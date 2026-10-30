"""Trazado ferroviario OFICIAL del IGN (INSPIRE «Redes de transporte», capa tn-ra:RailwayLink).

Fuente: servicio WFS del IGN/CNIG  https://servicios.idee.es/wfs-inspire/transportes
Licencia: CC BY 4.0 · © Instituto Geográfico Nacional de España.
Comprobado desde el navegador: ~60.000 tramos, geometría real de la vía en EPSG:4326 (lat lon).
LIMITACIÓN: esta capa trae SOLO geometría (más una marca `fictitious` para conectores); NO trae número de vías, señales,
electrificación ni velocidades. Esos datos siguen pendientes de Adif. Aquí no se inventa ninguno (t=None).
"""
import io
import re
import time
from concurrent.futures import ThreadPoolExecutor
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from renfe_adapter import project

BASE = "https://servicios.idee.es/wfs-inspire/transportes"
UA = {"User-Agent": "RailGuard/1.0 (WhiteMoon; supervision ferroviaria; contacto whitemoon.es)"}
PAGE = 2000   # páginas más pequeñas: los offsets profundos con 4000 daban 502 del proxy del IGN
WORKERS = 3
MIN_COVERAGE = 0.85   # fracción mínima de páginas para publicar un trazado (si no, error)


def _url(**kw):
    return BASE + "?" + urllib.parse.urlencode(kw, safe=":")


def _get(url, timeout=120):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def parse_links(xml_bytes):
    """GML 3.2 de RailwayLink -> [(fictitious, [(lat, lon), ...])]. Se ignora el prefijo de espacio de nombres."""
    out = []
    for _, e in ET.iterparse(io.BytesIO(xml_bytes), events=("end",)):
        if not e.tag.endswith("}RailwayLink"):
            continue
        fict, pos = False, None
        for c in e.iter():
            t = c.tag.rsplit("}", 1)[-1]
            if t == "fictitious":
                fict = (c.text or "").strip().lower() == "true"
            elif t == "posList" and pos is None:
                pos = (c.text or "").split()
        e.clear()
        if pos and len(pos) >= 4:
            v = [float(x) for x in pos]
            out.append((fict, list(zip(v[0::2], v[1::2]))))
    return out


def load(diag, simplify, max_pages=80):
    """Descarga y proyecta los tramos reales. `simplify` es infra.simplify (Douglas-Peucker en km)."""
    hits = _get(_url(service="WFS", version="2.0.0", request="GetFeature", typeNames="tn-ra:RailwayLink", resultType="hits"), 60)
    m = re.search(rb'numberMatched="(\d+)"', hits)
    total = int(m.group(1)) if m else None
    diag["total"] = total
    ways, got, real = [], 0, 0
    pages = min(max_pages, (total // PAGE + 1) if total else max_pages)

    def fetch(page, tries=6):
        for attempt in range(tries):
            try:
                return parse_links(_get(_url(service="WFS", version="2.0.0", request="GetFeature", typeNames="tn-ra:RailwayLink",
                                             srsName="urn:ogc:def:crs:EPSG::4326", count=PAGE, startIndex=page * PAGE), 180))
            except Exception as ex:
                diag["last_error"] = repr(ex)[:120]
                time.sleep(min(30, 3 * (attempt + 1)))
        return None   # no se aborta todo por una página: se reintenta al final

    def add(links):
        nonlocal got, real
        got += len(links)
        diag["downloaded"] = got
        for fict, ll in links:
            if fict:
                continue   # conectores ficticios (enlaces de estación): no son vía
            pts = simplify([project(la, lo) for la, lo in ll])
            if len(pts) >= 2:
                real += 1
                ways.append({"t": None, "s": None, "v": None, "el": None, "src": "ign",
                             "p": [[round(x, 2), round(y, 2)] for x, y in pts]})

    failed = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:   # páginas en paralelo: el servidor tarda más cuanto más profundo es el offset
        for page, links in enumerate(ex.map(fetch, range(pages))):
            if links is None:
                failed.append(page)
            else:
                add(links)
    for page in list(failed):   # segunda pasada, en serie, con más paciencia
        links = fetch(page, tries=8)
        if links is not None:
            add(links)
            failed.remove(page)
    diag["failed_pages"] = failed
    if pages and len(failed) / pages > 1 - MIN_COVERAGE:
        raise RuntimeError(f"IGN: {len(failed)} de {pages} páginas sin descargar ({diag.get('last_error')})")
    diag["real_links"] = real
    if not ways:
        raise RuntimeError("IGN WFS sin tramos utilizables")
    return ways
