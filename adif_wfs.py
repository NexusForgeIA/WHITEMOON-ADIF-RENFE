"""Cargador de la red ferroviaria OFICIAL de Adif (servicio WFS de la iDE de Adif, INSPIRE TN-Rail).

Fuente: https://ideadif.adif.es/services/wfs  (© Administrador de infraestructuras ferroviarias; uso libre citando la autoría).
Devuelve tramos con nº de vías, electrificación, ancho y velocidad de DISEÑO (no operativa) en el mismo formato que infra.py.

El esquema exacto no se conocía al escribir esto (el servicio no era accesible desde el entorno de desarrollo), así que el cargador
DESCUBRE las capas con GetCapabilities y busca los atributos por nombre sin distinguir mayúsculas. Todo lo que descubre queda en
`diag` para poder auditarlo (/api/infra). No inventa datos: lo que el servicio no trae queda sin valor.
"""
import json
import math
import re
import time
import urllib.parse
import urllib.request

from renfe_adapter import project

BASE = "https://ideadif.adif.es/services/wfs"
UA = {"User-Agent": "RailGuard/1.0 (WhiteMoon; supervision ferroviaria; contacto whitemoon.es)"}
PAGE = 2000
MAX_FEATURES = 60000


def _get(url, timeout=60):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _q(**kw):
    return BASE + "?" + urllib.parse.urlencode(kw)


def feature_types(xml):
    """Nombres de capas del GetCapabilities (sin depender del prefijo de espacio de nombres)."""
    return re.findall(r"<(?:\w+:)?FeatureType>\s*<(?:\w+:)?Name>([^<]+)</", xml)


def pick(props, *needles):
    """Valor del primer atributo cuyo nombre contenga alguno de los fragmentos (sin mayúsculas ni separadores)."""
    norm = {re.sub(r"[^a-z0-9]", "", k.lower()): v for k, v in props.items()}
    for n in needles:
        for k, v in norm.items():
            if n in k and v not in (None, ""):
                return v
    return None


def _num(v):
    try:
        if isinstance(v, str):
            m = re.search(r"-?\d+(?:[.,]\d+)?", v)
            return float(m.group().replace(",", ".")) if m else None
        return float(v)
    except Exception:
        return None


def _lines(geom):
    if not geom:
        return []
    t, c = geom.get("type"), geom.get("coordinates")
    if t == "LineString":
        return [c]
    if t == "MultiLineString":
        return list(c)
    return []


def _latlon(pt, swapped):
    return (pt[0], pt[1]) if swapped else (pt[1], pt[0])


def looks_swapped(coords):
    """GeoJSON es lon,lat; si el servidor devolvió lat,lon el primer valor cae en 36–44 y el segundo en −10–4."""
    x, y = coords[0][0], coords[0][1]
    return 35 <= x <= 45 and -11 <= y <= 5


def fetch_layer(name, diag, log=print):
    """Descarga una capa en GeoJSON paginando. Devuelve la lista de features."""
    feats, start, last_err = [], 0, None
    fmts = ["application/json", "json", "geojson", "application/geo+json"]
    fmt = diag.setdefault("formats", {}).get(name)
    while start < MAX_FEATURES:
        data = None
        for f in ([fmt] if fmt else fmts):
            try:
                raw = _get(_q(service="WFS", version="2.0.0", request="GetFeature", typeNames=name, outputFormat=f,
                              srsName="EPSG:4326", count=PAGE, startIndex=start), timeout=120)
                data = json.loads(raw)
                fmt = f
                diag["formats"][name] = f
                break
            except Exception as ex:
                last_err = repr(ex)[:160]
        if data is None:
            diag.setdefault("errors", []).append(f"{name}: {last_err}")
            break
        page = data.get("features") or []
        feats += page
        if len(page) < PAGE:
            break
        start += PAGE
    return feats


def load(diag, log=print):
    """Devuelve (ways, points) o lanza si no hay nada utilizable. `diag` se rellena con lo descubierto."""
    xml = _get(_q(service="WFS", request="GetCapabilities", version="2.0.0"), timeout=60).decode("utf-8", "replace")
    names = feature_types(xml)
    diag["layers"] = names[:60]
    if not names:
        raise RuntimeError("GetCapabilities sin capas (¿respuesta no WFS?): " + xml[:120].replace("\n", " "))
    link = [n for n in names if "railwaylink" in n.lower() and "sequence" not in n.lower()]
    stn = [n for n in names if "stationnode" in n.lower()]
    diag["selected"] = {"links": link[:3], "stations": stn[:2]}
    ways = []
    for n in link[:1]:
        feats = fetch_layer(n, diag, log)
        diag["links_downloaded"] = len(feats)
        if feats:
            diag["sample_props"] = {k: str(v)[:60] for k, v in (feats[0].get("properties") or {}).items()}
        swapped = None
        for f in feats:
            p = f.get("properties") or {}
            for line in _lines(f.get("geometry")):
                if len(line) < 2:
                    continue
                if swapped is None:
                    swapped = looks_swapped(line)
                    diag["axis_swapped"] = swapped
                pts = [project(*_latlon(c, swapped)) for c in line]
                tracks = _num(pick(p, "numberoftracks", "numvias", "tracks"))
                ways.append({"t": int(tracks) if tracks and tracks > 0 else None, "s": None,
                             "v": int(_num(pick(p, "designspeed", "speed", "velocidad")) or 0) or None,
                             "el": _electrified(pick(p, "electrification", "electrific")),
                             "g": pick(p, "gauge", "ancho"),
                             "u": pick(p, "railwayuse", "use"),
                             "p": [[round(x, 2), round(y, 2)] for x, y in pts]})
    points = []
    for n in stn[:1]:
        for f in fetch_layer(n, diag, log):
            g = f.get("geometry") or {}
            if g.get("type") == "Point":
                p = f.get("properties") or {}
                pts_swapped = diag.get("axis_swapped") or False
                x, y = project(*_latlon(g["coordinates"], pts_swapped))
                points.append({"k": "station", "x": round(x, 3), "y": round(y, 3),
                               "d": str(pick(p, "name", "nombre", "stationcode", "code") or "")[:40], "official": True})
        diag["stations_downloaded"] = len(points)
    if not ways:
        raise RuntimeError("El servicio respondió pero no se pudo extraer ningún tramo (ver diag)")
    return ways, points


def _electrified(v):
    if v is None:
        return None
    s = str(v).lower()
    return not (re.search(r"\b(no|none|false|sin)\b", s) or "not" in s)


def tracks_between(ways, a, b, samples=9, max_km=1.5):
    """Nº de vías predominante entre dos puntos (km) muestreando la recta y buscando el tramo oficial más cercano.
    Devuelve None si no hay tramos cercanos o sin dato. Usa una rejilla para que sea barato."""
    grid = _grid(ways)
    votes = []
    for i in range(1, samples + 1):
        f = i / (samples + 1)
        x, y = a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f
        best, bd = None, max_km
        cx, cy = int(x // 5), int(y // 5)
        for gx in (cx - 1, cx, cx + 1):
            for gy in (cy - 1, cy, cy + 1):
                for w in grid.get((gx, gy), ()):
                    for (x1, y1), (x2, y2) in zip(w["p"], w["p"][1:]):
                        d = _dist_seg(x, y, x1, y1, x2, y2)
                        if d < bd:
                            bd, best = d, w
        if best is not None and best.get("t"):
            votes.append(best["t"])
    if not votes:
        return None
    return max(set(votes), key=votes.count)


_grid_cache = {}


def _grid(ways):
    k = id(ways)
    if k in _grid_cache:
        return _grid_cache[k]
    g = {}
    for w in ways:
        seen = set()
        for x, y in w["p"]:
            c = (int(x // 5), int(y // 5))
            if c not in seen:
                seen.add(c)
                g.setdefault(c, []).append(w)
    _grid_cache.clear()
    _grid_cache[k] = g
    return g


def _dist_seg(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    L = dx * dx + dy * dy
    t = 0 if L == 0 else max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / L))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))
