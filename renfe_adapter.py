"""Adaptador del feed OFICIAL de Renfe (GTFS-RT en JSON, licencia CC BY 4.0, data.renfe.com)
al esquema que consume el motor.

Fuentes
  posiciones : https://gtfsrt.renfe.com/vehicle_positions_LD.json   (cada ~15 s)
  retrasos   : https://gtfsrt.renfe.com/trip_updates_LD.json        (cada ~20-30 s)
  estático   : https://ssl.renfe.com/gtransit/Fichero_AV_LD/google_transit.zip  (GTFS)

El feed de posiciones NO trae velocidad, rumbo ni marca de tiempo por vehículo (solo lat/lon,
stopId, currentStatus y la cabecera). Aquí se derivan de posiciones sucesivas:
  * velocidad  = distancia/Δt entre sondeos, suavizada (EMA)
  * rumbo      = dirección del desplazamiento
  * congelado  = posición idéntica mientras iba a >60 km/h (un frenazo real deja desplazamiento
                 decreciente, no cero): se conserva la marca de tiempo antigua para que B1 lo vea caducar.
Coordenadas de salida en KM (proyección equirectangular, error < 3 % en la península);
usar Engine(cfg={"km_per_px": 1.0}).
"""
from __future__ import annotations

import csv
import io
import json
import math
import re
import time
import urllib.request
import zipfile
import punctuality
from datetime import datetime
from zoneinfo import ZoneInfo

URL_VP = "https://gtfsrt.renfe.com/vehicle_positions_LD.json"
URL_TU = "https://gtfsrt.renfe.com/trip_updates_LD.json"
GTFS_ZIP = "https://ssl.renfe.com/gtransit/Fichero_AV_LD/google_transit.zip"

LAT_N, LAT_REF, LON_W = 44.0, 40.0, -10.0
KM_LAT = 111.19
KM_LON = 111.32 * math.cos(math.radians(LAT_REF))

# nombre de producto -> clase de velocidad del motor (supuesto a calibrar)
PRODUCT_CLASS = [("AVLO", 2), ("AVE", 2), ("IRYO", 2), ("OUIGO", 2), ("AVANT", 10), ("ALVIA", 11),
                 ("EUROMED", 11), ("INTERCITY", 11), ("ALTARIA", 11), ("TRENHOTEL", 11), ("TALGO", 11),
                 ("REGIONAL", 16), ("MD", 16), ("R.EXPRES", 16), ("REGIONAL EXPRES", 16)]


def project(lat: float, lon: float):
    return (lon - LON_W) * KM_LON, (LAT_N - lat) * KM_LAT


def _g(d, *names, default=None):
    if isinstance(d, dict):
        for n in names:
            if n in d:
                return d[n]
    return default


def product_of(*texts) -> int:
    toks = set(re.findall(r"[A-Z0-9\.]+", " ".join(t or "" for t in texts).upper()))
    for key, cls in PRODUCT_CLASS:
        if key in toks:
            return cls
    return 0


def _csv(zf, name):
    with zf.open(name) as f:  # se materializa dentro del 'with': el fichero se cierra al salir
        return list(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig")))


def _hms(t):
    """'HH:MM:SS' (GTFS admite >24 h) -> segundos desde medianoche, o None."""
    try:
        h, m, sec = (int(p) for p in str(t).strip().split(":"))
        return h * 3600 + m * 60 + sec
    except Exception:
        return None


STALE_MIN = 20   # un retraso cuya llegada estimada lleva > 20 min en el pasado ya no describe un viaje en curso


def eta_epoch(info, delay_s, now):
    """Llegada estimada al destino (epoch s) = hora programada + retraso del feed; None si el GTFS no trae horas.
    Los horarios GTFS son segundos desde las 00:00 del día de servicio (pueden pasar de 86400)."""
    times = (info or {}).get("times") or []
    if not times:
        return None
    arr = times[-1][0] if times[-1][0] is not None else times[-1][1]
    if arr is None:
        return None
    mid = datetime.fromtimestamp(now, ZoneInfo("Europe/Madrid")).replace(hour=0, minute=0, second=0, microsecond=0)
    sod = now - mid.timestamp()
    base = mid.timestamp() - (86400 if arr >= 86400 and sod < 6 * 3600 else 0)   # viaje que cruza la medianoche
    return base + arr + (delay_s or 0)


def finished(info, sig, status, delay_s, now):
    """True si el viaje ya terminó: parado en su última parada, o llegada estimada vencida hace más de STALE_MIN."""
    stops = (info or {}).get("stops") or []
    if stops and sig == stops[-1] and status == "STOPPED_AT":
        return True
    e = eta_epoch(info, delay_s, now)
    return e is not None and now - e > STALE_MIN * 60


def hhmm(sec):
    return None if sec is None else f"{int(sec // 3600) % 24:02d}:{int(sec % 3600 // 60):02d}"


def load_gtfs(src: str):
    """src: ruta a un .zip o URL. Devuelve {'stops':{id:(name,lat,lon)}, 'trips':{trip_id:{...}}, 'by_number':{...}}."""
    if src.startswith("http"):
        raw = urllib.request.urlopen(src, timeout=90).read()
        zf = zipfile.ZipFile(io.BytesIO(raw))
    else:
        zf = zipfile.ZipFile(src)
    stops = {r["stop_id"]: (r.get("stop_name", r["stop_id"]), float(r["stop_lat"]), float(r["stop_lon"]))
             for r in _csv(zf, "stops.txt") if r.get("stop_lat")}
    rows_r = _csv(zf, "routes.txt")
    routes = {r["route_id"]: product_of(r.get("route_short_name"), r.get("route_long_name")) for r in rows_r}
    rname = {r["route_id"]: (r.get("route_short_name") or "").strip() for r in rows_r}
    trip_route = {r["trip_id"]: r["route_id"] for r in _csv(zf, "trips.txt")}
    seq = {}
    for r in _csv(zf, "stop_times.txt"):
        seq.setdefault(r["trip_id"], []).append((int(r["stop_sequence"]), r["stop_id"],
                                                 _hms(r.get("arrival_time")), _hms(r.get("departure_time"))))
    trips = {}
    for tid, lst in seq.items():
        lst.sort()
        trips[tid] = {"stops": [x[1] for x in lst], "product": routes.get(trip_route.get(tid), 0),
                      "times": [(x[2], x[3]) for x in lst], "rname": rname.get(trip_route.get(tid), "")}
    by_number = {}
    for tid, info in trips.items():
        by_number.setdefault(tid[:5], info)
    return {"stops": stops, "trips": trips, "by_number": by_number}


def _http_json(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.load(r)


class RenfeFeed:
    def __init__(self, gtfs=None, opener=None, now=time.time):
        self.gtfs = gtfs
        self.open = opener or _http_json
        self.now = now
        self.state = {}
        self.stats = {}
        self.detail = {}
        self.skew_ms = None
        self.skew_note = None
        self.est = {}
        if gtfs:
            for sid, (n, lat, lon) in gtfs["stops"].items():
                x, y = project(lat, lon)
                self.est[sid] = {"n": n, "x": x, "y": y}

    # ---- helpers ----
    def _trip(self, trip_id):
        if not self.gtfs or not trip_id:
            return None
        g = self.gtfs
        return g["trips"].get(trip_id) or g["trips"].get(trip_id[:-10]) or g["by_number"].get(trip_id[:5])

    @staticmethod
    def _delays(tu):
        out = {}
        for e in (tu or {}).get("entity", []):
            t = _g(e, "tripUpdate", "trip_update")
            if not t:
                continue
            tid = _g(_g(t, "trip"), "tripId", "trip_id")
            d = _g(t, "delay")
            if d is None:
                stu = _g(t, "stopTimeUpdate", "stop_time_update", default=[])
                if stu:
                    d = _g(_g(stu[0], "arrival", default={}), "delay")
            if tid is not None and d is not None:
                out[tid] = int(d)
        return out

    def _nm(self, sid):
        return str((self.est.get(sid) or {}).get("n") or sid or "?")

    def _detail(self, label, info, sig, ant, status, delay_s):
        """Ficha del tren: horarios del GTFS + retraso del feed. Solo lo que se sabe; el resto queda a None."""
        d = {"n": label, "delay_s": delay_s, "status": status}
        if not info:
            return d
        stops, times = info["stops"], info.get("times") or []
        delay = delay_s or 0
        d.update(product=info.get("rname") or None, ori=self._nm(stops[0]), des=self._nm(stops[-1]))
        if times:
            arr = times[-1][0] if times[-1][0] is not None else times[-1][1]
            d["dest_sched"], d["dest_est"] = hhmm(arr), hhmm(None if arr is None else arr + delay)
            i = stops.index(sig) if sig in stops else -1
            if i >= 0:
                t = times[i][0] if times[i][0] is not None else times[i][1]
                d["next"] = {"name": self._nm(sig), "sched": hhmm(t), "est": hhmm(None if t is None else t + delay)}
        d["where"] = ("En " + self._nm(sig)) if status == "STOPPED_AT" else \
            (f"Entre {self._nm(ant)} y {self._nm(sig)}" if ant and sig and ant != sig else (f"Hacia {self._nm(sig)}" if sig else None))
        return d

    # ---- ciclo ----
    def fetch(self):
        vp = self.open(URL_VP)
        try:
            delays = self._delays(self.open(URL_TU))
        except Exception:
            delays = {}
        hdr = int(_g(_g(vp, "header", default={}), "timestamp", default=0) or 0)
        ts_ms = hdr * 1000 if hdr else int(self.now() * 1000)
        if hdr and self.skew_ms is None:
            # Calibración única del desfase del reloj del feed (Renfe publica a veces marcas con ±1 h de error).
            # Se redondea a múltiplos de 30 min y se fija: un feed realmente parado sigue detectándose como caducado.
            off = (self.now() * 1000 - ts_ms) / 1000
            self.skew_ms = int(round(off / 1800.0) * 1800 * 1000) if abs(off) > 300 else 0
            self.skew_note = f"desfase de reloj del feed corregido: {self.skew_ms // 1000} s" if self.skew_ms else None
        ts_ms += self.skew_ms or 0
        trains, seen, matched, stale, unknown = [], set(), 0, 0, 0
        for e in vp.get("entity", []):
            v = _g(e, "vehicle")
            pos = _g(v, "position")
            if not v or not pos:
                continue
            vid = str(_g(_g(v, "vehicle", default={}), "id", default=_g(e, "id")))
            label = str(_g(_g(v, "vehicle", default={}), "label", default=vid))
            trip_id = _g(_g(v, "trip", default={}), "tripId", "trip_id")
            sig = _g(v, "stopId", "stop_id")
            status = _g(v, "currentStatus", "current_status", default="IN_TRANSIT_TO")
            x, y = project(float(_g(pos, "latitude")), float(_g(pos, "longitude")))
            seen.add(vid)
            vts = _g(v, "timestamp")
            v_ms = (int(vts) * 1000 + (self.skew_ms or 0)) if vts else ts_ms   # marca propia del vehículo si existe
            st = self.state.setdefault(vid, {"x": x, "y": y, "ts": v_ms, "kmh": None, "ux": 0.0, "uy": 0.0,
                                              "last_move": ts_ms, "sig": sig, "ant": None})
            dt = (v_ms - st["ts"]) / 1000
            d = math.hypot(x - st["x"], y - st["y"])
            out_ts = ts_ms   # la caducidad se mide con la cabecera (corregida), no con la marca del vehículo
            if dt > 0:
                prev = st["kmh"]
                if d < 0.005 and prev is not None and prev > 60:   # congelado a velocidad
                    kmh, out_ts = prev, st["last_move"]
                else:
                    inst = d / dt * 3600
                    kmh = (prev if prev is not None else 0.0) if inst > 450 else (inst if prev is None else 0.6 * inst + 0.4 * prev)
                    if d >= 0.005:
                        st["last_move"] = v_ms
                        st["ux"], st["uy"] = (x - st["x"]) / d, (y - st["y"]) / d
                if st["sig"] != sig:
                    st["ant"] = st["sig"]
                st.update(x=x, y=y, ts=v_ms, kmh=kmh, sig=sig)
            else:
                kmh = st["kmh"] or 0.0  # cabecera sin avanzar: la caducidad la detecta B1 con la hora de la cabecera
            if status == "STOPPED_AT":
                kmh = 0.0
            info = self._trip(trip_id)
            if info:
                matched += 1
                stops = info["stops"]
                i = stops.index(sig) if sig in stops else -1
                ant = stops[i - 1] if i > 0 else (sig if i == 0 else st["ant"])
                ori, des, prod = stops[0], stops[-1], info["product"]
            else:
                ant, ori, des, prod = st["ant"] or sig, None, None, 0
            if status == "STOPPED_AT":
                ant = sig
            if self.gtfs and not info:
                unknown += 1    # tren sin viaje en el horario oficial: no se puede verificar, no se dibuja
                continue
            dly = delays.get(trip_id, 0)
            e_ = eta_epoch(info, dly, self.now()) if info else None
            rolling = kmh > 5 and e_ is not None and self.now() - e_ <= 3 * 3600   # circulando de verdad: un retraso del feed anticuado no lo oculta
            if info and finished(info, sig, status, dly, self.now()) and not (rolling and not (sig == (info["stops"] or [None])[-1] and status == "STOPPED_AT")):
                stale += 1      # viaje ya terminado (o llegada estimada vencida): el feed lo sigue publicando, pero no está en circulación
                continue        # no se dibuja, no genera peligros ni cuenta en los KPIs
            try:   # la ficha es informativa: un fallo aquí NUNCA debe tumbar la lectura de posiciones
                self.detail[label] = self._detail(label, info, sig, ant, status, delays.get(trip_id))
            except Exception:
                self.detail[label] = {"n": label}
            cat = punctuality.category(info.get("rname")) if info else "OTRO"
            eta = eta_epoch(info, dly, self.now()) if info else None
            k = kmh / 3600
            trains.append({"n": label, "p": prod, "x": x, "y": y, "kmh": round(kmh, 1),
                           "vx": st["ux"] * k if kmh > 1 else 0.0, "vy": st["uy"] * k if kmh > 1 else 0.0,
                           "ts": out_ts, "ret": round(dly / 60), "eta": round(eta) if eta else 0, "cat": cat, "ant": ant, "sig": sig,
                           "ori": ori, "des": des, "mat": f"v{vid}", "op": "renfe-viajeros"})
        for gone in set(self.state) - seen:
            del self.state[gone]
        for gone in set(self.detail) - {t["n"] for t in trains}:
            del self.detail[gone]
        self.stats = {"entities": len(trains), "header_age_s": round(self.now() - ts_ms / 1000),
                      "gtfs_matched": matched, "retrasos_caducados": stale, "sin_horario": unknown, "gtfs_loaded": bool(self.gtfs), "skew_s": (self.skew_ms or 0) // 1000}
        return self.est, trains


def _probe():
    import argparse
    ap = argparse.ArgumentParser(description="Sonda del feed oficial de Renfe")
    ap.add_argument("--gtfs", help="ruta o URL del google_transit.zip")
    a = ap.parse_args()
    gtfs = load_gtfs(a.gtfs) if a.gtfs else None
    feed = RenfeFeed(gtfs)
    feed.fetch()
    time.sleep(16)
    est, trains = feed.fetch()
    print("estadísticas:", feed.stats)
    print("estaciones con coordenadas:", len(est))
    mv = [t for t in trains if t["kmh"] > 10]
    print(f"trenes: {len(trains)} · en movimiento: {len(mv)} · vel. máx. derivada: {max((t['kmh'] for t in trains), default=0):.0f} km/h")
    for t in trains[:3]:
        print(t)


if __name__ == "__main__":
    _probe()
