"""Trazado ferroviario OFICIAL del IGN (INSPIRE «Redes de transporte», capa tn-ra:RailwayLink).

Fuente: servicio WFS del IGN/CNIG  https://servicios.idee.es/wfs-inspire/transportes
Licencia: CC BY 4.0 · © Instituto Geográfico Nacional de España.
Comprobado desde el navegador: ~60.000 tramos, geometría real de la vía en EPSG:4326 (lat lon).
LIMITACIÓN: esta capa trae SOLO geometría (más una marca `fictitious` para conectores); NO trae número de vías, señales,
electrificación ni velocidades. Esos datos siguen pendientes de Adif. Aquí no se inventa ninguno (t=None).
"""
import io
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from renfe_adapter import project

BASE = "https://servicios.idee.es/wfs-inspire/transportes"
UA = {"User-Agent": "RailGuard/1.0 (WhiteMoon; supervision ferroviaria; contacto whitemoon.es)"}
PAGE = 4000


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


def load(diag, simplify, max_pages=40):
    """Descarga y proyecta los tramos reales. `simplify` es infra.simplify (Douglas-Peucker en km)."""
    hits = _get(_url(service="WFS", version="2.0.0", request="GetFeature", typeNames="tn-ra:RailwayLink", resultType="hits"), 60)
    m = re.search(rb'numberMatched="(\d+)"', hits)
    total = int(m.group(1)) if m else None
    diag["total"] = total
    ways, got, real = [], 0, 0
    for page in range(max_pages):
        raw = _get(_url(service="WFS", version="2.0.0", request="GetFeature", typeNames="tn-ra:RailwayLink",
                        srsName="urn:ogc:def:crs:EPSG::4326", count=PAGE, startIndex=page * PAGE))
        links = parse_links(raw)
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
        if len(links) < PAGE or (total and got >= total):
            break
    diag["real_links"] = real
    if not ways:
        raise RuntimeError("IGN WFS sin tramos utilizables")
    return ways
