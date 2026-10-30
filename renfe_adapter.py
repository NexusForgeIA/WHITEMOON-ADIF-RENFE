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


def load_gtfs(src: str):
    """src: ruta a un .zip o URL. Devuelve {'stops':{id:(name,lat,lon)}, 'trips':{trip_id:{...}}, 'by_number':{...}}."""
    if src.startswith("http"):
        raw = urllib.request.urlopen(src, timeout=90).read()
        zf = zipfile.ZipFile(io.BytesIO(raw))
    else:
        zf = zipfile.ZipFile(src)
    stops = {r["stop_id"]: (r.get("stop_name", r["stop_id"]), float(r["stop_lat"]), float(r["stop_lon"]))
             for r in _csv(zf, "stops.txt") if r.get("stop_lat")}
    routes = {r["route_id"]: product_of(r.get("route_short_name"), r.get("route_long_name"))
              for r in _csv(zf, "routes.txt")}
    trip_route = {r["trip_id"]: r["route_id"] for r in _csv(zf, "trips.txt")}
    seq = {}
    for r in _csv(zf, "stop_times.txt"):
        seq.setdefault(r["trip_id"], []).append((int(r["stop_sequence"]), r["stop_id"]))
    trips = {}
    for tid, lst in seq.items():
        lst.sort()
        trips[tid] = {"stops": [s for _, s in lst], "product": routes.get(trip_route.get(tid), 0)}
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

    # ---- ciclo ----
    def fetch(self):
        vp = self.open(URL_VP)
        try:
            delays = self._delays(self.open(URL_TU))
        except Exception:
            delays = {}
        hdr = int(_g(_g(vp, "header", default={}), "timestamp", default=0) or 0)
        ts_ms = hdr * 1000 if hdr else int(self.now() * 1000)
        trains, seen, matched = [], set(), 0
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
            st = self.state.setdefault(vid, {"x": x, "y": y, "ts": ts_ms, "kmh": None, "ux": 0.0, "uy": 0.0,
                                              "last_move": ts_ms, "sig": sig, "ant": None})
            dt = (ts_ms - st["ts"]) / 1000
            d = math.hypot(x - st["x"], y - st["y"])
            out_ts = ts_ms
            if dt > 0:
                prev = st["kmh"]
                if d < 0.005 and prev is not None and prev > 60:   # congelado a velocidad
                    kmh, out_ts = prev, st["last_move"]
                else:
                    inst = d / dt * 3600
                    kmh = prev if inst > 450 and prev is not None else (inst if prev is None else 0.6 * inst + 0.4 * prev)
                    if d >= 0.005:
                        st["last_move"] = ts_ms
                        st["ux"], st["uy"] = (x - st["x"]) / d, (y - st["y"]) / d
                if st["sig"] != sig:
                    st["ant"] = st["sig"]
                st.update(x=x, y=y, ts=ts_ms, kmh=kmh, sig=sig)
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
            k = kmh / 3600
            trains.append({"n": label, "p": prod, "x": x, "y": y, "kmh": round(kmh, 1),
                           "vx": st["ux"] * k if kmh > 1 else 0.0, "vy": st["uy"] * k if kmh > 1 else 0.0,
                           "ts": out_ts, "ret": round(delays.get(trip_id, 0) / 60), "ant": ant, "sig": sig,
                           "ori": ori, "des": des, "mat": f"v{vid}", "op": "renfe-viajeros"})
        for gone in set(self.state) - seen:
            del self.state[gone]
        self.stats = {"entities": len(trains), "header_age_s": round(self.now() - ts_ms / 1000),
                      "gtfs_matched": matched, "gtfs_loaded": bool(self.gtfs)}
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
