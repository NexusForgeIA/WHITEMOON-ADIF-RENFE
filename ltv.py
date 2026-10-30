"""LTV: limitaciones temporales de velocidad publicadas por Adif (visor público ArcGIS).

Fuente: FeatureServer público de Adif «Límites temporales de velocidad». NO es una fuente de
seguridad: es el visor informativo. Se usa solo para mostrar y para avisos CAUTION en B2.
Si el servidor no llega a ArcGIS se usa la última caché en disco; si no hay, la capa queda vacía.
"""
import json, math, os, threading, time, urllib.parse, urllib.request

URL = "https://services7.arcgis.com/XTupIrLX53AjaJqO/arcgis/rest/services/LTV_2/FeatureServer/0/query"
FIELDS = "CODLINEA,PKINI,PKFIN,RESTRICCIONVELOCIDAD,VIAS,DESCPSINI,DESCPSFIN,LTVID"
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
                    "to": a.get("DESCPSFIN") or "", "x": round(x, 2), "y": round(y, 2)})
    return out


def near(items, x, y, r_km=3.0):
    """LTV a menos de r_km del punto (x,y) en km, ordenadas por cercanía."""
    r2 = r_km * r_km
    hit = [(((i["x"] - x) ** 2 + (i["y"] - y) ** 2), i) for i in items]
    return [i for d, i in sorted(hit, key=lambda t: t[0]) if d <= r2]


class Ltv:
    def __init__(self, cache="data/ltv_cache.json", opener=None, period=1800):
        self.cache, self.period = cache, period
        self.open = opener or self._http
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
        self.items = items
        self.status = {"state": "oficial", "fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "n": len(items)}
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
