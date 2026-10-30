"""Capa de infraestructura: vías, nº de vías, desvíos, señales y cambios de sección.

FUENTE: OpenStreetMap (ODbL), descargada con Overpass al arrancar y guardada en caché.
NO es un dato oficial de Adif: la cobertura de señales/desvíos y del tag `tracks` es parcial y puede
estar desfasada. Lo que OSM no tiene (cantones, balizas, bucles LZB) NO se inventa: se cargará desde
data/infra_extra.json cuando Adif (u otra fuente oficial) lo ceda. Formato de ese fichero al final.

Coordenadas de salida en km con la misma proyección que el adaptador de Renfe.
"""
import json
import math
import os
import threading
import time
import urllib.parse
import urllib.request

from renfe_adapter import project

ENDPOINTS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
             "https://overpass.private.coffee/api/interpreter"]
# Península + Baleares (aprox.), en teselas de 2°×2° para no agotar el tiempo de Overpass
LAT0, LAT1, LON0, LON1, STEP = 36.0, 44.0, -9.5, 3.5, 2.0
TOL_KM = 0.05          # simplificación de geometría (50 m)
POINT_KINDS = {"signal": "signal", "switch": "switch", "buffer_stop": "buffer", "railway_crossing": "crossing",
               "crossing": "crossing", "derail": "derail"}


def tiles():
    la = LAT0
    while la < LAT1:
        lo = LON0
        while lo < LON1:
            yield (la, lo, min(la + STEP, LAT1), min(lo + STEP, LON1))
            lo += STEP
        la += STEP


def query(b):
    s, w, n, e = b
    bb = f"({s},{w},{n},{e})"
    return (f'[out:json][timeout:50];'
            f'(way["railway"="rail"]["usage"~"^(main|branch)$"][!"service"]{bb};'
            f'way["railway"="rail"]["highspeed"="yes"]{bb};)->.r;'
            f'.r out tags geom qt;'
            f'node(w.r)["railway"~"^(signal|switch|buffer_stop|railway_crossing|crossing|derail)$"];out tags qt;')


def _int(v):
    try:
        return int(str(v).split(";")[0])
    except Exception:
        return None


def signalling_of(tags):
    """Clase de señalización SOLO si el propio dato lo dice."""
    def on(k):
        v = tags.get(k)
        return v is not None and str(v).lower() not in ("no", "none", "0", "")
    if on("railway:etcs") or on("railway:ertms"):
        return "ETCS"
    if on("railway:lzb"):
        return "LZB"
    if on("railway:asfa"):
        return "ASFA"
    return None


def simplify(pts, tol=TOL_KM):
    """Douglas-Peucker iterativo sobre [(x,y)] en km."""
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        (ax, ay), (bx, by) = pts[a], pts[b]
        dx, dy = bx - ax, by - ay
        L = math.hypot(dx, dy) or 1e-9
        far, fi = -1.0, -1
        for i in range(a + 1, b):
            d = abs(dy * (pts[i][0] - ax) - dx * (pts[i][1] - ay)) / L
            if d > far:
                far, fi = d, i
        if far > tol:
            keep[fi] = True
            stack += [(a, fi), (fi, b)]
    return [p for p, k in zip(pts, keep) if k]


def build(elements):
    """Elementos de Overpass -> {'ways': [...], 'points': [...]} (dedupe entre teselas por id)."""
    ways, points = {}, {}
    for e in elements:
        t = e.get("tags") or {}
        if e["type"] == "way" and e.get("geometry"):
            pts = simplify([project(g["lat"], g["lon"]) for g in e["geometry"]])
            if len(pts) < 2:
                continue
            ways[e["id"]] = {"t": _int(t.get("tracks")), "s": signalling_of(t), "v": _int(t.get("maxspeed")),
                             "el": (None if "electrified" not in t else t["electrified"] not in ("no", "")),
                             "p": [[round(x, 2), round(y, 2)] for x, y in pts]}
        elif e["type"] == "node" and "lat" in e:
            kind = POINT_KINDS.get(t.get("railway", ""))
            if not kind:
                continue
            x, y = project(e["lat"], e["lon"])
            det = (t.get("railway:signal:main") or t.get("railway:signal:distant") or t.get("railway:signal:speed_limit")
                   or t.get("railway:switch") or t.get("name") or "")
            if kind == "signal":
                sub = ("principal" if "railway:signal:main" in t else "previa" if "railway:signal:distant" in t
                       else "velocidad" if "railway:signal:speed_limit" in t else "")
                det = sub
            points[e["id"]] = {"k": kind, "x": round(x, 3), "y": round(y, 3), "d": str(det)[:40]}
    return list(ways.values()), list(points.values())


def section_changes(ways):
    """Marca los extremos compartidos entre vías con distinto nº de vías o distinta señalización."""
    ends = {}
    for w in ways:
        for i in (0, -1):
            ends.setdefault((round(w["p"][i][0], 1), round(w["p"][i][1], 1)), []).append(w)
    out = []
    for (x, y), ws in ends.items():
        if len(ws) != 2:
            continue
        a, b = ws
        if a["t"] and b["t"] and a["t"] != b["t"]:
            out.append({"k": "change", "x": x, "y": y, "d": f"{a['t']}→{b['t']} vías"})
        elif a["s"] and b["s"] and a["s"] != b["s"]:
            out.append({"k": "change", "x": x, "y": y, "d": f"{a['s']}→{b['s']}"})
    return out


def load_extra(path):
    """Datos oficiales opcionales. Formato: {"source": "...", "points": [{"k":"balise|lzb_loop|signal|...","lat":..,"lon":..,"d":".."}],
    "cantones": [{"id":"..","line":"..","points":[[lat,lon],...]}]}"""
    if not os.path.exists(path):
        return {}, [], []
    j = json.load(open(path, encoding="utf-8"))
    pts = []
    for p in j.get("points", []):
        x, y = project(p["lat"], p["lon"])
        pts.append({"k": p.get("k", "other"), "x": round(x, 3), "y": round(y, 3), "d": p.get("d", ""), "official": True})
    cant = [{"id": c.get("id"), "line": c.get("line"), "p": [[round(a, 2), round(b, 2)] for a, b in (project(*q) for q in c["points"])]}
            for c in j.get("cantones", [])]
    return {"extra_source": j.get("source", "fichero local")}, pts, cant


class Infra:
    def __init__(self, cache="data/infra_cache.json", extra="data/infra_extra.json", opener=None):
        self.cache, self.extra = cache, extra
        self.open = opener or self._http
        self.data = None
        self.status = {"state": "pendiente", "tiles_done": 0, "tiles_total": sum(1 for _ in tiles())}
        self.lock = threading.Lock()

    @staticmethod
    def _http(ep, q):
        req = urllib.request.Request(ep, data=("data=" + urllib.parse.quote(q)).encode(),
                                     headers={"User-Agent": "RailGuard/1.0 (WhiteMoon; contact whitemoon.es)"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)

    def _tile(self, b):
        last = None
        for attempt in range(2):
            for ep in ENDPOINTS:
                try:
                    return self.open(ep, query(b))["elements"]
                except Exception as ex:  # 429/502/timeout: probar otro servidor
                    last = ex
                    self.status["last_error"] = f"{ep.split('/')[2]}: {ex!r}"[:140]
                    time.sleep(2)
        raise RuntimeError(f"tesela {b}: {last!r}")

    def run(self):
        try:
            if os.path.exists(self.cache) and time.time() - os.path.getmtime(self.cache) < 7 * 86400:
                self._set(json.load(open(self.cache, encoding="utf-8")))
                return
            els, failed = [], []
            self.status["state"] = "descargando"
            for b in tiles():
                try:
                    t0 = time.time()
                    els += self._tile(b)
                    self.status["last_tile_s"] = round(time.time() - t0, 1)
                except Exception as ex:
                    failed.append(str(ex)[:120])
                self.status["tiles_done"] += 1
                self.status["state"] = "descargando"
                time.sleep(1)
            ways, points = build(els)
            data = {"ways": ways, "points": points + section_changes(ways), "failed_tiles": len(failed)}
            if ways:
                os.makedirs(os.path.dirname(self.cache) or ".", exist_ok=True)
                json.dump(data, open(self.cache, "w", encoding="utf-8"), separators=(",", ":"))
            self._set(data)
            if failed:
                self.status["errors"] = failed[:3]
        except Exception as ex:
            self.status.update(state="error", error=repr(ex)[:200])

    def _set(self, data):
        meta, xp, cant = load_extra(self.extra)
        d = dict(data)
        d["points"] = list(data["points"]) + xp
        d["cantones"] = cant
        d["meta"] = {"source": "OpenStreetMap (ODbL) · © colaboradores de OpenStreetMap", "official": False,
                     "fetched": int(time.time()), **meta,
                     "counts": {"ways": len(d["ways"]), "points": len(d["points"]),
                                "with_tracks": sum(1 for w in d["ways"] if w["t"]),
                                "with_signalling": sum(1 for w in d["ways"] if w["s"]),
                                "signals": sum(1 for p in d["points"] if p["k"] == "signal"),
                                "switches": sum(1 for p in d["points"] if p["k"] == "switch"),
                                "changes": sum(1 for p in d["points"] if p["k"] == "change"),
                                "cantones": len(cant)}}
        with self.lock:
            self.data = d
            self.status.update(state="listo")

    def start(self):
        threading.Thread(target=self.run, daemon=True).start()
