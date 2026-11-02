"""Alertas de energía (INFORMATIVAS): detecta apagones y ceros eléctricos por zona a partir de titulares de medios (Google Noticias RSS
público). Hasta ahora solo se miraba la demanda de la península (Red Eléctrica), que no ve una isla o una comarca sin luz.

NO es un aviso oficial ni verifica nada: son titulares. Un apagón que afecte al suministro de la red ferroviaria se confirma con el
operador. Aislada de las barreras B0–B6. Solo titular, medio, fecha y enlace; no se copia el contenido.
"""
import json
import os
import re
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
from html import unescape

import news as N

BASE = "https://news.google.com/rss/search?hl=es&gl=ES&ceid=ES:es&q="
QUERIES = ['(apagón OR "cero eléctrico" OR "cero energético" OR "sin luz" OR "sin suministro eléctrico" OR "caída de tensión") when:1d',
           '(apagón OR "sin luz" OR "cero eléctrico") (Canarias OR "La Palma" OR Tenerife OR "Gran Canaria" OR Lanzarote OR Fuerteventura OR "La Gomera" OR "El Hierro" OR Baleares OR Mallorca OR Ibiza OR Ceuta OR Melilla) when:1d']
OUTAGE = re.compile(r"apag[oó]n|cero el[eé]ctrico|cero energ[eé]tico|sin luz|sin (suministro|servicio) el[eé]ctrico|sin electricidad|ca[ií]da de tensi[oó]n|corte (de luz|el[eé]ctrico|de suministro)", re.I)
# no son sucesos actuales: precios, retrospectivas, política, investigaciones, apagón analógico/digital…
EXCL = re.compile(r"precio|factura|tarifa|recibo|bono social|aniversario|un a[ñn]o|28 de abril|informe|comisi[oó]n|investigaci|indemniz|juicio|"
                  r"ministr|gobierno|oposici|anal[oó]gico|digital|televisi|m[oó]vil|whatsapp|wifi|internet|operadora|futbol|f[uú]tbol|partido|serie|pel[ií]cula|"
                  r"c[oó]mo (actuar|prepar)|kit|consejos|simulacro|mapa del|opini[oó]n|editorial|apag[oó]n medi[aá]tico|apagón informativo|simulaci", re.I)
BIG = re.compile(r"toda la isla|isla entera|cero el[eé]ctrico|cero energ[eé]tico|apag[oó]n general|miles de|todo el (pa[ií]s|territorio)|sin luz toda|total", re.I)
PLACES = [("La Palma", r"la palma"), ("La Gomera", r"la gomera"), ("El Hierro", r"el hierro"), ("Tenerife", r"tenerife"), ("Gran Canaria", r"gran canaria"),
          ("Lanzarote", r"lanzarote"), ("Fuerteventura", r"fuerteventura"), ("Canarias", r"canarias|canario"), ("Mallorca", r"mallorca"),
          ("Ibiza", r"ibiza|eivissa"), ("Menorca", r"menorca"), ("Baleares", r"baleares"), ("Ceuta", r"ceuta"), ("Melilla", r"melilla"),
          ("Madrid", r"madrid"), ("Barcelona", r"barcelona|catalu[ñn]a"), ("Valencia", r"valencia"), ("Andalucía", r"andaluc[ií]a|sevilla|m[aá]laga|c[oó]rdoba"),
          ("Galicia", r"galicia|vigo|coru[ñn]a"), ("Península", r"pen[ií]nsula|toda espa[ñn]a|todo el pa[ií]s")]
PLACES = [(n, re.compile(r"\b(" + rx + r")\b", re.I)) for n, rx in PLACES]
MAX_AGE_S = 18 * 3600
RED_AGE_S = 12 * 3600


def parse(xml_text):
    out = []
    try:
        root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    except ET.ParseError:
        return out
    for it in root.iter():
        if N._ln(it.tag) not in ("item", "entry"):
            continue
        title = unescape(N._txt(it, "title"))
        src = N._txt(it, "source")
        if src and title.endswith(" - " + src):
            title = title[:-(len(src) + 3)]
        if not title or not OUTAGE.search(title) or EXCL.search(title) or N.FOREIGN.search(title) or N.FOREIGN_SRC.search(src):
            continue
        sn = next((e for e in it if N._ln(e.tag) == "source"), None)
        host = re.sub(r"^https?://", "", (sn.get("url") if sn is not None else "") or "")
        if host and N.FOREIGN_TLD.search(host.split("/")[0] + "/"):
            continue
        ts = N._when(N._txt(it, "pubDate", "published", "updated", "date"))
        if ts is None:
            continue
        out.append({"t": title, "s": src, "ts": int(ts), "u": N._txt(it, "link")})
    return out


def place_of(title):
    for name, rx in PLACES:
        if rx.search(title):
            return name
    return None


def build(items, now=None):
    """Agrupa titulares por zona. Devuelve alertas {id,type,sev,title,detail,place,n,ts,sources,links}. Sin zona reconocible → no hay alerta
    (un titular suelto sin lugar no es accionable)."""
    now = now or time.time()
    by = {}
    for i in items:
        age = now - i["ts"]
        if age > MAX_AGE_S or age < -600:
            continue
        pl = place_of(i["t"])
        if pl:
            by.setdefault(pl, []).append(i)
    out = []
    for pl, lst in by.items():
        lst.sort(key=lambda i: -i["ts"])
        top = next((i for i in lst if not N.FOLLOWUP.search(i["t"]) and not re.search(r"exige|investig|pide|critica|acusa|culp", i["t"], re.I)), lst[0])
        srcs = sorted({i["s"] for i in lst if i["s"]})
        first = min(i["ts"] for i in lst)
        age = now - top["ts"]
        big = any(BIG.search(i["t"]) for i in lst)
        red = age <= RED_AGE_S and (big or len(srcs) >= 2)
        mins = max(0, int((now - first) // 60))
        when = f"desde hace {mins} min" if mins < 90 else f"desde hace {mins // 60} h"
        out.append({"id": "energia-" + pl, "type": "energia", "sev": "muy alta" if red else "alta", "place": pl, "n": len(lst),
                    "title": f"Apagón · {pl}" if red else f"Posible apagón · {pl}",
                    "detail": f"{top['t']} · {', '.join(srcs[:3]) or 'medios'} · {when}" + (f" · {len(lst)} titulares" if len(lst) > 1 else "") + " · sin confirmar por el operador eléctrico",
                    "ts": top["ts"], "sources": srcs, "links": [i["u"] for i in lst[:3]], "trains": [], "lat": None, "lon": None})
    out.sort(key=lambda a: (a["sev"] != "muy alta", -a["ts"]))
    return out


class Energia:
    def __init__(self, cache="data/energia_cache.json", opener=None, period=180):
        self.cache, self.period, self.open = cache, period, opener or N.News._http
        self.items, self.status, self.lock = [], {"state": "pendiente"}, threading.Lock()
        try:
            d = json.load(open(cache, encoding="utf-8"))
            self.items, self.status = d["items"], {"state": "caché", "fetched": d.get("fetched")}
        except Exception:
            pass

    def refresh(self):
        got, errs = [], 0
        for q in QUERIES:
            try:
                got += parse(self.open(BASE + urllib.parse.quote(q)))
            except Exception:
                errs += 1
        seen, uniq = set(), []
        for i in sorted(got, key=lambda i: -i["ts"]):
            if i["t"] not in seen:
                seen.add(i["t"])
                uniq.append(i)
        with self.lock:
            if errs < len(QUERIES):
                self.items = uniq
                self.status = {"state": "ok", "fetched": int(time.time() * 1000), "n": len(uniq)}
            else:
                self.status = {**self.status, "state": "error"}
        try:
            os.makedirs(os.path.dirname(self.cache) or ".", exist_ok=True)
            json.dump({"items": self.items, "fetched": self.status.get("fetched")}, open(self.cache, "w", encoding="utf-8"))
        except OSError:
            pass

    def alerts(self, now=None):
        with self.lock:
            return build(self.items, now)

    def _loop(self):
        while True:
            try:
                self.refresh()
            except Exception:
                pass
            time.sleep(self.period)

    def start(self):
        threading.Thread(target=self._loop, daemon=True, name="energia").start()
