"""Noticias ferroviarias de Google Noticias (RSS público). Solo titular, medio, fecha y enlace: no se copia el contenido.

NO es una fuente oficial ni verifica nada: sirve para que el centro de control vea que hay información en medios sobre
incendios, descarrilamientos, cortes o incidencias en la red. Solo informativo.
"""
import json, os, re, threading, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from html import unescape

BASE = "https://news.google.com/rss/search?hl=es&gl=ES&ceid=ES:es&q="
QUERIES = ["(incendio OR humo) (tren OR AVE OR Renfe OR Adif OR vía) when:1d",
           "(descarrilamiento OR accidente ferroviario OR colisión tren) when:1d",
           "(Adif OR Renfe) (incidencia OR corte OR suspendida OR interrumpida OR retrasos) when:1d",
           "(accidente OR colisión OR atropello) (coche OR turismo OR camión OR carretera OR autovía OR \"paso a nivel\" OR DGT) when:1d",
           "(AVE OR Alta Velocidad OR Cercanías OR Rodalies) (incendio OR avería OR corte OR evacuados) when:1d"]
# Feeds RSS públicos y gratuitos de medios: salen antes que Google Noticias (que tiene que indexarlos). Cada uno se prueba por separado
# y el estado de cada feed se ve en /api/noticias → status.feeds; si alguno cambia de dirección o falla, se ignora sin afectar al resto.
FEEDS = [("El País", "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/portada"),
         ("El Mundo", "https://e00-elmundo.uecdn.es/elmundo/rss/espana.xml"),
         ("20minutos", "https://www.20minutos.es/rss/"),
         ("Europa Press", "https://www.europapress.es/rss/rss.aspx"),
         ("La Vanguardia", "https://www.lavanguardia.com/rss/home.xml"),
         ("ABC", "https://www.abc.es/rss/2.0/espana/")]
RAILWORDS = re.compile(r"\b(coche|turismo|cami[oó]n|carretera|autov[ií]a|autopista|dgt|paso a nivel|ave|tren(es)?|renfe|adif|ferroviari\w*|cercan[ií]as|rodalies|v[ií]as?|alta velocidad|locomotora|catenaria|apeadero|estaci[oó]n)\b", re.I)
SEV = [("inc", re.compile(r"incendi|humo|llamas|fuego", re.I)), ("acc", re.compile(r"descarril|colisi|accident|arrolla|herid|muert|fallecid", re.I)),
       ("cor", re.compile(r"cort|interrump|suspend|evacu|sin servicio|paralizad", re.I))]
# Política, obras, crisis y opinión: no son sucesos, se descartan del todo
DROP = re.compile(r"feij[oó]o|s[aá]nchez|puente|ministr|gobierno|\bpp\b|psoe|vox|sumar|oposici|congreso|elecciones|obras de renovaci|crisis|plazas|huelga|billetes|precio", re.I)
KIND = {"inc": "Incendio", "acc": "Accidente", "cor": "Corte o interrupción", "otr": "Incidencia"}
# Una noticia solo es "última hora" si el propio titular lo dice; lo demás es seguimiento o información general
BREAKING = re.compile(r"[uú]ltima hora|en directo|\bahora\b|urgente|en vivo|minuto a minuto|se registra|se produce|se declara", re.I)
FOLLOWUP = re.compile(r"superviviente|hospitalizad|investig|juicio|v[ií]ctimas|homenaje|funeral|duelo|balance|causas?|declara|reclama|critica|acusa|"
                      r"reanud|trabajos|piden|mantienen|maquinistas|sindicat|retrasos?|circulaci[oó]n|restablec|vuelven|dimisi|ministro|oposici|pol[ií]tic|indemniz|recuerd|testimon|muere|falleci|identific|ingresad|heridos? siguen|crisis", re.I)


def _ln(t):
    return t.rsplit("}", 1)[-1]


def _txt(el, *names):
    for c in el:
        if _ln(c.tag) in names:
            if _ln(c.tag) == "link" and not (c.text or "").strip() and c.get("href"):
                return c.get("href").strip()
            return (c.text or "").strip()
    return ""


def _when(s):
    try:
        return parsedate_to_datetime(s).timestamp()
    except Exception:
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
        except Exception:
            return None


def parse(xml_text, source=None):
    """RSS 2.0 o Atom. `source` = nombre del medio cuando el feed no lo indica por noticia (Google Noticias sí lo indica)."""
    out = []
    try:
        root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    except ET.ParseError:
        return out
    for it in root.iter():
        if _ln(it.tag) not in ("item", "entry"):
            continue
        title = unescape(_txt(it, "title"))
        src = _txt(it, "source") or source or ""
        if src and title.endswith(" - " + src):
            title = title[:-(len(src) + 3)]
        if not title or not RAILWORDS.search(title) or DROP.search(title):
            continue
        ts = _when(_txt(it, "pubDate", "published", "updated", "date"))
        if ts is None:
            continue
        k = next((k for k, rx in SEV if rx.search(title)), "otr")
        if k == "otr":
            continue
        lvl = "seg" if FOLLOWUP.search(title) else ("ult" if BREAKING.search(title) else "seg")
        out.append({"t": title, "s": src, "ts": int(ts), "u": _txt(it, "link"), "k": k, "l": lvl})
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
    def __init__(self, cache="data/news_cache.json", opener=None, period=180):
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
        lists, errs, feeds = [], 0, {}
        jobs = [("Google Noticias", BASE + urllib.parse.quote(q), None) for q in QUERIES] + [(n, u, n) for n, u in FEEDS]
        for name, url, src in jobs:
            try:
                got = parse(self.open(url), src)
                lists.append(got)
                f = feeds.setdefault(name, {"ok": 0, "err": 0, "n": 0})
                f["ok"] += 1
                f["n"] += len(got)
            except Exception as ex:
                f = feeds.setdefault(name, {"ok": 0, "err": 0, "n": 0})
                f["err"] += 1
                f["last_error"] = repr(ex)[:80]
                errs += 1
        if errs == len(jobs):
            raise RuntimeError("Ninguna fuente de noticias responde")
        items = merge(lists)
        with self.lock:
            self.items = items
            self.status = {"state": "ok", "fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "n": len(items), "errors": errs, "feeds": feeds}
        print("[noticias] " + " · ".join(f"{k}: {'ok' if v['ok'] else 'ERROR ' + v.get('last_error', '')} ({v['n']})" for k, v in feeds.items()) + f" → {len(items)} titulares", flush=True)
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
                    "source": "Titulares de medios (RSS públicos y Google Noticias). No es un aviso oficial. Solo informativo."}
