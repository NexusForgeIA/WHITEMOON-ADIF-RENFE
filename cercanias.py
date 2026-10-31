"""Capa INFORMATIVA de Cercanías/Rodalies (GTFS-RT vehicle positions de Renfe).

Aislada a propósito: estos trenes NO entran en el motor de seguridad (barreras, proximidad, previsión).
Motivo: el feed no trae velocidad y, en STOPPED_AT / INCOMING_AT, la posición es la de la propia estación (no GPS),
así que alimentar B1–B4 con ellos generaría saltos y cruces falsos. Se dibujan como marcadores huecos con su estado.
Se descarga en un hilo propio: si falla o tarda, la supervisión de larga distancia no se entera.
"""
import json
import re
import threading
import time
import urllib.request

from renfe_adapter import project

URL = "https://gtfsrt.renfe.com/vehicle_positions.json"
URL_ALERTS = "https://gtfsrt.renfe.com/alerts.json"
URL_TU = "https://gtfsrt.renfe.com/trip_updates.json"
REGION = {"10": "Madrid", "30": "Sevilla", "31": "Cádiz/Jerez", "32": "Málaga", "40": "Valencia", "41": "Murcia/Alicante", "51": "Rodalies Catalunya"}
_SERVICE = re.compile(r"sin servicio|no presta|suspendid|retraso|v[ií]a [uú]nica|transbordo|alternativ|no se puede garantizar|afectaci|no prestan|inicia su recorrido|fuera de su horario|incidencia", re.I)
_ACCESS = re.compile(r"ascensor|PMR|movilidad reducida|aseos|accesib", re.I)
UA = {"User-Agent": "RailGuard/1.0 (WhiteMoon; supervision ferroviaria)"}
STATUS = {"STOPPED_AT": "En estación", "INCOMING_AT": "Llegando a estación", "IN_TRANSIT_TO": "En marcha hacia"}


def _fetch(url=URL):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=12) as r:
        return json.load(r)


def _g(d, *names, default=None):
    for n in names:
        if isinstance(d, dict) and n in d:
            return d[n]
    return default


def _clean_label(label, vid):
    """«C1-23559-PLATF.(6)» -> («C1», «23559»). La línea es lo que va antes del primer guion."""
    m = re.match(r"^([A-Za-z]+\d*[A-Za-z]?)-(\d+)", label or "")
    return (m.group(1), m.group(2)) if m else ("", str(vid))


def parse(doc, now=None, km_per_px=1.0):
    """-> (trains, header_ts). Descarta entidades sin posición válida o fuera de la península/islas."""
    now = now or time.time()
    out = []
    for e in doc.get("entity", []) or []:
        v = _g(e, "vehicle")
        pos = _g(v, "position")
        if not v or not pos:
            continue
        try:
            lat, lon = float(pos["latitude"]), float(pos["longitude"])
        except Exception:
            continue
        if not (27 <= lat <= 44 and -19 <= lon <= 5):
            continue
        veh = _g(v, "vehicle", default={}) or {}
        vid = str(_g(veh, "id", default=_g(e, "id")))
        line, num = _clean_label(str(_g(veh, "label", default=vid)), vid)
        x, y = project(lat, lon)
        ts = int(_g(v, "timestamp", default=0) or 0)
        out.append({"id": vid, "trip": str(_g(_g(v, "trip", default={}) or {}, "tripId", "trip_id", default="") or ""), "n": (line + " " + num).strip(), "line": line, "x": x / km_per_px, "y": y / km_per_px,
                    "st": _g(v, "currentStatus", "current_status", default="?"), "stop": str(_g(v, "stopId", "stop_id", default="") or ""),
                    "age_s": max(0, int(now - ts)) if ts else None})
    hdr = int(_g(_g(doc, "header", default={}), "timestamp", default=0) or 0)
    return out, hdr


MAX_AGE_H = 6        # un aviso sin fecha de fin más antiguo que esto se descarta
STALE_MIN = 90       # si el texto cita una hora (p. ej. «a las 08:30h») y pasó hace más de esto, ya no vale


def _madrid_min(ts):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    d = datetime.fromtimestamp(ts, ZoneInfo("Europe/Madrid"))
    return d.hour * 60 + d.minute


_HORA = re.compile(r"\b(?:a las|de las|sobre las|las)\s+([01]?\d|2[0-3])[:.]([0-5]\d)\s*h?", re.I)


def _past_hours(text, hm_now):
    """True si TODAS las horas citadas en el texto pasaron hace más de STALE_MIN (hoy, hora de Madrid)."""
    hs = [int(m.group(1)) * 60 + int(m.group(2)) for m in _HORA.finditer(text)]
    return bool(hs) and all(0 <= hm_now - h > STALE_MIN for h in hs)


def parse_alerts(doc, now=None, limit=12):
    """Avisos de servicio activos (no accesibilidad/ascensores), más recientes primero. Solo informativo."""
    now = now or time.time()
    hdr = now   # la edad y la vigencia se miden contra la hora real, no contra la cabecera del feed (puede ir retrasada)
    hm_now = _madrid_min(now)
    out, seen = [], set()
    for e in doc.get("entity", []) or []:
        a = _g(e, "alert")
        if not a:
            continue
        per = (_g(a, "activePeriod", "active_period", default=[]) or [{}])[0]
        start, end = int(per.get("start") or 0), int(per.get("end") or 0)
        if (start and start > hdr + 300) or (end and end < hdr):
            continue
        if start and hdr - start > MAX_AGE_H * 3600 and not end:
            continue   # aviso sin fin y antiguo: casi seguro olvidado en el feed
        tr = (_g(_g(a, "descriptionText", "description_text", default={}), "translation", default=[]) or [{}])[0]
        text = re.sub(r"\s+", " ", str(tr.get("text") or "")).strip()
        if not text or _ACCESS.search(text) or not _SERVICE.search(text):
            continue
        routes = [str(i.get("routeId") or "") for i in (_g(a, "informedEntity", "informed_entity", default=[]) or [])]
        routes = [r for r in routes if r]
        lines = sorted({m.group(1) for r in routes for m in [re.search(r"([CRT]\d+)[a-z]?$", r)] if m})
        region = REGION.get(routes[0][:2], "Cercanías") if routes else "Cercanías"
        if _past_hours(text, hm_now):
            continue   # habla de un tren/hora concreta ya pasada hace tiempo
        key = (region, text[:80])
        if key in seen:
            continue
        seen.add(key)
        out.append({"id": str(_g(e, "id", default="")), "region": region, "lines": lines[:8], "text": text[:420],
                    "age_h": max(0, int((hdr - start) // 3600)) if start else 0,
                    "age_min": max(0, int((hdr - start) // 60)) if start else 0, "start": start})
    out.sort(key=lambda x: -x["start"])
    return out[:limit]


class CercaniasFeed:
    def __init__(self, km_per_px, opener=None, period=20, now=time.time, alerts_opener=None, tu_opener=None):
        self.k, self.open, self.period, self.now = km_per_px, opener or _fetch, period, now
        self.trains, self.hdr, self.ok_at, self.err, self.lines = [], 0, 0, None, {}
        self.alerts, self.alerts_ok, self.open_alerts = [], None, alerts_opener or (lambda: _fetch(URL_ALERTS))
        self.open_tu, self.delays, self.delays_ok = tu_opener or (lambda: _fetch(URL_TU)), {}, None
        self._stop = False

    def poll(self):
        try:
            doc = self.open()
            tr, hdr = parse(doc, self.now(), self.k)
            self.trains, self.hdr, self.ok_at, self.err = tr, hdr, self.now(), None
            self.lines = {}
            for t in tr:
                self.lines[t["line"] or "?"] = self.lines.get(t["line"] or "?", 0) + 1
        except Exception as ex:
            self.err = repr(ex)[:140]
        try:   # retrasos (trip_updates): fallo independiente; sin ellos los trenes siguen dibujándose
            from renfe_adapter import RenfeFeed
            self.delays, self.delays_ok = RenfeFeed._delays(self.open_tu()), True
        except Exception:
            self.delays_ok = False
        try:   # avisos: fallo independiente de las posiciones
            self.alerts, self.alerts_ok = parse_alerts(self.open_alerts(), self.now()), True
        except Exception:
            self.alerts_ok = False

    def start(self):
        def loop():
            while not self._stop:
                self.poll()
                time.sleep(self.period)
        threading.Thread(target=loop, daemon=True, name="cercanias").start()

    def delay_min(self, t):
        d = self.delays.get(t.get("trip"))
        return None if d is None else round(d / 60)

    def delay_rows(self):
        """[(n.º tren, retraso en min, "CER")] solo de trenes con retraso informado por Renfe (los demás no se cuentan como puntuales)."""
        if self.ok_at == 0 or self.now() - self.ok_at > 120:
            return []
        return [(t["n"], max(0, r), "CER") for t in self.trains for r in [self.delay_min(t)] if r is not None]

    def snapshot(self):
        age = None if not self.ok_at else round(self.now() - self.ok_at)
        stale = self.ok_at == 0 or age > 120
        return {"ok": not stale and not self.err, "err": self.err, "age_s": age, "count": len(self.trains), "lines": self.lines,
                "hdr_age_s": round(self.now() - self.hdr) if self.hdr else None,
                "alerts": self.alerts, "alerts_ok": self.alerts_ok, "delays_ok": self.delays_ok, "delay_n": len(self.delay_rows()),
                "trains": [] if stale else [[t["n"], round(t["x"], 2), round(t["y"], 2), t["st"], t["stop"], t["age_s"], self.delay_min(t)] for t in self.trains]}
