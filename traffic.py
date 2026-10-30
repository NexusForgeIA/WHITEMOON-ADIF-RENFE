"""Incidencias de tráfico por carretera de la DGT (DATEX II v3.7, Punto de Acceso Nacional, CC BY, sin clave, 1 min).

Es información de CARRETERAS: sirve para ver obras, cortes, retenciones y accidentes cerca de pasos a nivel y de los accesos de
los servicios de emergencia. No es tráfico ferroviario. Solo informativo.
Fuente: https://nap.dgt.es/en/dataset/incidencias-dgt-datex2-v3-7 (aviso legal de la DGT)
"""
import json, math, os, threading, time, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime

from ltv import project

URL = "https://nap.dgt.es/datex2/v3/dgt/SituationPublication/datex2_v37.xml"
XSI = "{http://www.w3.org/2001/XMLSchema-instance}type"
KINDS = {"acc": "Accidente", "ret": "Retención", "cor": "Corte o restricción de carril", "obr": "Obras", "vel": "Limitación de velocidad",
         "met": "Meteorología", "cal": "Estado de la calzada", "otr": "Incidencia"}


def _ln(tag):
    return tag.rsplit("}", 1)[-1]


def kind_of(rtype, cause=""):
    t = (rtype or "").lower()
    if "accident" in t or "obstruction" in t:
        return "acc"
    if "abnormaltraffic" in t or "traffic" in t and "congest" in t:
        return "ret"
    if "maintenance" in t or "construction" in t or cause == "roadmaintenance":
        return "obr"
    if "speed" in t:
        return "vel"
    if "management" in t:
        return "cor"
    if "weather" in t or "environment" in t:
        return "met"
    if "nonweather" in t or "roadcondition" in t:
        return "cal"
    return "otr"


def _epoch(s):
    try:
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return None


def parse(xml_bytes, now=None):
    """DATEX II -> lista compacta. Solo registros vigentes y con coordenadas. Se lee por nombre local: no depende de los prefijos."""
    now = now or time.time()
    out = []
    for ev, el in ET.iterparse(__import__("io").BytesIO(xml_bytes), events=("end",)):
        if _ln(el.tag) != "situationRecord":
            continue
        txt = {}
        pts, comment = [], ""
        for e in el.iter():
            n = _ln(e.tag)
            if n == "pointCoordinates":
                la = lo = None
                for c in e:
                    if _ln(c.tag) == "latitude":
                        la = c.text
                    elif _ln(c.tag) == "longitude":
                        lo = c.text
                try:
                    pts.append((float(la), float(lo)))
                except (TypeError, ValueError):
                    pass
            elif n == "value" and not comment and (e.text or "").strip():
                comment = e.text.strip()
            elif e.text and e.text.strip() and n not in txt:
                txt[n] = e.text.strip()
        rid, rtype = el.get("id", ""), el.get(XSI, "").split(":")[-1]
        el.clear()
        if not pts or txt.get("validityStatus", "active") != "active":
            continue
        end = _epoch(txt.get("overallEndTime", ""))
        if end and end < now:
            continue
        k = kind_of(rtype, txt.get("causeType", "").lower())
        x0, y0 = project(*pts[0])
        item = {"id": rid, "k": k, "road": txt.get("roadName", ""), "pk": txt.get("kilometerPoint", ""),
                "mun": txt.get("municipality", ""), "prov": txt.get("province", ""), "x": round(x0, 3), "y": round(y0, 3),
                "s": _epoch(txt.get("overallStartTime", "")), "c": comment[:240]}
        if len(pts) >= 2 and pts[0] != pts[1]:
            x1, y1 = project(*pts[1])
            item["x1"], item["y1"] = round(x1, 3), round(y1, 3)
        out.append(item)
    return out


def near(items, x, y, r_km, kinds=None):
    """Incidencias a menos de r_km de (x, y) [km], de más cerca a más lejos: [(dist, item)]."""
    c = [(math.hypot((i["x"] + i.get("x1", i["x"])) / 2 - x, (i["y"] + i.get("y1", i["y"])) / 2 - y), i) for i in items if not kinds or i["k"] in kinds]
    return sorted(((d, i) for d, i in c if d <= r_km), key=lambda r: r[0])


class Traffic:
    def __init__(self, cache="data/traffic_cache.json", opener=None, period=300):
        self.cache, self.period = cache, period
        self.open = opener or self._http
        self.items, self.status = [], {"state": "pendiente"}
        self.lock = threading.Lock()
        try:
            d = json.load(open(cache, encoding="utf-8"))
            self.items, self.status = d["items"], {"state": "caché", "fetched": d.get("fetched"), "n": len(d["items"])}
        except Exception:
            pass

    @staticmethod
    def _http():
        req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0 RailGuard/1.0 (WhiteMoon; whitemoon.es)", "Accept": "application/xml"})
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.read()

    def refresh(self):
        items = parse(self.open())
        with self.lock:
            self.items = items
            c = {}
            for i in items:
                c[i["k"]] = c.get(i["k"], 0) + 1
            self.status = {"state": "oficial-dgt", "fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "n": len(items), "por_tipo": c}
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
                self.status = {**self.status, "error": repr(ex)[:120], "state": self.status.get("state") if self.items else "error"}
            time.sleep(self.period)

    def start(self):
        threading.Thread(target=self._loop, daemon=True, name="traffic").start()

    def api(self):
        with self.lock:
            return {"ready": bool(self.items) or self.status.get("state") == "oficial-dgt", "status": self.status, "kinds": KINDS, "items": self.items,
                    "source": "DGT · Punto de Acceso Nacional (DATEX II v3.7, CC BY). Carreteras, no ferrocarril. Solo informativo."}
