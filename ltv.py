"""LTV: limitaciones temporales de velocidad publicadas por Adif (visor público ArcGIS).

Fuente: FeatureServer público de Adif «Límites temporales de velocidad». NO es una fuente de
seguridad: es el visor informativo. Se usa solo para mostrar y para avisos CAUTION en B2.
Si el servidor no llega a ArcGIS se usa la última caché en disco; si no hay, la capa queda vacía.
"""
import json, math, os, threading, time, urllib.parse, urllib.request

URL = "https://services7.arcgis.com/XTupIrLX53AjaJqO/arcgis/rest/services/LTV_2/FeatureServer/0/query"
FIELDS = "CODLINEA,PKINI,PKFIN,RESTRICCIONVELOCIDAD,VIAS,DESCPSINI,DESCPSFIN,CODPSINI,CODPSFIN,OBSERVACIONES,LTVID"
LAT_N, LON_W = 44.0, -10.0
KM_LAT, KM_LON = 111.19, 111.32 * math.cos(math.radians(40.0))


def project(lat, lon):
    return (lon - LON_W) * KM_LON, (LAT_N - lat) * KM_LAT


def parse(feats):
    """Features ArcGIS (outSR=4326) -> registros compactos con x,y en km. Descarta lo inválido."""
    out = []
    for f in feats or []:
        a, g = f.get("attributes") or {}, f.get("geometry") or {}
        try:
            v = float(a["RESTRICCIONVELOCIDAD"])
            lon, lat = float(g["x"]), float(g["y"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (35 <= lat <= 45 and -10 <= lon <= 5) or not 0 < v <= 350:
            continue
        x, y = project(lat, lon)
        out.append({"id": a.get("LTVID"), "line": str(a.get("CODLINEA") or ""), "pk0": a.get("PKINI"), "pk1": a.get("PKFIN"),
                    "kmh": int(v), "vias": a.get("VIAS") or "", "from": a.get("DESCPSINI") or "",
                    "to": a.get("DESCPSFIN") or "", "c0": a.get("CODPSINI") or "", "c1": a.get("CODPSFIN") or "",
                    "obs": (a.get("OBSERVACIONES") or "").strip()[:200], "x": round(x, 2), "y": round(y, 2)})
    return out


def near(items, x, y, r_km=3.0):
    """LTV a menos de r_km del punto (x,y) en km, ordenadas por cercanía."""
    r2 = r_km * r_km
    hit = [(((i["x"] - x) ** 2 + (i["y"] - y) ** 2), i) for i in items]
    return [i for d, i in sorted(hit, key=lambda t: t[0]) if d <= r2]


TRAMOS_URL = "https://services7.arcgis.com/XTupIrLX53AjaJqO/ArcGIS/rest/services/Tramos_en_servicio_Adif_p%c3%bablico/FeatureServer/0/query"


def parse_tramos(feats):
    """Tramos oficiales de Adif -> {línea: [(pk_a, pk_b, [(x_km,y_km)...])]} con la geometría en km del proyecto."""
    out = {}
    for f in feats or []:
        a, g = f.get("attributes") or {}, f.get("geometry") or {}
        try:
            line = str(a["COD_LINEA"]).split(" ")[0].strip()
            pa, pb = float(a["PKI"]), float(a["PKD"])
            pts = [project(lat, lon) for lon, lat in g["paths"][0]]
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        if len(pts) >= 2 and pa != pb:
            out.setdefault(line, []).append((pa, pb, pts))
    return out


def _cut(pts, f0, f1):
    """Subtrayecto de la polilínea entre las fracciones de longitud f0..f1 (0..1)."""
    d = [0.0]
    for p, q in zip(pts, pts[1:]):
        d.append(d[-1] + math.hypot(q[0] - p[0], q[1] - p[1]))
    L = d[-1]
    if L <= 0:
        return []
    lo, hi = sorted((f0, f1))
    lo, hi = max(0.0, lo) * L, min(1.0, hi) * L

    def at(s):
        for k in range(1, len(d)):
            if s <= d[k] or k == len(d) - 1:
                w = 0 if d[k] == d[k - 1] else (s - d[k - 1]) / (d[k] - d[k - 1])
                return (pts[k - 1][0] + w * (pts[k][0] - pts[k - 1][0]), pts[k - 1][1] + w * (pts[k][1] - pts[k - 1][1]))
    mid = [p for p, s in zip(pts, d) if lo < s < hi]
    return [at(lo)] + mid + [at(hi)]


def geometry(tramos, line, pk0, pk1, max_pts=14):
    """Polilíneas (km) del tramo PK pk0..pk1 de una línea, a partir de los tramos oficiales; [] si no se puede."""
    try:
        lo, hi = sorted((float(pk0), float(pk1)))
    except (TypeError, ValueError):
        return []
    out = []
    for pa, pb, pts in tramos.get(str(line), []):
        a, b = sorted((pa, pb))
        if hi < a or lo > b:
            continue
        f = lambda pk: (pk - pa) / (pb - pa)
        cut = _cut(pts, f(max(lo, a)), f(min(hi, b)))
        if len(cut) > max_pts:
            step = (len(cut) - 1) / (max_pts - 1)
            cut = [cut[round(i * step)] for i in range(max_pts)]
        if len(cut) >= 2:
            out.append([[round(x, 2), round(y, 2)] for x, y in cut])
    return out[:2]


def dist_to_polyline(poly, x, y):
    best = 1e9
    for (ax, ay), (bx, by) in zip(poly, poly[1:]):
        L2 = (bx - ax) ** 2 + (by - ay) ** 2
        f = 0.0 if L2 <= 0 else max(0.0, min(1.0, ((x - ax) * (bx - ax) + (y - ay) * (by - ay)) / L2))
        best = min(best, math.hypot(x - (ax + f * (bx - ax)), y - (ay + f * (by - ay))))
    return best


def on_geometry(item, x, y, max_off_km=0.7):
    """True/False con geometría oficial del tramo; None si la LTV no la tiene."""
    g = item.get("g")
    if not g:
        return None
    return min(dist_to_polyline(p, x, y) for p in g) <= max_off_km


def on_segment(i, st, x, y, max_off_km=1.5):
    """True/False si el tren (x,y en km) está sobre el tramo entre las estaciones de la LTV; None si no se conocen ambas."""
    a, b = st.get(i.get("c0")), st.get(i.get("c1"))
    if not a or not b or i.get("c0") == i.get("c1"):
        return None
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    L2 = (bx - ax) ** 2 + (by - ay) ** 2
    f = 0.0 if L2 <= 0 else max(0.0, min(1.0, ((x - ax) * (bx - ax) + (y - ay) * (by - ay)) / L2))
    return math.hypot(x - (ax + f * (bx - ax)), y - (ay + f * (by - ay))) <= max_off_km


def matching(items, st, x, y, r_km=1.0):
    """LTV que afectan al tren en (x,y) km. Con geometría oficial: sobre el tramo (≤0,7 km). Sin ella: ≤r_km del punto y, si se conocen
    las estaciones, sobre el tramo entre ellas."""
    with_g = [i for i in items if i.get("g") and on_geometry(i, x, y)]
    without = [i for i in near([i for i in items if not i.get("g")], x, y, r_km) if on_segment(i, st, x, y) is not False]
    return with_g + without


class Ltv:
    def __init__(self, cache="data/ltv_cache.json", opener=None, period=1800):
        self.cache, self.period = cache, period
        self.open = opener or self._http
        self.open_tramos = opener or self._http_tramos
        self.geo_n = 0
        self.items, self.status = [], {"state": "pendiente"}
        try:
            d = json.load(open(cache, encoding="utf-8"))
            self.items, self.status = d["items"], {"state": "caché", "fetched": d.get("fetched"), "n": len(d["items"])}
        except Exception:
            pass

    @staticmethod
    def _http(params):
        req = urllib.request.Request(URL + "?" + urllib.parse.urlencode(params), headers={"User-Agent": "RailGuard/1.0 (WhiteMoon)"})
        with urllib.request.urlopen(req, timeout=40) as r:
            return json.load(r)

    @staticmethod
    def _http_tramos(params):
        req = urllib.request.Request(TRAMOS_URL + "?" + urllib.parse.urlencode(params), headers={"User-Agent": "RailGuard/1.0 (WhiteMoon)"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)

    def refresh(self):
        feats, off = [], 0
        while True:
            j = self.open({"where": "1=1", "outFields": FIELDS, "outSR": 4326, "returnGeometry": "true",
                           "resultOffset": off, "resultRecordCount": 1000, "f": "json"})
            if "error" in j:
                raise RuntimeError(str(j["error"])[:120])
            fs = j.get("features") or []
            feats += fs
            if not fs or not j.get("exceededTransferLimit") or off > 20000:
                break
            off += len(fs)
        items = parse(feats)
        if not items:
            raise RuntimeError("respuesta sin LTV válidas")
        try:
            tj = self.open_tramos({"where": "1=1", "outFields": "CODTRAMO,COD_LINEA,PKI,PKD", "returnGeometry": "true", "outSR": 4326,
                                   "maxAllowableOffset": 0.0003, "geometryPrecision": 5, "resultRecordCount": 2000, "f": "json"})
            tr = parse_tramos(tj.get("features"))
            n = 0
            for i in items:
                g = geometry(tr, i["line"], i["pk0"], i["pk1"])
                if g:
                    i["g"], n = g, n + 1
            self.geo_n = n
        except Exception as ex:
            self.geo_n, self.geo_err = 0, repr(ex)[:100]
        self.items = items
        self.status = {"state": "oficial", "fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "n": len(items), "con_geometria": self.geo_n}
        try:
            os.makedirs(os.path.dirname(self.cache) or ".", exist_ok=True)
            json.dump({"fetched": self.status["fetched"], "items": items}, open(self.cache, "w", encoding="utf-8"), separators=(",", ":"))
        except OSError:
            pass

    def _loop(self):
        while True:
            try:
                self.refresh()
            except Exception as ex:
                self.status = {**self.status, "error": repr(ex)[:120], "state": self.status.get("state") if self.items else "sin datos"}
            time.sleep(self.period)

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()

    def api(self):
        return {"ready": bool(self.items), "status": self.status, "source": "Adif · visor público de límites temporales de velocidad (informativo, no certificado)", "items": self.items}
