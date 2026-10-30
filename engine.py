"""
RailGuard · motor de supervisión de seguridad en profundidad.

Principio de diseño
-------------------
La seguridad final NO depende de una persona. Hay 5 barreras automáticas e
independientes (B1..B5) antes de que un humano (B6) intervenga:

  B1  Integridad de datos      -> ¿puedo fiarme de lo que veo?
  B2  Supervisión de velocidad -> envolvente de velocidad + curva de frenado
  B3  Separación de bloques    -> distancia de seguridad / ocupación de bloque
  B4  Predicción de conflicto  -> cinemática: tiempo hasta colisión (TTC)
  B5  Enclavamiento (latch)    -> ejecuta, bloquea y NO suelta sin pruebas

Reglas de seguridad intrínseca (fail-safe):
  * Acciones RESTRICTIVAS: basta con UNA barrera (1ooN).
  * Acciones PERMISIVAS (liberar): hacen falta TODAS las barreras en limpio
    durante N ciclos consecutivos (NooN). Una persona sola nunca libera.
  * Si una barrera falla (excepción) o los datos se pierden -> el sistema
    se degrada hacia el lado restrictivo y escala al operador.
  * El humano solo recibe una situación YA contenida automáticamente.

IMPORTANTE: esto es una capa de SUPERVISIÓN sobre datos de posición. No
sustituye al enclavamiento, ATP/ASFA/ETCS ni a los circuitos de vía
certificados (EN 50126/50128/50129, SIL 4). Los comandos salen por una
interfaz de actuación (`actuators`) que debe conectarse a esos sistemas.
"""
from __future__ import annotations

import json
import math
import os
from collections import defaultdict, deque
from dataclasses import dataclass, field

import fleet_profile
import speed_profile
import ltv
import proximity

NONE, CAUTION, RESTRICT, STOP = 0, 1, 2, 3
SEV_NAME = {0: "NONE", 1: "CAUTION", 2: "RESTRICT", 3: "STOP"}

DEFAULT_CFG = {
    "km_per_px": 1.2,  # calibrado con Madrid-Sevilla / Madrid-Barcelona
    # Velocidad máxima por código de producto del feed (supuesto configurable)
    # SUPUESTO a calibrar con la velocidad de línea real (Adif). 28 se observa >280 km/h en el feed.
    "max_speed_by_product": {2: 310, 3: 310, 28: 310, 10: 250, 11: 250, 13: 250,
                             16: 160, 18: 160, 19: 140},
    "default_max_speed": 160,
    "unknown_product_max_speed": 310,  # producto sin clasificar: máximo de red (B2 queda con menos cobertura, no con falsos excesos)
    "decel_service": 0.6,       # m/s² (conservador; ETC ETCS(FN) Anexo D: ETCS asume 0,7 m/s² con adherencia reducida y 1,0 en el nivel 1)
    "spacing_margin_km": 0.5,
    "stale_s": 90,
    "feed_dead_s": 120,
    "jump_factor": 1.6,
    "ttc_stop_s": 120,
    "ttc_restrict_s": 300,
    "converge_eta_s": 45,
    "rearm_clear_cycles": 3,
    "rearm_dual": True,          # B7: el rearme de un STOP exige DOS autorizaciones de principales distintos
    "rearm_pending_s": 300,      # la primera autorización caduca
    "rearm_max_5min": 3,         # B7: máximo de rearmes completados por principal en 5 min
    "escalate_after_s": 180,
    "station_radius_km": 3.0,
    "single_track": [],         # lista de [codigoA, codigoB]
    "ltv_items": [],             # LTV de Adif (lo rellena el servidor desde ltv.py)
    "ltv_radius_km": 1.0,       # distancia máxima tren-punto de la LTV (el punto es aproximado)
    "ltv_margin": 1.25,         # tolerancia: la LTV es un punto, no un tramo exacto, y el tren puede estar ya frenando
    "tsr": {},                  # "A-B" -> km/h (limitaciones temporales Adif)
    "proximity_km": 3.0,        # regla de proximidad para las tablets de cabina
    "proximity_mode": "relevant",  # "relevant" | "strict" (ver proximity.py)
    "proximity_hold_s": 5,      # el ROJO se mantiene este tiempo tras desaparecer la condición
    "tablet_fresh_s": 10,       # antigüedad máxima de una posición de tablet para usarla
    "atp_stale_s": 15,
    # --- tolerancia al ruido del feed (valores de sim = sin filtro; el modo live los endurece, ver server.py) ---
    "speed_implausible_kmh": 360,   # por encima de esto la velocidad es un error de dato, no un exceso real (máx. red ≈ 310)
    "overspeed_persist": 1,         # ciclos consecutivos con exceso antes de ordenar nada (live: 3)
    "jump_persist": 1,              # saltos consecutivos para RESTRICT; el primero se avisa como CAUTION (live: 2)
    "stale_restrict_s": 90,         # posición caducada: CAUTION desde stale_s, RESTRICT desde aquí (live: 300)
}


# ───────────────────────── modelo ─────────────────────────
@dataclass
class Train:
    n: str
    product: int
    x: float
    y: float
    vx: float
    vy: float
    kmh: float
    ts: int
    ant: str | None
    sig: str | None
    des: str | None
    mat: str | None
    ret: int
    op: str = "?"

    @property
    def moving(self) -> bool:
        return self.kmh > 10

    def heading(self):
        m = math.hypot(self.vx, self.vy)
        return (self.vx / m, self.vy / m) if m > 1e-9 else None

    def undirected(self):
        if self.ant and self.sig and self.ant != self.sig:
            return tuple(sorted((self.ant, self.sig)))
        return None

    def directed(self):
        if self.ant and self.sig and self.ant != self.sig:
            return (self.ant, self.sig)
        return None


def parse_train(d: dict, k: float) -> Train:
    return Train(
        n=str(d["n"]), product=int(d.get("p") or 0),
        x=d["x"] * k, y=d["y"] * k,
        vx=(d.get("vx") or 0) * k, vy=(d.get("vy") or 0) * k,
        kmh=float(d.get("kmh") or 0), ts=int(d["ts"]),
        ant=d.get("ant"), sig=d.get("sig"), des=d.get("des"),
        mat=d.get("mat"), ret=int(d.get("ret") or 0), op=d.get("op") or "?",
    )


@dataclass
class Hazard:
    barrier: str
    sev: int
    trains: tuple
    seg: tuple | None
    code: str
    msg: str
    data: dict = field(default_factory=dict)

    @property
    def key(self):
        return f"{self.barrier}|{self.code}|{'+'.join(sorted(self.trains))}|{self.seg or ''}"


class Ctx:
    """Entrada inmutable de un ciclo. Cada barrera la lee por su cuenta."""

    def __init__(self, trains, est, cfg, now_ms, prev, streak=None):
        self.trains, self.est, self.cfg, self.now_ms, self.prev = trains, est, cfg, now_ms, prev
        self.streak = streak if streak is not None else {}
        self.seen = set()
        k = cfg["km_per_px"]
        self.st = {c: (s["x"] * k, s["y"] * k) for c, s in est.items()}
        self.atp = {}
        self.profile = None
        self.line_of = lambda seg: None

    def persist(self, key, cond):
        """Ciclos consecutivos en que `cond` es cierta para `key` (0 si no lo es)."""
        if not cond:
            return 0
        self.seen.add(key)
        self.streak[key] = self.streak.get(key, 0) + 1
        return self.streak[key]

    def name(self, code):
        return self.est.get(code, {}).get("n", code or "?")

    def vmax(self, t: Train):
        if not t.product:
            return self.cfg["unknown_product_max_speed"]
        return self.cfg["max_speed_by_product"].get(t.product, self.cfg["default_max_speed"])

    def brake_km(self, kmh):
        v = kmh / 3.6
        return v * v / (2 * self.cfg["decel_service"]) / 1000

    def seg_name(self, seg):
        return f"{self.name(seg[0])}↔{self.name(seg[1])}" if seg else "-"


# ───────────────────────── barreras ─────────────────────────
def b1_integrity(c: Ctx):
    out = []
    for t in c.trains:
        age = (c.now_ms - t.ts) / 1000
        if age > c.cfg["stale_s"]:
            sev = RESTRICT if age > max(c.cfg["stale_restrict_s"], c.cfg["stale_s"]) else CAUTION
            out.append(Hazard("B1", sev, (t.n,), t.undirected(), "STALE",
                              f"Posición caducada ({age:.0f} s): ocupación desconocida", {"age_s": round(age)}))
        p = c.prev.get(t.n)
        if p and t.ts > p[2]:
            dt = (t.ts - p[2]) / 1000
            d = math.hypot(t.x - p[0], t.y - p[1])
            reach = c.cfg["jump_factor"] * c.vmax(t) / 3600 * dt + 0.5
            n_j = c.persist(("JUMP", t.n), d > reach)
            if n_j:   # el primer salto aislado es casi siempre un glitch de GPS: se avisa; si se repite, se restringe
                out.append(Hazard("B1", RESTRICT if n_j >= c.cfg["jump_persist"] else CAUTION, (t.n,), t.undirected(), "JUMP",
                                  f"Salto de posición imposible: {d:.1f} km en {dt:.0f} s", {"km": round(d, 1)}))
    by = defaultdict(list)
    for t in c.trains:
        by[(round(t.x, 1), round(t.y, 1))].append(t)
    for (px, py), g in by.items():
        if len(g) < 2 or len({t.mat for t in g}) < 2:
            continue  # misma composición acoplada: legítimo
        near = min((math.hypot(px * 1 - sx, py * 1 - sy) for sx, sy in c.st.values()), default=1e9)
        if near > c.cfg["station_radius_km"]:
            out.append(Hazard("B1", CAUTION, tuple(t.n for t in g), None, "DUP_POS",
                              "Dos servicios distintos con idéntica posición fuera de estación", {}))
    return out


def b2_speed(c: Ctx):
    out = []
    for t in c.trains:
        if not t.moving:
            continue
        limit = c.vmax(t)
        seg = t.undirected()
        if seg:
            tsr = c.cfg["tsr"].get(f"{seg[0]}-{seg[1]}")
            if tsr:
                limit = min(limit, tsr)
        why = "envolvente de línea"
        if t.sig and t.sig == t.des and t.sig in c.st:
            d = max(math.hypot(t.x - c.st[t.sig][0], t.y - c.st[t.sig][1]), 0.3)
            curve = math.sqrt(2 * c.cfg["decel_service"] * d * 1000) * 3.6
            if curve < limit:
                limit, why = curve, f"curva de frenado a {c.name(t.sig)} ({d:.1f} km)"
        if t.kmh > c.cfg["speed_implausible_kmh"]:
            # velocidad físicamente imposible en la red española: dato erróneo, no exceso. Se avisa como duda de dato (B1), sin frenar.
            c.persist(("OVERSPEED", t.n), False)
            out.append(Hazard("B1", CAUTION, (t.n,), seg, "SPEED_IMPLAUSIBLE",
                              f"Velocidad imposible en el feed ({t.kmh:.0f} km/h): se descarta como dato erróneo",
                              {"kmh": round(t.kmh)}))
            continue
        prof = None
        if c.cfg.get("speed_profile", True):
            zl = speed_profile.slow_limit(c.st, t.x, t.y)
            if zl and zl[0] < limit:
                prof = zl
                limit, why = zl[0], f"zona lenta PK {zl[1]:.0f} (FCMAF, no oficial)"
        if not prof and c.cfg.get("ltv_items"):
            hit = [i for i in ltv.near(c.cfg["ltv_items"], t.x, t.y, c.cfg["ltv_radius_km"]) if i["kmh"] * c.cfg["ltv_margin"] < limit]
            if hit:
                i = hit[0]
                prof = (i["kmh"], i.get("pk0") or 0)
                limit, why = i["kmh"] * c.cfg["ltv_margin"], f"LTV Adif línea {i['line']} PK {i.get('pk0')}-{i.get('pk1')} ({i['kmh']} km/h; visor público, no certificado)"
        r = t.kmh / limit if limit else 0
        sev = STOP if r > 1.15 else RESTRICT if r > 1.08 else CAUTION if r > 1.03 else NONE
        if prof and sev > CAUTION:
            sev = CAUTION   # límite no oficial: nunca restringe ni frena por sí solo
        n_o = c.persist(("OVERSPEED", t.n), sev != NONE)
        if sev and n_o < c.cfg["overspeed_persist"]:
            sev = NONE if sev == CAUTION else CAUTION   # exceso aún no confirmado: solo aviso
        if sev:
            out.append(Hazard("B2", sev, (t.n,), seg, "OVERSPEED",
                              f"{t.kmh:.0f} km/h sobre límite {limit:.0f} ({why})",
                              {"kmh": round(t.kmh), "limit": round(limit)}))
    return out


def b3_block(c: Ctx):
    out = []
    groups = defaultdict(list)
    for t in c.trains:
        u = t.undirected()
        if u and u[0] in c.st and u[1] in c.st:
            groups[u].append(t)
    single = {tuple(sorted(p)) for p in c.cfg["single_track"]}
    for seg, ts in groups.items():
        if len(ts) < 2:
            continue
        dirs = {t.directed() for t in ts}
        if seg in single and len(dirs) > 1:
            fw = [t.n for t in ts if t.directed() == (seg[0], seg[1])]
            bw = [t.n for t in ts if t.directed() == (seg[1], seg[0])]
            out.append(Hazard("B3", STOP, tuple(fw + bw), seg, "HEADON",
                              f"Sentidos opuestos en vía única {c.seg_name(seg)}", {}))
        for d in dirs:
            same = [t for t in ts if t.directed() == d]
            if len(same) < 2:
                continue
            a, b = c.st[d[0]], c.st[d[1]]
            L = math.hypot(b[0] - a[0], b[1] - a[1]) or 1e-9
            ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
            same.sort(key=lambda t: (t.x - a[0]) * ux + (t.y - a[1]) * uy)
            for rear, front in zip(same, same[1:]):
                if rear.mat and rear.mat == front.mat:
                    continue
                gap = ((front.x - a[0]) * ux + (front.y - a[1]) * uy) - ((rear.x - a[0]) * ux + (rear.y - a[1]) * uy)
                need = c.brake_km(rear.kmh) + c.cfg["spacing_margin_km"]
                if gap < need:
                    sev = STOP if gap < 0.5 * need else RESTRICT
                    out.append(Hazard("B3", sev, (rear.n,), seg, "SPACING",
                                      f"{rear.n} a {gap:.1f} km de {front.n}; necesita {need:.1f} km",
                                      {"gap_km": round(gap, 2), "need_km": round(need, 2), "front": front.n}))
    return out


def b4_predict(c: Ctx):
    out = []
    ts = [t for t in c.trains if t.heading()]
    for i in range(len(ts)):
        for j in range(i + 1, len(ts)):
            a, b = ts[i], ts[j]
            if a.mat and a.mat == b.mat:
                continue
            ha, hb = a.heading(), b.heading()
            same_seg = a.undirected() and a.undirected() == b.undirected()
            if same_seg and ha[0] * hb[0] + ha[1] * hb[1] > 0.7:  # seguimiento en el mismo sentido
                rx, ry = b.x - a.x, b.y - a.y
                along = rx * ha[0] + ry * ha[1]
                rear, front, gap = (a, b, along) if along > 0 else (b, a, -along)
                hr = rear.heading()
                va = rear.kmh / 3600 - (front.vx * hr[0] + front.vy * hr[1])
                if va > 0 and gap > 0:
                    ttc = gap / va
                    if ttc < c.cfg["ttc_restrict_s"]:
                        sev = STOP if ttc < c.cfg["ttc_stop_s"] else RESTRICT
                        out.append(Hazard("B4", sev, (rear.n,), a.undirected(), "TTC",
                                          f"Alcance de {front.n} en {ttc:.0f} s (cierre {va * 3600:.0f} km/h)",
                                          {"ttc_s": round(ttc), "front": front.n}))
            elif (a.sig and a.sig == b.sig and a.directed() and b.directed()
                  and a.directed() != b.directed() and a.sig in c.st):
                s = c.st[a.sig]
                ea = math.hypot(a.x - s[0], a.y - s[1]) / max(a.kmh / 3600, 1e-6)
                eb = math.hypot(b.x - s[0], b.y - s[1]) / max(b.kmh / 3600, 1e-6)
                if a.moving and b.moving and abs(ea - eb) < c.cfg["converge_eta_s"] and max(ea, eb) < 600:
                    late = a if ea > eb else b
                    # Estaciones con varias vías: llegar casi a la vez es normal. Solo se restringe si la diferencia es muy pequeña.
                    close = abs(ea - eb) < c.cfg["converge_eta_s"] * 0.25
                    out.append(Hazard("B4", RESTRICT if close else CAUTION, (late.n,), late.undirected(), "CONVERGE",
                                      f"{a.n} y {b.n} llegan a {c.name(a.sig)} con {abs(ea - eb):.0f} s de diferencia",
                                      {"eta_a": round(ea), "eta_b": round(eb)}))
    return out


def b0_atp(c: Ctx):
    """Contraste con el ATP de a bordo (LZB/ETCS/ASFA). Barrera EXTERNA: la ejecuta el tren, no este sistema."""
    out = []
    for t in c.trains:
        a = c.atp.get(t.n)
        if not a:
            continue  # sin telemetría: se informa como cobertura, no como peligro
        seg = t.undirected()
        line = c.line_of(seg)
        age = (c.now_ms - a["ts"]) / 1000
        if age > c.cfg["atp_stale_s"]:
            out.append(Hazard("B0", CAUTION, (t.n,), seg, "ATP_STALE", f"Telemetría ATP caducada ({age:.0f} s)", {"system": a.get("system", "?")}))
            continue
        sys_, mode = a.get("system", "?"), a.get("mode", "?")
        if not a.get("protected", True):
            why = " en línea que exige ATP" if (line and line.get("atp_required")) else ""
            out.append(Hazard("B0", RESTRICT, (t.n,), seg, "ATP_ISOLATED",
                              f"ATP {sys_} en modo {mode}: marcha SIN protección automática{why}", {"system": sys_}))
        elif a.get("intervention"):
            out.append(Hazard("B0", CAUTION, (t.n,), seg, "ATP_BRAKING", f"ATP {sys_} ha intervenido (freno automático)"))
        sv = a.get("supervised_kmh")
        if a.get("protected", True) and sv and not a.get("intervention") and t.kmh > sv * 1.05 + 10:
            out.append(Hazard("B0", RESTRICT, (t.n,), seg, "ATP_DISCREPANCY",
                              f"{t.kmh:.0f} km/h con velocidad supervisada {sv:.0f} y el ATP no interviene (¿ATP degradado o dato erróneo?)", {"system": sys_}))
    return out


def bp_profile(c: Ctx):
    """Perfil aprendido de la flota: desvíos respecto a los trenes previos y patrones de exceso. SOLO asesora (CAUTION)."""
    out = []
    prof = c.profile
    if prof is None:
        return out
    k = c.cfg["km_per_px"]
    for t in c.trains:
        if not t.moving or t.kmh > c.cfg["speed_implausible_kmh"] or (c.now_ms - t.ts) / 1000 > c.cfg["stale_s"]:
            continue
        loc = fleet_profile.locate(c.est, k, t.ant, t.sig, t.x, t.y) if t.ant and t.sig else None
        if not loc:
            continue
        seg, b, _ = loc
        key = (seg, b, c.vmax(t))
        grp = prof.group(key, c.now_ms, skip=t.n)
        if len(grp) >= fleet_profile.MIN_TRAINS:
            m = fleet_profile.median(grp)
            dev = t.kmh > m * fleet_profile.DEV_FAST and t.kmh - m >= fleet_profile.DEV_MIN_ABS
            if c.persist(("PROFILE", t.n), dev) >= 2:
                out.append(Hazard("BP", CAUTION, (t.n,), t.undirected(), "FLEET_DEVIATION",
                                  f"{t.kmh:.0f} km/h aquí; los {len(grp)} trenes previos pasaron a ~{m:.0f} km/h (¿limitación temporal no conocida?)",
                                  {"kmh": round(t.kmh), "median": round(m), "n": len(grp)}))
            ref = c.vmax(t)
            if c.persist(("PROFILE_OVER", t.n), m > ref * fleet_profile.OVER_REF) >= 2:
                out.append(Hazard("BP", CAUTION, (t.n,), t.undirected(), "FLEET_OVER_REF",
                                  f"Patrón sistemático: la flota pasa aquí a ~{m:.0f} km/h, sobre el límite de referencia {ref:.0f}", {"median": round(m), "ref": round(ref)}))
        prof.learn(key, t.n, t.ts, t.kmh)
    return out


BARRIERS = {
    "B0": ("ATP de a bordo (LZB/ETCS/ASFA)", "Barrera externa del tren: se contrasta su estado y velocidad supervisada", b0_atp),
    "B1": ("Integridad de datos", "Caducidad, saltos imposibles, posiciones duplicadas", b1_integrity),
    "B2": ("Velocidad y frenado", "Envolvente por línea/producto y curva de frenado", b2_speed),
    "B3": ("Separación de bloques", "Distancia de frenado + margen, vía única", b3_block),
    "B4": ("Predicción de conflicto", "Tiempo hasta alcance (TTC) y convergencia", b4_predict),
    "BP": ("Perfil aprendido de la flota", "Desvío respecto a los trenes previos y limitaciones probables (solo asesora)", bp_profile),
}


# ───────────────────────── motor + B5 + B6 ─────────────────────────
class Engine:
    def __init__(self, est, cfg=None, enabled=None, log_path=None):
        self.cfg = {**DEFAULT_CFG, **(cfg or {})}
        self.est = est
        self.enabled = set(enabled or BARRIERS)
        self.log_path = log_path
        self.cycle = 0
        self.now_ms = 0
        self.prev = {}
        self.streak = {}
        self.profile = fleet_profile.Profile()
        self.trains: list[Train] = []
        self.hazards: list[Hazard] = []
        self.state: dict[str, dict] = {}     # B5: orden vigente por tren
        self.manual: dict[str, dict] = {}    # restricciones humanas
        self.acks: dict[str, dict] = {}
        self.faults: dict[str, str] = {}
        self.counts = defaultdict(int)
        self.degraded = None
        self.blind = 0
        self.fault_inject: set[str] = set()
        self.locked: set = set()
        self.atp: dict[str, dict] = {}
        self.lines: list[dict] = []
        self.seen_segs: set = set()
        self.prox: list[dict] = []
        self.prox_state: dict[str, dict] = {}
        self.pos_src: dict[str, str] = {}
        self.events = deque(maxlen=300)
        self._active_keys = set()
        self.last_fire: dict[str, int] = {}
        self.fault_since: dict[str, int] = {}
        self.pending_rearm: dict[str, dict] = {}
        self.rearm_hist: dict[str, list] = defaultdict(list)
        self.guard = {"refused": 0, "dual_pending": 0, "completed": 0, "rate_blocked": 0, "last": None}

    # ---- registro ----
    def log(self, kind, msg, **data):
        e = {"t": self.now_ms, "kind": kind, "msg": msg, **data}
        self.events.appendleft(e)
        if self.log_path:
            os.makedirs(os.path.dirname(self.log_path) or ".", exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")

    # ---- ciclo ----
    def step(self, raw, now_ms):
        self.cycle += 1
        self.now_ms = now_ms
        k = self.cfg["km_per_px"]
        if raw is None:
            self.blind += 1
        else:
            self.blind = 0
            self.trains = [parse_train(d, k) for d in raw]
        newest = max((t.ts for t in self.trains), default=0)
        feed_age = (now_ms - newest) / 1000 if newest else 1e9
        was = self.degraded
        self.degraded = None
        if raw is None or feed_age > self.cfg["feed_dead_s"]:
            self.degraded = "Feed de posiciones perdido: supervisor ciego"
        if self.degraded and not was:
            self.log("SYS", self.degraded)
        if was and not self.degraded:
            self.log("SYS", "Feed recuperado")

        ctx = Ctx(self.trains, self.est, self.cfg, now_ms, self.prev, self.streak)
        ctx.atp, ctx.line_of, ctx.profile = self.atp, self.line_of, self.profile
        for t in self.trains:
            if t.undirected():
                self.seen_segs.add(t.undirected())
        hz = []
        for bid in BARRIERS:
            if bid not in self.enabled:
                continue
            try:
                if bid in self.fault_inject:
                    raise RuntimeError("fallo inyectado")
                found = BARRIERS[bid][2](ctx)
                self.faults.pop(bid, None)
                self.fault_since.pop(bid, None)
                hz += found
            except Exception as ex:  # fail-closed
                if bid not in self.faults:
                    self.fault_since[bid] = now_ms
                self.faults[bid] = repr(ex)
                self.log("FAULT", f"Barrera {bid} en fallo: {ex!r}")
        for k in [k for k in self.streak if k not in ctx.seen]:
            del self.streak[k]
        if self.degraded or self.faults:
            for t in self.trains:
                hz.append(Hazard("SYS", CAUTION, (t.n,), t.undirected(), "DEGRADED",
                                 "Supervisor degradado: restricción preventiva", {}))
        for h in hz:
            self.counts[h.barrier] += 0
        keys = {h.key for h in hz}
        for h in hz:
            if h.key not in self._active_keys:
                self.counts[h.barrier] += 1
                self.last_fire[h.barrier] = now_ms
                self.log("HAZARD", f"[{h.barrier}] {SEV_NAME[h.sev]} {','.join(h.trains)}: {h.msg}",
                         barrier=h.barrier, sev=SEV_NAME[h.sev], trains=list(h.trains))
        for gone in self._active_keys - keys:
            self.log("CLEAR", f"Condición despejada: {gone}")
        self._active_keys = keys
        self.hazards = hz
        self._interlock(hz)
        self.prev = {t.n: (t.x, t.y, t.ts) for t in self.trains}

    # ---- B5: enclavamiento ----
    def _interlock(self, hz):
        demand = defaultdict(lambda: [0, []])
        for h in hz:
            for tn in h.trains:
                d = demand[tn]
                d[0] = max(d[0], h.sev)
                d[1].append(f"{h.barrier}:{h.code}")
        for tn, m in self.manual.items():
            demand[tn][0] = max(demand[tn][0], m["sev"])
            demand[tn][1].append("MANUAL")
        by_n = {t.n: t for t in self.trains}
        # ratchet / latch
        for tn, (sev, why) in demand.items():
            if sev == NONE:
                continue
            st = self.state.get(tn)
            if not st:
                seg = by_n[tn].undirected() if tn in by_n else None
                st = self.state[tn] = {"sev": 0, "since": self.now_ms, "clear": 0, "seg": seg, "why": set(), "barriers": set()}
                self.log("ACTUATE", f"B5 ordena {SEV_NAME[sev]} a {tn}", train=tn, sev=SEV_NAME[sev])
            elif sev > st["sev"]:
                self.log("ACTUATE", f"B5 escala a {SEV_NAME[sev]} el tren {tn}", train=tn, sev=SEV_NAME[sev])
            st["sev"] = max(st["sev"], sev)
            st["clear"] = 0
            st["why"] |= set(why)
            st["barriers"] |= {w.split(":")[0] for w in why if ":" in w}
            if by_n.get(tn) and by_n[tn].undirected():
                st["seg"] = by_n[tn].undirected()
        # liberación: solo con N ciclos limpios (STOP además exige humano)
        for tn in list(self.state):
            if demand[tn][0] == NONE if tn in demand else True:
                st = self.state[tn]
                st["clear"] += 1
                if st["sev"] < STOP and st["clear"] >= self.cfg["rearm_clear_cycles"]:
                    self.log("RELEASE", f"Restricción liberada automáticamente: {tn}", train=tn)
                    del self.state[tn]
        # bloques enclavados: avisa a los demás trenes del bloque
        locked = {st["seg"] for st in self.state.values() if st["sev"] == STOP and st["seg"]}
        for t in self.trains:
            u = t.undirected()
            if u in locked and t.n not in self.state:
                self.state[t.n] = {"sev": CAUTION, "since": self.now_ms, "clear": 0, "seg": u,
                                   "why": {"B5:BLOCK_LOCKED"}, "barriers": {"B5"}}
        for st in self.state.values():
            if st["why"] == {"B5:BLOCK_LOCKED"} and st["seg"] not in locked:
                st["clear"] = self.cfg["rearm_clear_cycles"]
        for tn in [n for n, s in self.state.items() if s["why"] == {"B5:BLOCK_LOCKED"} and s["clear"] >= self.cfg["rearm_clear_cycles"]]:
            del self.state[tn]
        self.locked = locked

    # ---- líneas, ATP y proximidad ----
    def _ref_of(self, key):
        return key[2]

    def set_lines(self, corridors):
        self.lines = corridors
        for c in self.lines:
            c["_m"] = set(c["stations"])

    def line_of(self, seg):
        if seg:
            for c in self.lines:
                if seg[0] in c["_m"] and seg[1] in c["_m"]:
                    return c
        return None

    def set_atp(self, tn, rec, ts=None):
        self.atp[tn] = {**rec, "ts": ts if ts is not None else self.now_ms}

    def proximity_update(self, tablets, now_ms):
        """Regla de proximidad. Usa la posición de la TABLET (GPS de cabina) si es reciente; si no, la del feed.
        Activa a <proximity_km; se libera a >1,1*proximity_km o 'hold' s después de dejar de cumplirse."""
        self.now_ms = max(self.now_ms, now_ms)
        fresh = self.cfg["tablet_fresh_s"] * 1000
        pos = {}
        for t in self.trains:
            tb = tablets.get(t.n)
            pos[t.n] = (tb["x"], tb["y"], "tablet") if tb and now_ms - tb["ts"] <= fresh else (t.x, t.y, "feed")
        self.pos_src = {n: p[2] for n, p in pos.items()}
        single = {tuple(sorted(p)) for p in self.cfg["single_track"]}
        R, hold = self.cfg["proximity_km"], self.cfg["proximity_hold_s"] * 1000
        found = {"|".join(sorted((p["a"], p["b"]))): p for p in proximity.evaluate(self.trains, pos, self.cfg, single)}
        out = []
        for key, p in found.items():
            st = self.prox_state.get(key)
            cond = p["level"] == "RED"
            if st is None and cond and p["dist_km"] < R:
                st = self.prox_state[key] = {"since": now_ms, "last_red": now_ms}
                self.log("PROX", f"ROJO {p['a']}↔{p['b']} a {p['dist_km']:.2f} km ({p['reason']})", pair=key)
            elif st is not None:
                if cond:
                    st["last_red"] = now_ms
                elif now_ms - st["last_red"] > hold:
                    self.prox_state.pop(key)
                    st = None
                    self.log("PROX", f"Despejado {p['a']}↔{p['b']}", pair=key)
            out.append({**p, "key": key, "level": "RED" if st else "AMBER", "since": st["since"] if st else None,
                        "critical": bool(st) and p["dist_km"] < R / 2})
        for key in [k for k in self.prox_state if k not in found]:
            if now_ms - self.prox_state[key]["last_red"] > hold:
                self.prox_state.pop(key)
                self.log("PROX", f"Despejado {key}", pair=key)
            else:  # fuera de banda pero dentro del 'hold': se mantiene
                pass
        self.prox = out

    # ---- B6: interfaz con el humano ----
    def proof_clear(self, tn):
        st = self.state.get(tn)
        return bool(st) and st["clear"] >= self.cfg["rearm_clear_cycles"]

    def _refuse(self, msg, who, tn, kind="refused"):
        self.guard[kind] += 1
        self.guard["last"] = {"t": self.now_ms, "who": who, "train": tn, "msg": msg}
        self.log("GUARD", f"B7 rechaza orden de {who} sobre {tn}: {msg}", train=tn, who=who)
        return False, "Rechazado por B7: " + msg

    def rearm(self, tn, who, principal=None):
        """B7 · guardia de órdenes humanas. Una persona puede AÑADIR restricciones siempre; para LIBERAR
        un STOP el sistema exige: prueba de vía libre de las barreras, supervisor sano, sin conflicto real
        de proximidad, límite de frecuencia y (por defecto) dos autorizaciones de principales distintos."""
        principal = principal or who
        st = self.state.get(tn)
        if not st:
            return False, "El tren no tiene restricción activa"
        if st["sev"] < STOP:
            return False, "Solo los STOP enclavados requieren rearme humano; el resto se libera solo"
        if self.degraded or self.faults:
            return self._refuse("el supervisor está degradado: no se puede demostrar vía libre", who, tn)
        if not self.proof_clear(tn):
            return self._refuse(f"las barreras aún no demuestran vía libre "
                                f"({st['clear']}/{self.cfg['rearm_clear_cycles']} ciclos limpios)", who, tn)
        if any(p.get("level") == "RED" and tn in (p.get("a"), p.get("b")) for p in self.prox):
            return self._refuse("hay un conflicto de proximidad real en curso con otro tren", who, tn)
        recent = [t for t in self.rearm_hist[principal] if self.now_ms - t < 300_000]
        self.rearm_hist[principal] = recent
        if len(recent) >= self.cfg["rearm_max_5min"]:
            return self._refuse(f"{principal} ya completó {len(recent)} rearmes en 5 min (límite anti-error)", who, tn, "rate_blocked")
        if self.cfg["rearm_dual"]:
            p = self.pending_rearm.get(tn)
            if p and self.now_ms - p["t"] > self.cfg["rearm_pending_s"] * 1000:
                p = None
            if not p or p["principal"] == principal:
                self.pending_rearm[tn] = {"principal": principal, "who": who, "t": self.now_ms}
                self.guard["dual_pending"] += 1
                self.log("GUARD", f"B7: primera autorización de {who} para reanudar {tn}; falta la de otro "
                                  f"centro/operador distinto", train=tn, who=who)
                return False, ("Primera autorización registrada. Falta la segunda autorización de OTRO centro u "
                               f"operador (caduca en {self.cfg['rearm_pending_s']} s)")
            first = p
            del self.pending_rearm[tn]
            self.log("REARM", f"{first['who']} y {who} autorizan reanudar {tn} tras prueba de vía libre (doble autorización)",
                     train=tn, who=who)
        else:
            self.log("REARM", f"{who} autoriza reanudar {tn} tras prueba de vía libre", train=tn, who=who)
        self.rearm_hist[principal].append(self.now_ms)
        self.guard["completed"] += 1
        del self.state[tn]
        return True, "Rearme aceptado"

    def manual_restrict(self, tn, who, sev=RESTRICT):
        self.manual[tn] = {"sev": sev, "who": who, "t": self.now_ms}
        self.log("MANUAL", f"{who} impone restricción manual a {tn}", train=tn, who=who)
        return True, "Restricción aplicada (las acciones restrictivas nunca se rechazan)"

    def release_manual(self, tn, who):
        if tn in self.manual:
            del self.manual[tn]
            self.log("MANUAL", f"{who} retira su restricción manual de {tn}", train=tn, who=who)
            return True, "Restricción manual retirada; las barreras automáticas siguen vigentes"
        return False, "No hay restricción manual"

    def forget(self, tn):
        """Elimina todo rastro de un tren que ya no existe en el feed."""
        self.state.pop(tn, None)
        self.manual.pop(tn, None)
        self.prev.pop(tn, None)
        self.atp.pop(tn, None)

    def ack(self, key, who):
        self.acks[key] = {"who": who, "t": self.now_ms}
        self.log("ACK", f"{who} reconoce {key}", key=key, who=who)
        return True, "Reconocido"

    def _pending_view(self, tn):
        p = self.pending_rearm.get(tn)
        if not p:
            return None
        left = self.cfg["rearm_pending_s"] - (self.now_ms - p["t"]) / 1000
        return {"by": p["who"], "principal": p["principal"], "left_s": max(0, round(left))} if left > 0 else None

    def operator_queue(self):
        q = []
        n = self.cfg["rearm_clear_cycles"]
        for tn, st in self.state.items():
            if st["sev"] == STOP:
                key = f"stop:{tn}"
                q.append({"key": key, "level": "CRITICA", "train": tn,
                          "title": f"Tren {tn} detenido y bloque enclavado",
                          "auto": ["Freno de emergencia ordenado", "Bloque enclavado", "Trenes cercanos restringidos"],
                          "barriers": sorted(st["barriers"]),
                          "action": "Rearmar" if self.proof_clear(tn) else f"Esperando prueba de vía libre ({st['clear']}/{n})",
                          "can_rearm": self.proof_clear(tn), "ack": key in self.acks,
                          "rearm_pending": self._pending_view(tn)})
            elif self.now_ms - st["since"] > self.cfg["escalate_after_s"] * 1000:
                key = f"persist:{tn}"
                q.append({"key": key, "level": "AVISO", "train": tn,
                          "title": f"Restricción persistente sobre {tn}",
                          "auto": [f"Restricción {SEV_NAME[st['sev']]} activa"],
                          "barriers": sorted(st["barriers"]), "action": "Revisar causa",
                          "can_rearm": False, "ack": key in self.acks})
        for h in self.hazards:
            if h.barrier == "B0" and h.code in ("ATP_ISOLATED", "ATP_DISCREPANCY"):
                key = f"atp:{h.trains[0]}:{h.code}"
                q.append({"key": key, "level": "CRITICA", "train": h.trains[0], "title": h.msg,
                          "auto": ["Restricción de velocidad ordenada por B5", "Contraste con las barreras B1–B4"],
                          "barriers": ["B0"], "action": "Contactar con la cabina (GSM-R) y con el CTC",
                          "can_rearm": False, "ack": key in self.acks})
        if self.degraded:
            q.append({"key": "sys:blind", "level": "CRITICA", "train": None, "title": self.degraded,
                      "auto": ["Restricción preventiva a toda la red"], "barriers": ["B1"],
                      "action": "Activar procedimiento de degradado", "can_rearm": False, "ack": "sys:blind" in self.acks})
        for bid, err in self.faults.items():
            q.append({"key": f"fault:{bid}", "level": "CRITICA", "train": None,
                      "title": f"Barrera {bid} en fallo", "auto": ["Fallo hacia lado restrictivo"],
                      "barriers": [bid], "action": err[:120], "can_rearm": False, "ack": f"fault:{bid}" in self.acks})
        return q

    # ---- salida ----
    def snapshot(self):
        cmd = {tn: SEV_NAME[s["sev"]] for tn, s in self.state.items()}
        for tn, m in self.manual.items():
            cmd[tn] = SEV_NAME[max(m["sev"], STOP if cmd.get(tn) == "STOP" else m["sev"])]
        active = defaultdict(int)
        for h in self.hazards:
            active[h.barrier] += 1
        barriers = []
        for bid, (nm, desc, _) in BARRIERS.items():
            status = ("OFF" if bid not in self.enabled else "FAULT" if bid in self.faults else "ALERT" if active[bid]
                      else "NODATA" if bid == "B0" and not self.atp else "OK")
            barriers.append({"id": bid, "name": nm, "desc": desc, "status": status,
                             "active": active[bid], "total": self.counts[bid]})
        n_lock = len(getattr(self, "locked", ()))
        barriers.append({"id": "B5", "name": "Enclavamiento", "desc": "Ejecuta, bloquea y exige prueba para liberar",
                         "status": "ALERT" if self.state else "OK", "active": len(self.state), "total": n_lock})
        names = {c: s["n"] for c, s in self.est.items()}
        trains = []
        for t in self.trains:
            hd = t.heading() if t.moving else None
            trains.append({"n": t.n, "x": t.x / self.cfg["km_per_px"], "y": t.y / self.cfg["km_per_px"],
                           "kmh": round(t.kmh), "vmax": self.cfg["max_speed_by_product"].get(t.product, self.cfg["default_max_speed"]) if t.product else self.cfg["unknown_product_max_speed"], "ret": t.ret, "cmd": cmd.get(t.n, "NONE"),
                           "from": names.get(t.ant, t.ant), "to": names.get(t.sig, t.sig), "dest": names.get(t.des, t.des),
                           "hx": round(hd[0], 3) if hd else None, "hy": round(hd[1], 3) if hd else None,
                           "op": t.op, "src": self.pos_src.get(t.n, "feed"),
                           "by": sorted((self.state.get(t.n) or {}).get("barriers", ())) + (["MANUAL"] if t.n in self.manual else []),
                           "line": (self.line_of(t.undirected()) or {}).get("name"),
                           "signalling": (self.line_of(t.undirected()) or {}).get("signalling"),
                           "atp": (f"{self.atp[t.n].get('system', '?')} {self.atp[t.n].get('mode', '?')}"
                                   + ("" if self.atp[t.n].get("protected", True) else " · SIN PROTECCIÓN")) if t.n in self.atp else None})
        cnt = defaultdict(int)
        for t in trains:
            cnt[t["cmd"]] += 1
        return {
            "now": self.now_ms, "cycle": self.cycle, "degraded": self.degraded,
            "barriers": barriers, "trains": trains,
            "stations": [{"c": c, "n": s["n"], "x": s["x"], "y": s["y"]} for c, s in self.est.items()],
            "unit_km": self.cfg["km_per_px"],
            "corridors": [{k: v for k, v in c.items() if k != "_m"} for c in self.lines],
            "segments": [list(s) for s in self.seen_segs],
            "hazards": [{"barrier": h.barrier, "sev": SEV_NAME[h.sev], "trains": list(h.trains),
                         "seg": ctx_name(self.est, h.seg), "msg": h.msg, "code": h.code} for h in sorted(self.hazards, key=lambda h: -h.sev)],
            "locked": [ctx_name(self.est, s) for s in getattr(self, "locked", ())],
            "locked_pairs": [list(s) for s in getattr(self, "locked", ())],
            "learned_limits": self.profile.probable_limits(self.now_ms, self._ref_of)[:40],
            "operator": self.operator_queue(),
            "events": list(self.events)[:60],
            "guard": {**self.guard, "pending": len(self.pending_rearm)},
            "kpi": {"trains": len(trains), "clear": cnt["NONE"], "caution": cnt["CAUTION"],
                    "restrict": cnt["RESTRICT"], "stop": cnt["STOP"]},
        }


def ctx_name(est, seg):
    if not seg:
        return None
    return f"{est.get(seg[0], {}).get('n', seg[0])} ↔ {est.get(seg[1], {}).get('n', seg[1])}"
