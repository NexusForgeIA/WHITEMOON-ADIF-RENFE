"""Recursos de emergencia cercanos a la red: puestos y comandancias de la Guardia Civil y sedes de Cruz Roja.

Fuente: OpenStreetMap (Overpass). NO es un listado oficial: puede haber ausencias o datos desfasados; el dato que no
está en OSM (teléfono, dirección) simplemente no se muestra. Solo informativo: RailGuard no avisa ni moviliza a nadie.
"""
import json, math, os, threading, time, urllib.parse, urllib.request

# Servidores que responden bien (se prueban en este orden); overpass-api.de suele estar saturado
ENDPOINTS = ["https://overpass.openstreetmap.fr/api/interpreter", "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
             "https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
from ltv import project

LAT0, LAT1, LON0, LON1, STEP = 35.8, 44.0, -9.5, 4.5, 2.0
GC_RE = "Guardia Civil|Comandancia|Cuartel de la Guardia"
CR_RE = "Cruz Roja"
CR_AMEN = "ambulance_station|social_facility|clinic|hospital|doctors|community_centre"


def tiles():
    la = LAT0
    while la < LAT1:
        lo = LON0
        while lo < LON1:
            yield (la, lo, min(la + STEP, LAT1), min(lo + STEP, LON1))
            lo += STEP
        la += STEP


def query(b):
    """Consulta ligera: solo filtros de valor EXACTO (Overpass los resuelve por índice en segundos). El reparto entre Guardia
    Civil y Cruz Roja se hace después, en kind_of(). Las consultas con expresiones regulares sobre todo el mapa agotan el tiempo."""
    s, w, n, e = b
    bb = f"({s},{w},{n},{e})"
    f = ['["amenity"="police"]', '["operator"="Cruz Roja Española"]', '["operator"="Cruz Roja"]', '["brand"="Cruz Roja"]',
         '["emergency"="ambulance_station"]', '["amenity"="ambulance_station"]']
    return "[out:json][timeout:30];(" + "".join(f"nwr{x}{bb};" for x in f) + ");out tags center qt;"


def kind_of(tags):
    """'gc' | 'cr' | None, solo si el propio dato lo dice."""
    txt = f'{tags.get("operator", "")} {tags.get("name", "")}'.lower()
    if tags.get("amenity") == "police":
        return "gc" if ("guardia civil" in txt or "comandancia" in txt or "cuartel" in txt) else None
    who = f'{tags.get("operator", "")} {tags.get("brand", "")}'.lower()
    if "cruz roja" in who:
        return "cr"
    if "cruz roja" in txt and (tags.get("amenity") in CR_AMEN.split("|") or tags.get("emergency") == "ambulance_station"):
        return "cr"
    return None


def parse(elements):
    out, seen = [], set()
    for el in elements or []:
        tags = el.get("tags") or {}
        k = kind_of(tags)
        c = el if "lat" in el else (el.get("center") or {})
        if not k or "lat" not in c:
            continue
        key = (el.get("type"), el.get("id"))
        if key in seen:
            continue
        seen.add(key)
        x, y = project(float(c["lat"]), float(c["lon"]))
        addr = " ".join(filter(None, [tags.get("addr:street"), tags.get("addr:housenumber")]))
        town = " ".join(filter(None, [tags.get("addr:postcode"), tags.get("addr:city")]))
        tel = tags.get("phone") or tags.get("contact:phone") or ""
        out.append({"k": k, "n": tags.get("name") or ("Guardia Civil" if k == "gc" else "Cruz Roja"),
                    "x": round(x, 3), "y": round(y, 3), "a": ", ".join(filter(None, [addr, town])),
                    "t": tel.split(";")[0].strip(), "w": tags.get("website") or tags.get("contact:website") or "",
                    "id": f'{el.get("type", "n")[0]}{el.get("id")}'})
    return out


def nearest(items, x, y, kind, n=1):
    """Los n recursos de ese tipo más cercanos a (x, y) en km: [(dist_km, item)]."""
    c = sorted(((math.hypot(i["x"] - x, i["y"] - y), i) for i in items if i["k"] == kind), key=lambda r: r[0])
    return c[:n]


class Emergency:
    def __init__(self, cache="data/emergency_cache.json", opener=None):
        self.cache = cache
        self.open = opener or self._http
        self.items, self.status = [], {"state": "pendiente"}
        self.lock = threading.Lock()
        try:
            d = json.load(open(cache, encoding="utf-8"))
            self.items, self.status = d["items"], {"state": "caché", "fetched": d.get("fetched"), "n": len(d["items"])}
        except Exception:
            pass

    @staticmethod
    def _http(ep, q):
        req = urllib.request.Request(ep, data=("data=" + urllib.parse.quote(q)).encode(),
                                     headers={"User-Agent": "RailGuard/1.0 (WhiteMoon; contact whitemoon.es)"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)

    def refresh(self):
        els, failed, total = [], 0, sum(1 for _ in tiles())
        had = bool(self.items)      # con caché ya cargada no se publican parciales: bajaría de 1777 a 105 puntos durante minutos
        for n, b in enumerate(tiles(), 1):
            ok = False
            for ep in ENDPOINTS:
                try:
                    els += self.open(ep, query(b)).get("elements", [])
                    ok = True
                    break
                except Exception as ex:
                    self.status["last_error"] = repr(ex)[:100]
                    time.sleep(2)
            failed += not ok
            part = parse(els)
            with self.lock:       # los resultados parciales ya se pueden dibujar mientras se descarga el resto
                if part and not had:
                    self.items = part
                self.status = {**self.status, "state": "cargando", "tiles_done": n, "tiles_total": total, "n": len(self.items), "failed_tiles": failed}
            print(f"[emergencia] tesela {n}/{total} · {len(self.items)} recursos · fallidas {failed}", flush=True)
        items = parse(els)
        if not items:
            raise RuntimeError("Overpass no devolvió recursos de emergencia")
        with self.lock:
            self.items = items
            self.status = {"state": "oficial-osm", "fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "n": len(items),
                           "gc": sum(i["k"] == "gc" for i in items), "cr": sum(i["k"] == "cr" for i in items), "failed_tiles": failed,
                           "tiles_done": total, "tiles_total": total}
        try:
            os.makedirs(os.path.dirname(self.cache) or ".", exist_ok=True)
            json.dump({"fetched": self.status["fetched"], "items": items}, open(self.cache, "w", encoding="utf-8"), separators=(",", ":"))
        except OSError:
            pass

    def _loop(self):
        while True:
            try:
                self.refresh()
                wait = 7 * 86400      # cambian poco: una vez por semana
            except Exception as ex:
                self.status = {**self.status, "state": "error" if not self.items else "caché", "error": repr(ex)[:120]}
                wait = 1800
            time.sleep(wait)

    def start(self):
        threading.Thread(target=self._loop, daemon=True, name="emergency").start()

    def api(self):
        with self.lock:
            return {"ready": bool(self.items), "status": self.status, "items": self.items,
                    "source": "OpenStreetMap (no oficial). Solo informativo: RailGuard no avisa ni moviliza a nadie. En una emergencia, 112."}
