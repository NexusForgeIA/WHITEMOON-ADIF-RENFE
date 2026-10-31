"""Fuentes públicas gratuitas y SIN CLAVE para dar contexto a la supervisión (capa informativa, aislada de las barreras B0–B5).

  · Red Eléctrica (REData): demanda real frente a prevista, cada 5 min.
  · IGN: terremotos de los últimos 10 días (GeoRSS).
  · AEMET: avisos meteorológicos en CAP con polígono (se descargan solo los CAP nuevos).
  · NASA FIRMS: focos de calor VIIRS de las últimas 24 h.
Cada fuente se lee en su propio hilo: si una falla o tarda, no afecta a las demás ni a la lectura de trenes. Los parsers son funciones puras.
"""
import csv
import io
import json
import re
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from html import unescape

UA = {"User-Agent": "RailGuard/1.0 (WhiteMoon; supervision ferroviaria)"}
LICENSE = {
    "ree": "Fuente: Red Eléctrica (REData). Uso informativo",
    "ign": "Obra derivada del catálogo de terremotos del IGN · CC-BY 4.0 · Instituto Geográfico Nacional",
    "aemet": "© AEMET · avisos sin alterar: nivel, zona, vigencia y fecha de emisión",
    "firms": "NASA FIRMS (LANCE, ESDIS) · datos de NASA sin restricciones de uso · no apto para decisiones tácticas",
}
AEMET_RSS = "https://www.aemet.es/documentos_d/eltiempo/prediccion/avisos/rss/CAP_AFAE_wah_RSS.xml"
FIRMS_BASE = "https://firms.modaps.eosdis.nasa.gov/data/active_fire/noaa-20-viirs-c2/csv"
FIRMS_FILES = [f"{FIRMS_BASE}/J1_VIIRS_C2_Europe_24h.csv", f"{FIRMS_BASE}/J1_VIIRS_C2_Northern_and_Central_Africa_24h.csv"]
# España: península (con Portugal y franja pirenaica), Baleares y Canarias. Al sur de 37° N no hay territorio español al este de -1,6° (Argelia).
AREAS = [(35.8, 43.9, -9.6, 4.5), (27.4, 29.6, -18.3, -13.2)]
LEVELS = {"yellow": "amarillo", "orange": "naranja", "red": "rojo"}


def in_spain(lat, lon):
    if lat < 37 and lon > -1.6:
        return False
    return any(a <= lat <= b and c <= lon <= d for a, b, c, d in AREAS)


def _ln(tag):
    return tag.rsplit("}", 1)[-1]


def _kids(el, name):
    return [c for c in el if _ln(c.tag) == name]


def _t(el, name):
    for c in el.iter():
        if _ln(c.tag) == name and c.text is not None:
            return c.text.strip()
    return None


def _iso_ms(s):
    """Marca ISO 8601 (con 'Z' o desfase) → epoch ms; None si no se entiende."""
    if not s:
        return None
    try:
        from datetime import datetime, timezone
        d = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return int(d.timestamp() * 1000)
    except Exception:
        return None


# ---------- Red Eléctrica ----------
def parse_ree(data):
    series = {s.get("type"): (s.get("attributes") or {}).get("values") or [] for s in data.get("included") or []}
    real, fc = series.get("Real") or [], {v["datetime"]: v["value"] for v in series.get("Prevista") or []}
    if not real:
        return None
    last = real[-1]
    exp = fc.get(last["datetime"])
    dev = (last["value"] - exp) / exp if exp else None
    return {"demandMW": last["value"], "forecastMW": exp, "deviation": dev, "at": _iso_ms(last["datetime"]),
            "history": [{"t": _iso_ms(v["datetime"]), "real": v["value"], "forecast": fc.get(v["datetime"])} for v in real[-36:]]}


# ---------- IGN sismos ----------
_QUAKE = re.compile(r"magnitud\s+([\d.]+)\s+en\s+(.+?)\s+en la fecha\s+(\d+)/(\d+)/(\d+)\s+(\d+):(\d+):(\d+)")


def parse_ign(xml_text):
    out = []
    try:
        root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    except ET.ParseError:
        return out
    for it in root.iter():
        if _ln(it.tag) != "item":
            continue
        desc = unescape(_t(it, "description") or "")
        m = _QUAKE.search(desc)
        try:
            lat, lon = float(_t(it, "lat")), float(_t(it, "long"))
        except (TypeError, ValueError):
            continue
        if not m:
            continue
        mag, place, dd, mm, yy, hh, mi, ss = m.groups()
        import calendar
        t = calendar.timegm((int(yy), int(mm), int(dd), int(hh), int(mi), int(ss))) * 1000   # el RSS del IGN va en UTC
        mg = float(mag)
        guid = _t(it, "guid") or ""
        out.append({"id": "ign:" + (re.search(r"evid=(\w+)", guid) or [None, str(t)])[1], "cat": "sismo", "mag": mg, "lat": lat, "lon": lon, "t": t,
                    "sev": "muy alta" if mg >= 5 else "alta" if mg >= 4 else "media" if mg >= 3 else "baja",
                    "title": f"Terremoto M{mg:.1f} · {place}", "url": _t(it, "link")})
    return out


# ---------- AEMET (CAP) ----------
def _ring(poly):
    pts = []
    for p in poly.split():
        try:
            la, lo = p.split(",")
            pts.append((float(lo), float(la)))   # (lon, lat)
        except ValueError:
            continue
    if pts and pts[0] != pts[-1]:
        pts.append(pts[0])
    return pts


def parse_cap(xml_text):
    try:
        root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    except ET.ParseError:
        return []
    if (_t(root, "msgType") or "") == "Cancel":
        return []
    infos = _kids(root, "info")
    info = next((i for i in infos if (_t(i, "language") or "").startswith("es")), infos[0] if infos else None)
    if info is None:
        return []
    params = {}
    for p in _kids(info, "parameter"):
        params[(_t(p, "valueName") or "")] = (_t(p, "value") or "")
    lvl = params.get("AEMET-Meteoalerta nivel", "").strip().lower()
    if lvl not in LEVELS.values():
        lvl = LEVELS.get((params.get("awareness_level", "").split(";") + ["", ""])[1].strip(), "")
    if lvl not in ("amarillo", "naranja", "rojo"):
        return []
    event = re.sub(r"\s+de nivel \w+$", "", re.sub(r"^aviso (de|por)\s+", "", _t(info, "event") or "fenómenos adversos", flags=re.I), flags=re.I)
    ident = _t(root, "identifier") or ""
    out = []
    for i, area in enumerate(_kids(info, "area")):
        rings = [r for r in (_ring(p.text or "") for p in _kids(area, "polygon")) if len(r) >= 4]
        if not rings:
            continue
        name = _t(area, "areaDesc") or ""
        out.append({"id": f"aemet:{ident}:{i}", "cat": "meteo", "level": lvl, "type": event, "rings": rings, "area": name,
                    "title": f"Aviso {lvl} por {event} · {name}", "desc": _t(info, "description") or "",
                    "start": _iso_ms(_t(info, "onset") or _t(info, "effective")), "end": _iso_ms(_t(info, "expires")),
                    "sev": "muy alta" if lvl == "rojo" else "alta" if lvl == "naranja" else "media"})
    return out


def cap_links(rss_text):
    try:
        root = ET.fromstring(rss_text.encode("utf-8") if isinstance(rss_text, str) else rss_text)
    except ET.ParseError:
        return []
    return [(_t(it, "link") or _t(it, "guid") or "").strip() for it in root.iter() if _ln(it.tag) == "item"]


# ---------- NASA FIRMS ----------
def parse_firms(csv_text):
    out = []
    for r in csv.DictReader(io.StringIO(csv_text)):
        try:
            lat, lon, frp = float(r["latitude"]), float(r["longitude"]), float(r.get("frp") or 0)
        except (KeyError, ValueError):
            continue
        if not in_spain(lat, lon) or (r.get("confidence") or "").lower().startswith("l"):
            continue
        hhmm = (r.get("acq_time") or "0000").zfill(4)
        try:
            import calendar
            y, m, d = (int(x) for x in r["acq_date"].split("-"))
            t = calendar.timegm((y, m, d, int(hhmm[:2]), int(hhmm[2:]), 0)) * 1000
        except Exception:
            continue
        out.append({"id": f"firms:{lat:.4f}:{lon:.4f}:{r['acq_date']}{hhmm}", "cat": "incendio", "lat": lat, "lon": lon, "frp": frp, "t": t,
                    "sev": "alta" if frp >= 50 else "media" if frp >= 10 else "baja", "title": f"Foco de calor de {round(frp)} MW"})
    return out


def _get(url, timeout=25):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


class Extras:
    """Estado compartido de las cuatro fuentes. `get` y `now` son inyectables para probar sin red."""
    def __init__(self, get=_get, now=time.time, log=print):
        self.get, self.now, self.log = get, now, log
        self.lock = threading.Lock()
        self.ree = None
        self.events = {"ign": [], "aemet": [], "firms": []}
        self.status = {k: {"ok": None, "last_ok": None, "err": None, "n": 0, "interval": iv}
                       for k, iv in (("ree", 300), ("ign", 180), ("aemet", 600), ("firms", 3600))}
        self.caps = {}   # url → avisos (cada CAP es inmutable)

    def _done(self, key, n, err=None):
        with self.lock:
            s = self.status[key]
            s["ok"], s["n"], s["err"] = err is None, n, (repr(err)[:120] if err else None)
            if err is None:
                s["last_ok"] = self.now()
        self.log(f"[extras] {key}: " + ("ok (%d)" % n if err is None else "ERROR " + repr(err)[:100]))

    def refresh_ree(self):
        try:
            m = parse_ree(json.loads(self.get("https://apidatos.ree.es/es/datos/demanda/demanda-tiempo-real?start_date=%sT00:00&end_date=%sT23:59&time_trunc=hour" % ((time.strftime("%Y-%m-%d"),) * 2))))
            with self.lock:
                self.ree = m
            self._done("ree", 1 if m else 0, None if m else ValueError("sin datos"))
        except Exception as ex:
            self._done("ree", 0, ex)

    def refresh_ign(self):
        try:
            ev = parse_ign(self.get("https://www.ign.es/ign/RssTools/sismologia.xml"))
            with self.lock:
                self.events["ign"] = ev
            self._done("ign", len(ev))
        except Exception as ex:
            self._done("ign", 0, ex)

    def refresh_aemet(self, budget_s=50):
        try:
            links = cap_links(self.get(AEMET_RSS))
            if not links:
                raise ValueError("RSS sin avisos")
            t0 = time.time()
            for u in links:
                if u in self.caps:
                    continue
                if time.time() - t0 > budget_s:
                    break    # el resto se baja en el siguiente ciclo
                try:
                    self.caps[u] = parse_cap(self.get(u, 15))
                except Exception:
                    self.caps[u] = []
            for u in set(self.caps) - set(links):
                del self.caps[u]
            ev = [a for u in links for a in self.caps.get(u, [])]
            with self.lock:
                self.events["aemet"] = ev
            self._done("aemet", len(ev))
        except Exception as ex:
            self._done("aemet", 0, ex)

    def refresh_firms(self):
        try:
            ev = []
            for u in FIRMS_FILES:
                ev += parse_firms(self.get(u, 60))
            with self.lock:
                self.events["firms"] = ev
            self._done("firms", len(ev))
        except Exception as ex:
            self._done("firms", 0, ex)

    def start(self):
        for key, fn, period in (("ree", self.refresh_ree, 300), ("ign", self.refresh_ign, 180), ("aemet", self.refresh_aemet, 600), ("firms", self.refresh_firms, 3600)):
            def run(fn=fn, period=period):
                while True:
                    fn()
                    time.sleep(period)
            threading.Thread(target=run, daemon=True, name="extras-" + key).start()

    def snapshot(self):
        with self.lock:
            return {"ree": self.ree, "events": {k: list(v) for k, v in self.events.items()}, "status": {k: dict(v, license=LICENSE[k]) for k, v in self.status.items()}}
