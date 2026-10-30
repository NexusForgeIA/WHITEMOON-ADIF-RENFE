#!/usr/bin/env python3
"""RailGuard · servidor (solo librería estándar).

  python3 server.py                          simulación sobre captura real; los trenes OBEDECEN las órdenes
  python3 server.py --source renfe --gtfs Z  feed oficial de Renfe (GTFS-RT)
  python3 server.py --source URL             feed con el mismo esquema que /api/estado

Superficies:
  /          panel de control (operador)          GET /api/snapshot
  /tablet    app de cabina (PWA, requiere HTTPS)  POST /api/tablet/pos · /api/tablet/ack  (cabecera X-Driver-Token)
Variables: RAILGUARD_TOKEN -> los POST del panel exigen X-Token; emitir/revocar tokens de maquinista exige que exista.
"""
import argparse, base64, hmac, json, math, os, random, threading, time, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import gzip
import proximity
import scenarios
from centres import Centres, NATIONAL
from drivers import Drivers
from engine import Engine
from infra import Infra
from ltv import Ltv
from emergency import Emergency
from traffic import Traffic
import persist
import punctuality
import systems
import forecast

ROOT = os.path.dirname(os.path.abspath(__file__))
CFG = {"single_track": [["54404", "54405"]]}  # DEMO: la lista real debe salir de la infraestructura de Adif
K = 1.2
SEV_FACTOR = {0: 1.0, 1: 0.85, 2: 0.6, 3: 0.0}
LAT_N, LON_W, KM_LAT, KM_LON = 44.0, -10.0, 111.19, 111.32 * math.cos(math.radians(40.0))
ONLINE_S = 10          # una tablet cuenta como conectada si informó hace menos de esto
ESCALATE_ALERT_S = 20  # alerta sin 'enterado' o sin canal -> se eleva al operador
ESCALATE_ITEM_S = 60   # situación CRÍTICA sin reconocer por su centro -> se eleva a todos los centros
EVENT_KINDS_ALWAYS = {"SYS", "FAULT", "MSG", "HANDOVER", "CENTRE"}
MAX_TABLET_DEVIATION_KM = 15  # tablet a más de esto del feed del mismo tren: se ignora (¿tren equivocado?)


def project(lat, lon):
    return (lon - LON_W) * KM_LON, (LAT_N - lat) * KM_LAT


def _load(name):
    return json.load(open(os.path.join(ROOT, "data", name), encoding="utf-8"))


class App:
    def __init__(self, source=None, gtfs=None):
        self.lock = threading.RLock()
        self.source = source
        self.mode = "live" if source else "sim"
        self.feed = None
        cfg = dict(CFG)
        if source == "renfe":  # feed oficial de Renfe: coordenadas en km, sin lista de vía única de demo
            from renfe_adapter import RenfeFeed, load_gtfs
            self.feed = RenfeFeed(load_gtfs(gtfs) if gtfs else None)
            # Umbrales de modo LIVE: el feed de Renfe es ruidoso (GPS que salta, velocidades derivadas de posiciones).
            # Un exceso/salto hay que verlo en varios ciclos antes de frenar; los datos imposibles se descartan (B1).
            # Valores de RailGuard, a validar con Adif; NO son parámetros oficiales.
            cfg = {"km_per_px": 1.0, "single_track": [], "overspeed_persist": 3, "jump_persist": 4,
                   "stale_s": 120, "stale_restrict_s": 300, "default_max_speed": 310, "speed_implausible_kmh": 340,
                   # el mapa producto→velocidad es un supuesto sin validar: en vivo se usa el máximo de red hasta cargar velocidades de línea de Adif
                   "max_speed_by_product": {k: 310 for k in (2, 3, 28, 10, 11, 13, 16, 18, 19)}}
        self.active = set()
        self.token = os.environ.get("RAILGUARD_TOKEN")
        if self.mode == "sim":
            fx = _load("fixture.json")
            self.est, self.base = fx["est"], {t["n"]: t for t in fx["trains"]}
        else:
            self.est, self.base = {}, {}
        self.engine = Engine(self.est, cfg=cfg, log_path=os.path.join(ROOT, "data", "events.jsonl"))
        self.engine.set_lines([dict(c) for c in _load("infrastructure.json")["corridors"]])
        if self.feed:
            self.engine.est.update(self.feed.est)
        self.cercanias = None   # capa informativa de Cercanías: aislada del motor de seguridad
        if self.feed and not os.environ.get("RG_NO_CERCANIAS"):
            try:
                from cercanias import CercaniasFeed
                self.cercanias = CercaniasFeed(self.engine.cfg["km_per_px"])
                self.cercanias.start()
            except Exception as ex:
                print("Cercanías no disponible:", repr(ex))
        self.operators = _load("operators.json")
        self.drivers = Drivers(os.path.join(ROOT, "data", "drivers.json"))
        self.tablets = {}        # tren -> {x,y (km),ts,acc,driver}
        self.tablet_seen = {}    # tren -> última comunicación (ms)
        self.demo_tablets = set()
        self.deliv = {}          # "par|tren" -> {sent, seen, ack}
        self.bad_auth = {}       # ip -> [t,...]
        self.mismatch_logged = set()
        self.centres = Centres(os.path.join(ROOT, "data", "centres.json"), os.path.join(ROOT, "data", "centres_auth.json"))
        if self.mode == "sim":   # tokens de demostración (en producción se emiten con /api/centre/issue)
            for cid in [*self.centres.c, NATIONAL]:
                self.centres.add_demo(f"ctc-{cid}", cid)
        self.zones, self.zone_info, self.item_first = {}, {}, {}
        self.sim, self.last, self.t_reset = {}, time.time(), time.time()
        if self.mode == "sim":
            self._reset_sim()

    # ---------- simulación con lazo cerrado: los trenes obedecen a B5 ----------
    def _reset_sim(self):
        self.sim = {}
        for n, t in self.base.items():
            self._add_sim(n, t)
        self.engine.prev.clear()
        self.t_reset = time.time()

    def _add_sim(self, n, t):
        m = math.hypot(t["vx"], t["vy"])
        self.sim[n] = {"x": t["x"], "y": t["y"], "k0": t["kmh"], "kmh": t["kmh"], "ux": t["vx"] / m if m else 0,
                       "uy": t["vy"] / m if m else 0}

    def _sim_frame(self, now, dt):
        out = []
        frozen = {}
        for sid in self.active:
            frozen.update(scenarios.frozen(sid))
        for n, s in self.sim.items():
            t = self.base[n]
            st = self.engine.state.get(n)
            sev = max(st["sev"] if st else 0, self.engine.manual.get(n, {}).get("sev", 0))
            target = s["k0"] * SEV_FACTOR[sev]
            rate = 3.6 if target < s["kmh"] else 1.8  # frena 1,0 m/s², acelera 0,5 m/s²
            s["kmh"] = max(target, s["kmh"] - rate * dt) if target < s["kmh"] else min(target, s["kmh"] + rate * dt)
            adv = s["kmh"] / 3600 / K * dt
            sig = self.est.get(t["sig"])
            if sig and t["sig"] != t["ant"]:
                rem = math.hypot(sig["x"] - s["x"], sig["y"] - s["y"])
                if rem < 0.5 + adv:
                    s["kmh"], adv = 0, 0
            s["x"] += s["ux"] * adv
            s["y"] += s["uy"] * adv
            v = s["kmh"] / 3600 / K
            d = dict(t)
            d.update(x=s["x"], y=s["y"], kmh=round(s["kmh"]), vx=s["ux"] * v, vy=s["uy"] * v,
                     ts=int(now - frozen.get(n, 0) * 1000))
            out.append(d)
        return out

    # ---------- trenes que solo existen por su tablet (operadores sin feed público) ----------
    def _tablet_raw(self, known, now):
        k = self.engine.cfg["km_per_px"]
        out = []
        for tn, tb in self.tablets.items():
            if tn in known or tb.get("demo") or now - tb["ts"] > self.engine.cfg["tablet_fresh_s"] * 1000:
                continue
            spd, hdg = tb.get("spd") or 0.0, tb.get("hdg")
            vx = vy = 0.0
            if hdg is not None and spd > 0.5:       # m/s -> km/s -> px/s
                v = spd / 1000 / k
                vx, vy = math.sin(math.radians(hdg)) * v, -math.cos(math.radians(hdg)) * v
            out.append({"n": tn, "p": 0, "x": tb["x"] / k, "y": tb["y"] / k, "kmh": spd * 3.6, "vx": vx, "vy": vy,
                        "ts": tb["ts"], "ant": None, "sig": None, "des": None, "mat": f"tab-{tn}", "ret": 0, "op": tb.get("op", "?")})
        return out

    # ---------- ciclo del supervisor (feed) ----------
    def tick(self):
        with self.lock:
            now = int(time.time() * 1000)
            dt = min(time.time() - self.last, 5)
            self.last = time.time()
            if self.mode == "sim":
                idle = not self.active and not any(s["sev"] == 3 for s in self.engine.state.values())
                if idle and time.time() - self.t_reset > 150 and not self.demo_tablets:
                    self._reset_sim()
                raw = self._sim_frame(now, dt)
                if "supervisor_ciego" in self.active:
                    raw = None
                self.engine.fault_inject = {"B3"} if "fallo_barrera" in self.active else set()
                for sid in self.active:   # telemetría ATP de los trenes sintéticos
                    for tn, rec in scenarios.atp(sid).items():
                        self.engine.set_atp(tn, rec, now)
            elif self.feed:
                try:
                    _, raw = self.feed.fetch()
                except Exception as ex:
                    self.engine.log("SYS", f"Fallo de lectura del feed de Renfe: {ex!r}")
                    raw = None
            else:
                try:
                    with urllib.request.urlopen(self.source, timeout=8) as r:
                        data = json.load(r)
                    self.engine.est.clear()
                    self.engine.est.update(data["est"])
                    raw = data["trains"]
                except Exception as ex:
                    self.engine.log("SYS", f"Fallo de lectura del feed: {ex!r}")
                    raw = None
            if raw is not None:
                raw = list(raw) + self._tablet_raw({d["n"] for d in raw}, now)
            elif self.tablets:   # feed caído: las tablets frescas siguen alimentando al supervisor
                raw = self._tablet_raw(set(), now) or None
            self.engine.step(raw, now)
            self._update_zones(now)

    # ---------- zonas y traspasos entre centros ----------
    def _update_zones(self, now):
        new, info = {}, {}
        for t in self.engine.trains:
            z, nb, _ = self.centres.assign(t.n, t.x, t.y)
            new[t.n], info[t.n] = z, (z, nb)
        for n, z in new.items():
            old = self.zones.get(n)
            if old and old != z:
                self.engine.log("HANDOVER", f"Tren {n}: {self.centres.name(old)} → {self.centres.name(z)}", train=n)
                self.centres.send("sistema", z, f"Recibe el tren {n} (viene de {self.centres.name(old)})", now)
                self.centres.send("sistema", old, f"Cede el tren {n} a {self.centres.name(z)}", now)
        self.zones, self.zone_info = new, info

    # ---------- ciclo de proximidad (1 s, usa GPS de las tablets) ----------
    def prox_tick(self):
        with self.lock:
            now = int(time.time() * 1000)
            if self.mode == "sim":
                for tn in list(self.demo_tablets):
                    s = self.sim.get(tn)
                    if s:   # la 'tablet' demo sigue al tren con ruido GPS de ~5 m
                        self.tablets[tn] = {"x": s["x"] * K + random.gauss(0, .004), "y": s["y"] * K + random.gauss(0, .004),
                                            "ts": now, "acc": 5, "driver": "demo"}
                        self.tablet_seen[tn] = now
            # alta inmediata de trenes que solo existen por su tablet (sin esperar al siguiente ciclo del feed)
            from engine import parse_train
            have = {t.n for t in self.engine.trains}
            for d in self._tablet_raw(have, now):
                self.engine.trains.append(parse_train(d, self.engine.cfg["km_per_px"]))
            self._update_zones(now)
            self.engine.proximity_update(self.tablets, now)
            live = set()
            for p in self.engine.prox:
                if p["level"] != "RED":
                    continue
                for tn in (p["a"], p["b"]):
                    key = f"{p['key']}|{tn}"
                    live.add(key)
                    if key not in self.deliv:
                        self.deliv[key] = {"sent": now, "seen": None, "ack": None, "pair": p["key"], "train": tn}
            for key in [k for k in self.deliv if k not in live]:
                d = self.deliv.pop(key)
                f = lambda v: "—" if v is None else f"{(v - d['sent']) / 1000:.0f} s"
                self.engine.log("ALERT", f"Alerta cerrada {d['pair']} → tren {d['train']}: entregada {f(d['seen'])}, enterado {f(d['ack'])}",
                                train=d["train"], pair=d["pair"])

    # ---------- escenarios ----------
    def set_scenario(self, sid, on):
        with self.lock:
            if sid not in {s[0] for s in scenarios.LIST}:
                return False, "Escenario desconocido"
            if on:
                self.active.add(sid)
                for t in scenarios.synthetic(sid, self.est):
                    self.base[t["n"]] = t
                    self._add_sim(t["n"], t)
                scenarios.once(sid, self.sim)
                self.engine.log("SCENARIO", f"Inyectado: {sid}")
            else:
                self.active.discard(sid)
                for t in scenarios.synthetic(sid, self.est):
                    self.base.pop(t["n"], None)
                    self.sim.pop(t["n"], None)
                    self.tablets.pop(t["n"], None)
                    self.demo_tablets.discard(t["n"])
                    self.engine.forget(t["n"])
                self.engine.log("SCENARIO", f"Retirado: {sid}")
            return True, "ok"

    # ---------- canal privado de cabina ----------
    def auth_tablet(self, token, ip):
        with self.lock:
            now = time.time()
            fails = [t for t in self.bad_auth.get(ip, []) if now - t < 60]
            if len(fails) >= 20:
                return None, "demasiados intentos"
            rec = self.drivers.auth(token)
            if not rec and self.mode == "sim" and token and token.startswith("demo-") and token[5:] in self.base:
                tn = token[5:]
                rec = {"id": f"demo-{tn}", "operator": self.base[tn].get("op", "?"), "train": tn}
            if not rec:
                self.bad_auth[ip] = fails + [now]
                return None, "token no válido"
            return rec, None

    def _op_name(self, oid):
        return next((o["name"] for o in self.operators if o["id"] == oid), oid)

    def tablet_pos(self, rec, body):
        with self.lock:
            now = int(time.time() * 1000)
            tn = rec["train"]
            warn = None
            if body.get("demo") and self.mode == "sim":
                self.demo_tablets.add(tn)
            elif "lat" in body:
                try:
                    lat, lon, acc = float(body["lat"]), float(body["lon"]), float(body.get("acc", 50))
                except (TypeError, ValueError):
                    return 400, {"ok": False, "msg": "posición inválida"}
                if not (math.isfinite(lat) and math.isfinite(lon) and 27 <= lat <= 44.5 and -19 <= lon <= 5.5):
                    return 400, {"ok": False, "msg": "posición fuera de España"}
                x, y = project(lat, lon)
                tr = next((t for t in self.engine.trains if t.n == tn), None)
                if acc > 500:
                    warn = "GPS impreciso (>500 m): se usa la posición de la red"
                elif tr and math.hypot(tr.x - x, tr.y - y) > MAX_TABLET_DEVIATION_KM:
                    warn = "La tablet no coincide con la posición del tren: se ignora"
                    if tn not in self.mismatch_logged:
                        self.mismatch_logged.add(tn)
                        self.engine.log("SYS", f"Tablet de {rec['id']} a >{MAX_TABLET_DEVIATION_KM} km del tren {tn}: ignorada")
                else:
                    spd, hdg = body.get("spd"), body.get("hdg")
                    spd = float(spd) if isinstance(spd, (int, float)) and math.isfinite(spd) and 0 <= spd < 120 else None
                    hdg = float(hdg) % 360 if isinstance(hdg, (int, float)) and math.isfinite(hdg) else None
                    self.tablets[tn] = {"x": x, "y": y, "ts": now, "acc": acc, "driver": rec["id"], "op": rec["operator"],
                                        "spd": spd, "hdg": hdg}
            self.tablet_seen[tn] = now
            return 200, self.tablet_state(rec, now, warn)

    def tablet_state(self, rec, now, warn=None):
        tn = rec["train"]
        by_n = {t.n: t for t in self.engine.trains}
        alerts, near = [], []
        for p in self.engine.prox:
            if tn not in (p["a"], p["b"]):
                continue
            me_is_a = tn == p["a"]
            other = p["b"] if me_is_a else p["a"]
            (mx, my, _), (ox, oy, _) = (p["a_xy"] + (0,), p["b_xy"] + (0,)) if me_is_a else (p["b_xy"] + (0,), p["a_xy"] + (0,))
            dx, dy = ox - mx, oy - my   # x este, y sur
            ot = by_n.get(other)
            item = {"key": p["key"], "other": other, "other_op": self._op_name(ot.op) if ot else "?",
                    "dist_km": p["dist_km"], "east_km": round(dx, 3), "north_km": round(-dy, 3),
                    "bearing": round(proximity.bearing(dx, dy)), "closing_kmh": p["closing_kmh"],
                    "other_kmh": round(ot.kmh) if ot else None, "reason": p["reason"]}
            if p["level"] == "RED":
                d = self.deliv.get(f"{p['key']}|{tn}")
                if d and d["seen"] is None:
                    d["seen"] = now
                alerts.append({**item, "level": "CRITICAL" if p["critical"] else "RED", "since": p["since"],
                               "acked": bool(d and d["ack"])})
            else:
                near.append(item)
        alerts.sort(key=lambda a: a["dist_km"])
        near.sort(key=lambda a: a["dist_km"])
        me = by_n.get(tn)
        return {"ok": True, "now": now, "driver": rec["id"], "train": tn, "operator": self._op_name(rec["operator"]),
                "speed_kmh": round(me.kmh) if me else None, "pos_src": self.engine.pos_src.get(tn, "feed"),
                "feed_degraded": bool(self.engine.degraded), "warn": warn, "alerts": alerts, "near": near[:5],
                "threshold_km": self.engine.cfg["proximity_km"]}

    def tablet_ack(self, rec, key):
        with self.lock:
            d = self.deliv.get(f"{key}|{rec['train']}")
            if not d:
                return 200, {"ok": True, "msg": "la alerta ya no está activa"}
            if d["ack"] is None:
                d["ack"] = int(time.time() * 1000)
                self.engine.log("ALERT", f"Maquinista {rec['id']} (tren {rec['train']}) confirma alerta {key} en "
                                f"{(d['ack'] - d['sent']) / 1000:.0f} s", train=rec["train"], pair=key)
            return 200, {"ok": True}

    def prox_queue(self, now):
        q = []
        for p in self.engine.prox:
            if p["level"] != "RED":
                continue
            parts, esc = [], False
            for tn in (p["a"], p["b"]):
                d = self.deliv.get(f"{p['key']}|{tn}")
                online = now - self.tablet_seen.get(tn, 0) < ONLINE_S * 1000
                st = ("sin canal de cabina" if not online else "enterado" if d and d["ack"]
                      else "entregada" if d and d["seen"] else "enviada")
                if d and (not online or not d["ack"]) and now - d["sent"] > ESCALATE_ALERT_S * 1000:
                    esc = True
                parts.append(f"{tn}: {st}")
            q.append({"key": f"prox:{p['key']}", "level": "CRITICA" if esc else "AVISO", "train": p["a"],
                      "title": f"Proximidad {p['dist_km']:.1f} km entre {p['a']} y {p['b']} ({p['reason']})",
                      "auto": ["Alarma roja y sirena enviadas a las tablets", " · ".join(parts)],
                      "barriers": ["B6"], "can_rearm": False, "ack": False,
                      "action": "Llamar a ambas cabinas por GSM-R (sin confirmación en %d s)" % ESCALATE_ALERT_S if esc
                      else "Seguimiento: esperando enterado de los maquinistas"})
        return q

    # ---------- salidas ----------
    def snapshot(self):
        with self.lock:
            now = int(time.time() * 1000)
            s = self.engine.snapshot()
            k = self.engine.cfg["km_per_px"]
            s["mode"] = self.mode
            s["scenarios"] = [{"id": i, "label": l, "desc": d, "active": i in self.active} for i, l, d in scenarios.LIST]
            s["operator"] = self.prox_queue(now) + s["operator"]
            by_n = {t.n: t for t in self.engine.trains}
            s["proximity"] = [{"key": p["key"], "a": p["a"], "b": p["b"], "dist_km": p["dist_km"], "level": p["level"],
                               "reason": p["reason"], "critical": p.get("critical", False),
                               "ax": p["a_xy"][0] / k, "ay": p["a_xy"][1] / k, "bx": p["b_xy"][0] / k, "by": p["b_xy"][1] / k}
                              for p in self.engine.prox]
            s["tablets"] = [{"train": tn, "driver": self.tablets.get(tn, {}).get("driver", "—"),
                             "online": now - seen < ONLINE_S * 1000, "age_s": round((now - seen) / 1000),
                             "acc_m": self.tablets.get(tn, {}).get("acc")} for tn, seen in self.tablet_seen.items()]
            cnt = {}
            for t in by_n.values():
                cnt[t.op] = cnt.get(t.op, 0) + 1
            known = {o["id"] for o in self.operators}
            s["operators"] = ([{**{k2: v for k2, v in o.items() if k2 in ("id", "name", "type", "verified")},
                                "trains": cnt.get(o["id"], 0)} for o in self.operators]
                              + [{"id": i, "name": i, "type": "?", "verified": False, "trains": n} for i, n in cnt.items() if i not in known])
            s["drivers"] = self.drivers.listing()
            s["proximity_km"] = self.engine.cfg["proximity_km"]
            s["proximity_mode"] = self.engine.cfg["proximity_mode"]
            self._annotate(s, now)
            try:   # informativo: nunca puede romper la lectura de datos de seguridad
                s["forecast"] = forecast.predict(self.engine)
            except Exception as ex:
                s["forecast"] = {"items": [], "total": 0, "horizon_s": 0, "note": "Previsión no disponible: " + repr(ex)[:100]}
            try:
                s["cercanias"] = self.cercanias.snapshot() if self.cercanias else None
            except Exception as ex:
                s["cercanias"] = {"ok": False, "err": repr(ex)[:100], "trains": [], "count": 0}
            try:
                s["outages"] = self.systems()["outages"]
            except Exception as ex:
                s["outages"] = [{"id": "OUTAGES-ERR", "sev": "WARN", "system": "Panel", "title": "No se pudo calcular el estado de sistemas",
                                 "detail": repr(ex)[:120], "trains": [], "applying": "", "covering": []}]
            c = s.get("cercanias")
            if c is not None and not c.get("ok"):   # solo informativo: no afecta a la supervisión de larga distancia
                s["outages"] = list(s.get("outages") or []) + [{
                    "id": "CERCANIAS-FEED", "sev": "INFO", "system": "Capa Cercanías (informativa)",
                    "title": "Sin datos de Cercanías", "detail": (c.get("err") or "Feed sin actualizar")[:120], "trains": [],
                    "applying": "Los trenes de Cercanías no entran en las barreras de seguridad; solo se dibujan como referencia.", "covering": []}]
            return s

    # ---------- ámbito por centro ----------
    def _annotate(self, s, now):
        """Asigna a cada tren su zona y a cada situación del operador su(s) centro(s); aplica el escalado."""
        self._update_zones(now)
        zones = self.zones
        dropped = set(self.centres.dropped(now))
        for t in s["trains"]:
            t["zone"] = zones.get(t["n"])
        keys = set()
        for it in s["operator"]:
            key = it["key"]
            keys.add(key)
            if key.startswith("prox:"):
                cs = {zones.get(x) for x in key[5:].split("|")} - {None}
            elif it.get("train") in zones:
                cs = {zones[it["train"]]}
            else:
                cs = {"*"}
            it["ack"] = it.get("ack") or key in self.engine.acks
            first = self.item_first.setdefault(key, now)
            esc = (it["level"] == "CRITICA" and not it["ack"] and now - first > ESCALATE_ITEM_S * 1000) or bool(cs & dropped)
            it["escalated"] = esc
            it["zone"] = sorted(c for c in cs if c != "*")
            it["centres"] = ["*"] if (esc or "*" in cs) else sorted(cs)
        for k in [k for k in self.item_first if k not in keys]:
            del self.item_first[k]
        for cid in sorted(dropped):
            key = f"centre:{cid}"
            s["operator"].insert(0, {"key": key, "level": "CRITICA", "train": None, "escalated": True, "centres": ["*"], "zone": [cid],
                                     "title": f"{self.centres.name(cid)} sin conexión: su zona queda sin supervisión humana",
                                     "auto": ["Las barreras automáticas B0–B5 siguen activas", "Sus situaciones se escalan a todos los centros"],
                                     "barriers": ["B6"], "action": "Contactar con el centro por línea telefónica",
                                     "can_rearm": False, "ack": key in self.engine.acks})
        count = {c: {"trains": 0, "queue": 0} for c in self.centres.c}
        for z in zones.values():
            if z in count:
                count[z]["trains"] += 1
        for it in s["operator"]:
            for c in count:
                if c in it["centres"] or "*" in it["centres"]:
                    count[c]["queue"] += 1
        s["centres"] = [{"id": cid, "name": c["name"], "online": self.centres.online(cid, now), "seen": cid in self.centres.seen,
                         "age_s": round((now - self.centres.seen[cid]) / 1000) if cid in self.centres.seen else None,
                         **count[cid]} for cid, c in self.centres.c.items()]
        s["messages"] = self.centres.messages_for(NATIONAL)

    def auth_centre(self, token, ip):
        with self.lock:
            now = time.time()
            fails = [t for t in self.bad_auth.get(ip, []) if now - t < 60]
            if len(fails) >= 20:
                return None, "demasiados intentos"
            cid = self.centres.auth(token)
            if not cid:
                self.bad_auth[ip] = fails + [now]
                return None, "token de centro no válido"
            return cid, None

    def train_detail(self, n):
        """Ficha de un tren: datos del motor + horarios del GTFS (solo en modo Renfe)."""
        with self.lock:
            s = self.engine.snapshot()
            t = next((x for x in s["trains"] if x["n"] == n), None)
            if not t:
                return None
            d = {"n": n, "kmh": t["kmh"], "cmd": t["cmd"], "ret_min": t["ret"], "from": t["from"], "to": t["to"],
                 "dest": t["dest"], "line": t["line"], "signalling": t["signalling"], "atp": t["atp"],
                 "op": t["op"], "src": t["src"],
                 "operator": next((o["name"] for o in self.operators if o["id"] == t["op"]), t["op"]),
                 "alerts": [{"barrier": h["barrier"], "sev": h["sev"], "msg": h["msg"]}
                            for h in s["hazards"] if n in h["trains"]][:6]}
            extra = (getattr(self.feed, "detail", None) or {}).get(n)
            if extra:
                d.update({k: v for k, v in extra.items() if v is not None and k != "n"})
            return d

    def systems(self):
        with self.lock:
            now = int(time.time() * 1000)
            tabs = sum(1 for tn, seen in self.tablet_seen.items() if now - seen < ONLINE_S * 1000)
            on = sum(1 for cid in self.centres.c if self.centres.online(cid, now))
            return systems.build(self.engine, {"tablets_online": tabs, "centres_online": on,
                                               "centres_total": len(self.centres.c), "mode": self.mode})

    def centre_snapshot(self, cid):
        with self.lock:
            now = int(time.time() * 1000)
            self.centres.touch(cid, now)
            s = self.snapshot()
            s["centre"] = {"id": cid, "name": self.centres.name(cid), "role": "nacional" if cid == NATIONAL else "regional"}
            if cid == NATIONAL:
                return s
            mine = {n for n, z in self.zones.items() if z == cid}
            incoming = {n for n, (z, nb) in self.zone_info.items() if nb == cid and z != cid}
            vis = mine | incoming
            by = {t["n"]: t for t in s["trains"]}
            k = s["unit_km"]
            keep = set()   # estaciones: las de la zona + las que rodean a los trenes visibles
            for st in s["stations"]:
                x, y = st["x"] * k, st["y"] * k
                if self.centres.nearest(x, y) == cid or any(
                        math.hypot(x - by[n]["x"] * k, y - by[n]["y"] * k) < 30 for n in vis if n in by):
                    keep.add(st["c"])
            s["stations"] = [st for st in s["stations"] if st["c"] in keep]
            s["segments"] = [sg for sg in s["segments"] if sg[0] in keep and sg[1] in keep]
            runs = []
            for c in s["corridors"]:
                run = []
                for code in c["stations"] + [None]:
                    if code in keep:
                        run.append(code)
                    else:
                        if len(run) >= 2:
                            runs.append({**c, "stations": run})
                        run = []
            s["corridors"] = runs
            names = {st["c"]: st["n"] for st in s["stations"]}
            s["locked_pairs"] = [p for p in s["locked_pairs"] if p[0] in keep and p[1] in keep]
            s["locked"] = [f"{names[a]} ↔ {names[b]}" for a, b in s["locked_pairs"]]
            s["trains"] = [t for t in s["trains"] if t["n"] in vis]
            for t in s["trains"]:
                t["incoming"] = t["n"] in incoming
            s["hazards"] = [h for h in s["hazards"] if any(n in vis for n in h["trains"])]
            s["proximity"] = [p for p in s["proximity"] if p["a"] in vis or p["b"] in vis]
            s["tablets"] = [t for t in s["tablets"] if t["train"] in vis]
            s["operator"] = [it for it in s["operator"] if cid in it["centres"] or "*" in it["centres"]]
            s["drivers"] = []
            cnt = {"NONE": 0, "CAUTION": 0, "RESTRICT": 0, "STOP": 0}
            ops = {}
            for t in s["trains"]:
                cnt[t["cmd"]] += 1
                ops[t["op"]] = ops.get(t["op"], 0) + 1
            s["kpi"] = {"trains": len(s["trains"]), "clear": cnt["NONE"], "caution": cnt["CAUTION"], "restrict": cnt["RESTRICT"], "stop": cnt["STOP"]}
            s["operators"] = [{**o, "trains": ops.get(o["id"], 0)} for o in s["operators"]]
            s["handover"] = {"out": [{"train": n, "to": self.centres.name(self.zone_info[n][1])} for n in sorted(mine)
                                     if self.zone_info.get(n, (None, None))[1]],
                             "in": [{"train": n, "from": self.centres.name(self.zone_info[n][0])} for n in sorted(incoming)]}
            vs = vis | {str(x) for x in vis}
            s["events"] = [e for e in s["events"]
                           if e["kind"] in EVENT_KINDS_ALWAYS or any(len(n) >= 4 and n in e["msg"] for n in vs)]
            s["messages"] = self.centres.messages_for(cid)
            return s

    def centre_post(self, cid, path, body):
        with self.lock:
            now = int(time.time() * 1000)
            who = f"{self.centres.name(cid)}·{str(body.get('who') or 'operador')[:30]}"
            if path == "/api/centre/ack":
                key = str(body.get("key", ""))[:80]
                it = next((i for i in self.snapshot()["operator"] if i["key"] == key), None)
                if not it or not (cid == NATIONAL or cid in it["centres"] or "*" in it["centres"]):
                    return 403, {"ok": False, "msg": "Esa situación no pertenece a su centro"}
                ok, msg = self.engine.ack(key, who)
            elif path in ("/api/centre/rearm", "/api/centre/manual"):
                tn = str(body.get("train", ""))[:30]
                restricting = path == "/api/centre/manual" and not body.get("release")
                z = self.zones.get(tn)
                if not restricting and cid != NATIONAL and z != cid:
                    return 403, {"ok": False, "msg": f"Rechazado: el tren {tn} pertenece a la zona de "
                                 f"{self.centres.name(z) if z else 'ningún centro'}. Solo puede añadir restricciones."}
                if path == "/api/centre/rearm":
                    ok, msg = self.engine.rearm(tn, who, principal=cid)
                elif body.get("release"):
                    ok, msg = self.engine.release_manual(tn, who)
                else:   # añadir una restricción es siempre posible, también sobre trenes de otra zona
                    ok, msg = self.engine.manual_restrict(tn, who)
                    if z and z != cid and cid != NATIONAL:
                        self.centres.send(cid, z, f"{self.centres.name(cid)} ha restringido su tren {tn}", now)
            elif path == "/api/centre/message":
                m = self.centres.send(cid, str(body.get("to", "")), str(body.get("text", "")), now)
                if not m:
                    return 400, {"ok": False, "msg": "mensaje o destinatario no válido"}
                self.engine.log("MSG", f"{self.centres.name(cid)} → {self.centres.name(m['to']) if m['to'] != '*' else 'todos'}: {m['text']}")
                ok, msg = True, "enviado"
            else:
                return 404, {"ok": False, "msg": "no existe"}
            return 200, {"ok": ok, "msg": msg}

    def post(self, path, body):
        with self.lock:
            who = str(body.get("who") or "operador")[:40]
            if path == "/api/rearm":
                ok, msg = self.engine.rearm(str(body.get("train")), who, principal=NATIONAL)
            elif path == "/api/ack":
                ok, msg = self.engine.ack(str(body.get("key")), who)
            elif path == "/api/manual":
                tn = str(body.get("train"))
                if body.get("release"):
                    ok, msg = self.engine.release_manual(tn, who)
                else:
                    ok, msg = self.engine.manual_restrict(tn, who)
            elif path == "/api/scenario" and self.mode == "sim":
                ok, msg = self.set_scenario(str(body.get("id")), bool(body.get("on")))
            elif path == "/api/reset" and self.mode == "sim":
                self.active.clear()
                self.base = {n: t for n, t in self.base.items() if not n.startswith("T-")}
                self.engine.state.clear(); self.engine.manual.clear(); self.engine.atp.clear()
                self.tablets.clear(); self.demo_tablets.clear(); self.deliv.clear()
                self._reset_sim(); self.engine.log("SYS", "Simulación reiniciada")
                ok, msg = True, "ok"
            elif path == "/api/proximity_mode":
                m = str(body.get("mode"))
                if m not in ("relevant", "strict"):
                    return 400, {"ok": False, "msg": "modo no válido"}
                self.engine.cfg["proximity_mode"] = m
                self.engine.log("SYS", f"{who} cambia el modo de proximidad a '{m}'")
                ok, msg = True, "ok"
            elif path == "/api/driver/issue":
                if not self.token:
                    return 403, {"ok": False, "msg": "defina RAILGUARD_TOKEN para emitir tokens de maquinista"}
                did, op, tr = str(body.get("id", ""))[:40], str(body.get("operator", ""))[:40], str(body.get("train", ""))[:20]
                if not (did and op and tr):
                    return 400, {"ok": False, "msg": "faltan id, operator o train"}
                tok = self.drivers.issue(did, op, tr)
                self.engine.log("SYS", f"{who} emite token al maquinista {did} (tren {tr}, {op})")
                return 200, {"ok": True, "token": tok, "msg": "Guárdelo ahora: no se vuelve a mostrar"}
            elif path == "/api/centre/issue":
                if not self.token:
                    return 403, {"ok": False, "msg": "defina RAILGUARD_TOKEN para emitir tokens de centro"}
                tok = self.centres.issue(str(body.get("centre", "")))
                if not tok:
                    return 400, {"ok": False, "msg": "centro desconocido"}
                self.engine.log("CENTRE", f"{who} emite token al centro {body.get('centre')}")
                return 200, {"ok": True, "token": tok, "msg": "Guárdelo ahora: no se vuelve a mostrar"}
            elif path == "/api/message":
                m = self.centres.send(NATIONAL, str(body.get("to", "")), str(body.get("text", "")), int(time.time() * 1000))
                if not m:
                    return 400, {"ok": False, "msg": "mensaje o destinatario no válido"}
                self.engine.log("MSG", f"{self.centres.name(NATIONAL)} → {self.centres.name(m['to']) if m['to'] != '*' else 'todos'}: {m['text']}")
                ok, msg = True, "enviado"
            elif path == "/api/driver/revoke":
                if not self.token:
                    return 403, {"ok": False, "msg": "defina RAILGUARD_TOKEN"}
                n = self.drivers.revoke(str(body.get("id", "")))
                self.engine.log("SYS", f"{who} revoca al maquinista {body.get('id')} ({n})")
                ok, msg = n > 0, f"{n} revocado(s)"
            else:
                return 404, {"ok": False, "msg": "no existe"}
            return 200, {"ok": ok, "msg": msg}


APP = None
STATIC = {"/": ("index.html", "text/html"), "/index.html": ("index.html", "text/html"), "/tablet": ("tablet.html", "text/html"), "/centro": ("index.html", "text/html"),
          "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
          "/sw.js": ("sw.js", "text/javascript"), "/icon.svg": ("icon.svg", "image/svg+xml"),
          "/logo.png": ("logo.png", "image/png"), "/og-image.png": ("og-image.png", "image/png"), "/favicon.png": ("favicon.png", "image/png"), "/basemap.json": ("basemap.json", "application/json")}


INFRA = None
LTV = None
EMG = None
TRAF = None
SYNC = None
_remote = persist.from_env()
if _remote:     # cachés en Supabase: sobreviven a los reinicios de Render. La descarga se acota para no retrasar el arranque.
    SYNC = persist.Sync(_remote, {os.path.join(ROOT, "data", f): f for f in ("infra_cache_v2.json", "ltv_cache.json", "emergency_cache.json", "punct_history.json")})
    _t = threading.Thread(target=SYNC.restore, daemon=True)
    _t.start()
    _t.join(60)
PUNCT = punctuality.History(os.path.join(ROOT, "data", "punct_history.json"))


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(b)

    def _viewer_ok(self):
        """Acceso de lectura protegido (RG_VIEW_PASSWORD): HTTP Basic, cualquier usuario. Sin variable = abierto (demo)."""
        pw = os.environ.get("RG_VIEW_PASSWORD")
        if not pw:
            return True
        try:
            got = base64.b64decode(self.headers.get("Authorization", "")[6:]).decode("utf-8", "replace").split(":", 1)[1]
        except Exception:
            got = ""
        if hmac.compare_digest(got.encode(), pw.encode()):
            return True
        body = "Acceso restringido".encode()
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="RailGuard · acceso restringido", charset="UTF-8"')
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return False

    def do_GET(self):
        path = self.path.split("?")[0]
        # abiertos con su propia autenticación o necesarios para la monitorización: salud, canal de centros y app de cabina
        if path not in ("/api/health", "/api/centre/snapshot", "/manifest.webmanifest", "/sw.js", "/icon.svg", "/logo.png", "/og-image.png", "/favicon.png", "/basemap.json") and not path.startswith("/tablet") and not self._viewer_ok():
            return
        if path == "/api/snapshot":
            return self._send(200, APP.snapshot())
        if path == "/api/systems":
            return self._send(200, APP.systems())
        if path == "/api/safety_systems":
            return self._send(200, _load("safety_systems.json"))
        if path == "/api/punct":
            k = punctuality.compute((t.n, t.ret, t.cat) for t in APP.engine.trains)
            return self._send(200, {**k, "history": PUNCT.series(), "source": "Feed GTFS-RT de Renfe (Larga Distancia, Avant, AVE); umbrales del compromiso de puntualidad de Renfe"})
        if path == "/api/trafico":
            return self._send(200, TRAF.api() if TRAF else {"ready": False, "items": []})
        if path == "/api/emergencia":
            return self._send(200, EMG.api() if EMG else {"ready": False, "items": []})
        if path == "/api/ltv":
            return self._send(200, LTV.api() if LTV else {"ready": False, "items": []})
        if path == "/api/infra":
            inf = INFRA
            if not inf or not inf.data:
                return self._send(200, {"ready": False, "status": inf.status if inf else {"state": "desactivada"}})
            raw = json.dumps({"ready": True, **inf.data}, separators=(",", ":")).encode()
            if "gzip" in self.headers.get("Accept-Encoding", ""):
                raw = gzip.compress(raw, 6)
                self.send_response(200)
                self.send_header("Content-Encoding", "gzip")
            else:
                self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "public, max-age=300")
            self.end_headers()
            return self.wfile.write(raw)
        if path == "/api/train":
            from urllib.parse import parse_qs, urlparse
            n = (parse_qs(urlparse(self.path).query).get("n") or [""])[0]
            d = APP.train_detail(n)
            return self._send(200, d) if d else self._send(404, {"ok": False, "msg": "tren desconocido"})
        if path == "/api/health":
            age = time.time() - APP.last
            return self._send(200 if age < 15 else 503, {"ok": age < 15, "cycle": APP.engine.cycle, "age_s": round(age, 1), "feed": getattr(APP.feed, "stats", None),
                                                                          "infra": INFRA.status if INFRA else None,
                                                                          "cercanias": (lambda c: {k: c[k] for k in ("ok", "err", "age_s", "count", "lines", "hdr_age_s")})(APP.cercanias.snapshot()) if APP.cercanias else None})
        if path == "/api/centre/snapshot":
            cid, err = APP.auth_centre(self.headers.get("X-Centre-Token", ""), self.client_address[0])
            return self._send(200, APP.centre_snapshot(cid)) if cid else self._send(401, {"ok": False, "msg": err})
        if path in STATIC:
            f, ct = STATIC[path]
            return self._send(200, open(os.path.join(ROOT, "dashboard", f), "rb").read(), ct)
        self._send(404, {"ok": False})

    def do_POST(self):
        try:
            n = min(int(self.headers.get("Content-Length", 0)), 4096)
            body = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(body, dict):
                raise ValueError
        except Exception:
            return self._send(400, {"ok": False, "msg": "JSON inválido"})
        if self.path in ("/api/tablet/pos", "/api/tablet/ack"):  # canal de cabina: token de maquinista, no el del panel
            rec, err = APP.auth_tablet(self.headers.get("X-Driver-Token", ""), self.client_address[0])
            if not rec:
                return self._send(401, {"ok": False, "msg": err})
            if self.path == "/api/tablet/pos":
                code, out = APP.tablet_pos(rec, body)
            else:
                code, out = APP.tablet_ack(rec, str(body.get("key", ""))[:80])
            return self._send(code, out)
        if self.path.startswith("/api/centre/") and self.path != "/api/centre/issue":   # panel de un centro: su propio token
            cid, err = APP.auth_centre(self.headers.get("X-Centre-Token", ""), self.client_address[0])
            if not cid:
                return self._send(401, {"ok": False, "msg": err})
            code, out = APP.centre_post(cid, self.path, body)
            return self._send(code, out)
        if not self._viewer_ok():
            return
        if APP.token and not hmac.compare_digest(self.headers.get("X-Token", ""), APP.token):
            return self._send(401, {"ok": False, "msg": "token requerido"})
        code, out = APP.post(self.path, body)
        self._send(code, out)


def main():
    global APP, INFRA, LTV, EMG, TRAF
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", help="'renfe' (feed oficial) o URL con el esquema de /api/estado")
    ap.add_argument("--gtfs", help="google_transit.zip de Renfe (ruta o URL); necesario para parada anterior, destino y producto")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--period", type=float, default=None)
    a = ap.parse_args()
    a.period = a.period or (15.0 if a.source == "renfe" else 2.0)
    APP = App(a.source, a.gtfs)
    if a.source == "renfe" and os.environ.get("RG_INFRA", "1") != "0":
        INFRA = Infra(os.path.join(ROOT, "data", "infra_cache_v2.json"), os.path.join(ROOT, "data", "infra_extra.json"))
        INFRA.start()
    if a.source == "renfe" and os.environ.get("RG_LTV", "1") != "0":
        LTV = Ltv(os.path.join(ROOT, "data", "ltv_cache.json"))
        LTV.start()
    if a.source == "renfe" and os.environ.get("RG_EMG", "1") != "0":
        EMG = Emergency(os.path.join(ROOT, "data", "emergency_cache.json"))
        threading.Timer(20, EMG.start).start()
    if a.source == "renfe" and os.environ.get("RG_TRAFFIC", "1") != "0":
        TRAF = Traffic(os.path.join(ROOT, "data", "traffic_cache.json"))
        TRAF.start()

    if SYNC:
        SYNC.start()

    def loop(fn, period):
        while True:
            try:
                fn()
            except Exception as ex:
                APP.engine.log("FAULT", f"Ciclo fallido: {ex!r}")
            time.sleep(period)

    def tick():
        if LTV:
            APP.engine.cfg["ltv_items"] = LTV.items
        APP.tick()
        if a.source == "renfe":
            PUNCT.add(punctuality.compute((t.n, t.ret, t.cat) for t in APP.engine.trains))
    threading.Thread(target=loop, args=(tick, a.period), daemon=True).start()
    threading.Thread(target=loop, args=(APP.prox_tick, 1.0), daemon=True).start()
    print(f"RailGuard ({APP.mode}) en http://{a.host}:{a.port}   ·   cabina: /tablet"
          + ("   ·   tokens demo: demo-<tren> (cabina) · ctc-madrid|barcelona|sevilla|nacional (panel /centro)" if APP.mode == "sim" else ""))
    ThreadingHTTPServer((a.host, a.port), H).serve_forever()


if __name__ == "__main__":
    main()
