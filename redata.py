"""Cliente de la API REData de Red Eléctrica (https://www.ree.es/es/datos/apidatos) y resumen por sistema eléctrico.

Formato: GET https://apidatos.ree.es/{lang}/datos/{categoría}/{widget}?start_date&end_date&time_trunc[&geo_trunc=electric_system&geo_limit&geo_ids]
Para pedir una región hay que enviar los tres parámetros geo_*. Gratuita y sin clave; solo GET. Fuente: Red Eléctrica (REData).

LÍMITE VERIFICADO (2 nov 2026): los sistemas no peninsulares (Canarias, Baleares, Ceuta, Melilla) solo publican datos DIARIOS con retraso de
horas o días y sin desglose por isla; la demanda en tiempo real y por horas solo existe para la península. Por eso un apagón de una isla
NO se ve aquí a tiempo: para eso están los titulares de medios (energia.py). Aquí se ve el sistema entero con retraso (p. ej. «ayer»).
"""
import json
import os
import threading
import time
import urllib.request
from datetime import datetime, timedelta

BASE = "https://apidatos.ree.es/es/datos/"
GEO = {"peninsular": 8741, "canarias": 8742, "baleares": 8743, "ceuta": 8744, "melilla": 8745}
NAMES = {"peninsular": "Península", "canarias": "Canarias", "baleares": "Baleares", "ceuta": "Ceuta", "melilla": "Melilla"}
# Catálogo de widgets de la API (según la documentación oficial)
CATALOG = {
    "balance": ["balance-electrico"],
    "demanda": ["evolucion", "variacion-componentes", "variacion-componentes-movil", "ire-general", "ire-general-anual", "ire-general-movil",
                "ire-industria", "ire-servicios", "ire-otras", "demanda-maxima-diaria", "demanda-maxima-horaria", "perdidas-transporte",
                "potencia-maxima-instantanea", "variacion-demanda", "demanda-tiempo-real"],
    "generacion": ["estructura-generacion", "evolucion-renovable-no-renovable", "estructura-renovables", "estructura-generacion-emisiones-asociadas",
                   "evolucion-estructura-generacion-emisiones-asociadas", "no-renovables-detalle-emisiones-CO2", "maxima-renovable", "potencia-instalada"],
    "intercambios": ["francia-frontera", "portugal-frontera", "marruecos-frontera", "andorra-frontera", "enlace-baleares", "todas-fronteras-fisicos"],
    "transporte": ["energia-no-suministrada-ens", "indice-indisponibilidad", "tiempo-interrupcion-medio-tim", "kilometros-lineas", "indice-disponibilidad",
                   "numero-cortes", "ens-tim", "indice-disponibilidad-total"],
    "mercados": ["componentes-precio-energia-cierre-desglose", "energia-gestionada-servicios-ajuste", "precios-mercados-tiempo-real"],
}


def _get(url, timeout=25):
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "RailGuard/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def url(category, widget, start, end, trunc="day", system=None):
    q = f"?start_date={start}&end_date={end}&time_trunc={trunc}"
    if system:
        q += f"&geo_trunc=electric_system&geo_limit={system}&geo_ids={GEO[system]}"
    return BASE + f"{category}/{widget}" + q


def daily_values(data):
    """Primera serie de un widget → [(datetime_iso, valor)]; vacía si la API devolvió un error."""
    inc = (data or {}).get("included") or []
    vals = ((inc[0].get("attributes") or {}).get("values") or []) if inc else []
    return [(v["datetime"], v["value"]) for v in vals if v.get("value") is not None]


def summarize(vals):
    """vals: demanda diaria (MWh) ordenada. Último día con dato frente a la media de los anteriores."""
    if not vals:
        return None
    last_dt, last = vals[-1]
    prev = [v for _, v in vals[:-1]]
    mean = sum(prev) / len(prev) if prev else None
    return {"date": last_dt[:10], "mwh": round(last), "mean_prev": round(mean) if mean else None,
            "deviation": round((last - mean) / mean, 3) if mean else None}


class RedData:
    def __init__(self, get=_get, cache="data/redata_cache.json", period=1800, now=time.time):
        self.get, self.cache, self.period, self.now = get, cache, period, now
        self.systems, self.status, self.lock = {}, {"state": "pendiente"}, threading.Lock()
        try:
            d = json.load(open(cache, encoding="utf-8"))
            self.systems, self.status = d["systems"], {"state": "caché", "fetched": d.get("fetched")}
        except Exception:
            pass

    def refresh(self):
        today = datetime.fromtimestamp(self.now())
        start, end = (today - timedelta(days=8)).strftime("%Y-%m-%dT00:00"), today.strftime("%Y-%m-%dT23:59")
        out, errs = {}, {}
        for sys_ in GEO:
            try:
                s = summarize(daily_values(self.get(url("demanda", "evolucion", start, end, "day", sys_))))
                if s:
                    out[sys_] = {"name": NAMES[sys_], **s}
                else:
                    errs[sys_] = "sin datos"
            except Exception as ex:
                errs[sys_] = str(ex)[:80]
        with self.lock:
            if out:
                self.systems = out
            self.status = {"state": "ok" if out else "error", "fetched": int(self.now() * 1000), "errors": errs}
        try:
            os.makedirs(os.path.dirname(self.cache) or ".", exist_ok=True)
            json.dump({"systems": self.systems, "fetched": self.status.get("fetched")}, open(self.cache, "w", encoding="utf-8"))
        except OSError:
            pass

    def view(self):
        with self.lock:
            return {"systems": self.systems, "status": self.status, "catalog": CATALOG,
                    "source": "Red Eléctrica de España · REData (apidatos.ree.es). Demanda diaria en MWh; Canarias, Baleares, Ceuta y Melilla solo con datos diarios."}

    def alerts(self, drop=-0.25):
        """Un sistema cuyo último día publicado cae mucho frente a su media reciente (con el retraso de publicación)."""
        out = []
        with self.lock:
            for k, s in self.systems.items():
                if s.get("deviation") is not None and s["deviation"] <= drop:
                    out.append({"id": "redata-" + k, "type": "red-electrica", "sev": "alta", "trains": [], "lat": None, "lon": None,
                                "title": f"Demanda de {s['name']} {round(s['deviation'] * 100)} % el {s['date']}",
                                "detail": f"{s['mwh']:,} MWh frente a ~{s['mean_prev']:,} MWh de media de los días previos (Red Eléctrica, dato diario con retraso)".replace(",", ".")})
        return out

    def _loop(self):
        while True:
            try:
                self.refresh()
            except Exception:
                pass
            time.sleep(self.period)

    def start(self):
        threading.Thread(target=self._loop, daemon=True, name="redata").start()
