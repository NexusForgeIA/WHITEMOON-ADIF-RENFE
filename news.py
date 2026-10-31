"""Noticias ferroviarias de Google Noticias (RSS público). Solo titular, medio, fecha y enlace: no se copia el contenido.

NO es una fuente oficial ni verifica nada: sirve para que el centro de control vea que hay información en medios sobre
incendios, descarrilamientos, cortes o incidencias en la red. Solo informativo.
"""
import json, os, re, threading, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from html import unescape

BASE = "https://news.google.com/rss/search?hl=es&gl=ES&ceid=ES:es&q="
QUERIES = ["(incendio OR humo) (tren OR AVE OR Renfe OR Adif OR vía) when:1d",
           "(descarrilamiento OR accidente ferroviario OR colisión tren) when:1d",
           "(Adif OR Renfe) (incidencia OR corte OR suspendida OR interrumpida OR retrasos) when:1d",
           "(AVE OR Alta Velocidad OR Cercanías OR Rodalies) (incendio OR avería OR corte OR evacuados) when:1d"]
RAILWORDS = re.compile(r"\b(ave|tren(es)?|renfe|adif|ferroviari\w*|cercan[ií]as|rodalies|v[ií]as?|alta velocidad|locomotora|catenaria|apeadero|estaci[oó]n)\b", re.I)
SEV = [("inc", re.compile(r"incendi|humo|llamas|fuego", re.I)), ("acc", re.compile(r"descarril|colisi|accident|arrolla|herid|muert|fallecid", re.I)),
       ("cor", re.compile(r"cort|interrump|suspend|evacu|sin servicio|paralizad", re.I))]
KIND = {"inc": "Incendio", "acc": "Accidente", "cor": "Corte o interrupción", "otr": "Incidencia"}


def parse(xml_text):
    out = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    for it in root.iter("item"):
        title = unescape((it.findtext("title") or "").strip())
        src = (it.findtext("source") or "").strip()
        if src and title.endswith(" - " + src):
            title = title[:-(len(src) + 3)]
        if not title or not RAILWORDS.search(title):
            continue
        try:
            ts = parsedate_to_datetime(it.findtext("pubDate")).timestamp()
        except Exception:
            continue
        k = next((k for k, rx in SEV if rx.search(title)), "otr")
        out.append({"t": title, "s": src, "ts": int(ts), "u": (it.findtext("link") or "").strip(), "k": k})
    return out


def merge(lists, now=None, max_age=36 * 3600):
    now = now or time.time()
    seen, res = set(), []
    for it in (i for l in lists for i in l):
        key = re.sub(r"\W+", "", it["t"].lower())[:60]
        if key in seen or now - it["ts"] > max_age:
            continue
        seen.add(key)
        res.append(it)
    return sorted(res, key=lambda i: -i["ts"])[:60]


class News:
    def __init__(self, cache="data/news_cache.json", opener=None, period=600):
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
    def _http(url):
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 RailGuard/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read().decode("utf-8", "replace")

    def refresh(self):
        lists, errs = [], 0
        for q in QUERIES:
            try:
                lists.append(parse(self.open(BASE + urllib.parse.quote(q))))
            except Exception as ex:
                errs += 1
                self.status["last_error"] = repr(ex)[:100]
        if errs == len(QUERIES):
            raise RuntimeError("Google Noticias no responde")
        items = merge(lists)
        with self.lock:
            self.items = items
            self.status = {"state": "ok", "fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "n": len(items), "errors": errs}
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
                self.status = {**self.status, "state": "error" if not self.items else "caché", "error": repr(ex)[:120]}
            time.sleep(self.period)

    def start(self):
        threading.Thread(target=self._loop, daemon=True, name="news").start()

    def api(self):
        with self.lock:
            return {"ready": bool(self.items) or self.status.get("state") == "ok", "status": self.status, "items": self.items, "kinds": KIND,
                    "source": "Google Noticias (titulares de medios; no oficial ni verificado). Solo informativo."}
