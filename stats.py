"""Histórico de puntualidad por estación y por tren (hoy / 7 días / 30 días) y estado de cada tren (en vivo / finalizado / sin señal).

Solo agrega datos que RailGuard ya lee del feed público de Renfe; no copia datos de terceros. Informativo: no interviene en las barreras.
Una muestra por minuto: cada tren con retraso conocido suma a su ficha y a la de su próxima estación. Se guarda un resumen por día
(muestras, muestras con retraso >= DELAY_MIN, suma y máximo de minutos), no cada muestra, y se conservan KEEP_DAYS días.
"""
import json
import os
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Madrid")
DELAY_MIN = 5        # mismo criterio de «con retraso» que punctuality.DELAY_MIN
KEEP_DAYS = 31
WINDOWS = {"1d": 1, "7d": 7, "30d": 30}
MIN_SAMPLES_ST, MIN_SAMPLES_TR = 30, 20      # mínimo de muestras para entrar en un ranking
GONE_KEEP_S = 6 * 3600                       # cuánto recordamos un tren que ya no está en el feed


def _day(now):
    return datetime.fromtimestamp(now, TZ).strftime("%Y-%m-%d")


class Daily:
    def __init__(self, path=None, every=60, save_every=300):
        self.path, self.every, self.save_every = path, every, save_every
        self.lock = threading.Lock()
        self.days = {}      # día -> {"st": {código: [n, retrasadas, suma, máx]}, "tr": {nº: [n, retrasadas, suma, máx, categoría]}}
        self.names = {}     # código de estación -> nombre
        self._last = self._saved = 0
        try:
            d = json.load(open(path, encoding="utf-8"))
            self.days, self.names = d.get("days", {}), d.get("names", {})
        except Exception:
            pass

    @staticmethod
    def _bump(row, ret):
        row[0] += 1
        row[1] += ret >= DELAY_MIN
        row[2] += ret
        row[3] = max(row[3], ret)

    def add(self, trains, now=None):
        """trains: iterable de (nº, retraso_min, categoría, código_estación_siguiente | None, nombre_estación | None)."""
        now = now or time.time()
        with self.lock:
            if now - self._last < self.every:
                return False
            self._last = now
            d = self.days.setdefault(_day(now), {"st": {}, "tr": {}})
            for n, ret, cat, code, name in trains:
                ret = max(0, int(ret or 0))
                row = d["tr"].setdefault(str(n), [0, 0, 0, 0, cat or ""])
                self._bump(row, ret)
                if code:
                    self._bump(d["st"].setdefault(str(code), [0, 0, 0, 0]), ret)
                    if name:
                        self.names[str(code)] = name
            for old in sorted(self.days)[:-KEEP_DAYS]:
                del self.days[old]
            return True

    def save(self, now=None, force=False):
        now = now or time.time()
        if not self.path or (not force and now - self._saved < self.save_every):
            return False
        with self.lock:
            self._saved = now
            try:
                os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
                tmp = self.path + ".tmp"
                json.dump({"days": self.days, "names": self.names}, open(tmp, "w", encoding="utf-8"), separators=(",", ":"))
                os.replace(tmp, self.path)
            except OSError:
                return False
        return True

    def _keys(self, w, now):
        n = WINDOWS.get(w, 7)
        today = datetime.fromtimestamp(now or time.time(), TZ).date()
        return [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]

    def _sum(self, kind, key, w, now):
        acc = [0, 0, 0, 0]
        used = 0
        for dk in self._keys(w, now):
            r = self.days.get(dk, {}).get(kind, {}).get(key)
            if r:
                used += 1
                acc[0] += r[0]; acc[1] += r[1]; acc[2] += r[2]; acc[3] = max(acc[3], r[3])
        return acc, used

    @staticmethod
    def _out(acc, used):
        n = acc[0]
        return {"samples": n, "days": used, "pct_delayed": round(100 * acc[1] / n, 1) if n else None,
                "mean_min": round(acc[2] / n, 1) if n else None, "max_min": acc[3]}

    def station(self, code, w="7d", now=None):
        with self.lock:
            acc, used = self._sum("st", str(code), w, now)
            return {"code": str(code), "name": self.names.get(str(code)), "window": w if w in WINDOWS else "7d", **self._out(acc, used)}

    def train(self, n, w="7d", now=None):
        with self.lock:
            acc, used = self._sum("tr", str(n), w, now)
            return {"n": str(n), "window": w if w in WINDOWS else "7d", **self._out(acc, used)}

    def top(self, w="7d", limit=8, now=None):
        """Estaciones y trenes con mayor % de muestras con retraso (con un mínimo de muestras para no premiar el ruido)."""
        with self.lock:
            def rank(kind, minn, label):
                keys = {k for dk in self._keys(w, now) for k in self.days.get(dk, {}).get(kind, {})}
                out = []
                for k in keys:
                    acc, used = self._sum(kind, k, w, now)
                    if acc[0] >= minn:
                        out.append({"id": k, "label": label(k), **self._out(acc, used)})
                out.sort(key=lambda r: (-r["mean_min"], -r["pct_delayed"]))
                return out[:limit]
            return {"window": w if w in WINDOWS else "7d",
                    "stations": rank("st", MIN_SAMPLES_ST, lambda k: self.names.get(k, k)),
                    "trains": rank("tr", MIN_SAMPLES_TR, lambda k: k)}


class TrainBook:
    """Recuerda los trenes vistos. Estado: live (en el feed), finished (desapareció con la siguiente parada = destino),
    lost (desapareció antes de llegar: puede ser fin de servicio o pérdida de señal del feed) o not_found (nunca visto o muy antiguo)."""
    def __init__(self):
        self.lock = threading.Lock()
        self.live, self.gone = {}, {}

    def update(self, trains, now=None):
        """trains: iterable de dicts con n, from, to, dest, ret, finishing (bool: la siguiente parada es el destino)."""
        now = now or time.time()
        with self.lock:
            cur = {}
            for t in trains:
                cur[str(t["n"])] = {**t, "last_seen": now}
            for n, t in self.live.items():
                if n not in cur:
                    self.gone[n] = {**t, "gone_at": now}
            for n in cur:
                self.gone.pop(n, None)
            self.live = cur
            for n in [n for n, t in self.gone.items() if now - t["gone_at"] > GONE_KEEP_S]:
                del self.gone[n]

    def status(self, n, now=None):
        now = now or time.time()
        n = str(n)
        with self.lock:
            if n in self.live:
                return {"n": n, "status": "live"}
            g = self.gone.get(n)
            if not g:
                return {"n": n, "status": "not_found"}
            return {"n": n, "status": "finished" if g.get("finishing") else "lost", "gone_min": max(0, int((now - g["gone_at"]) // 60)),
                    "from": g.get("from"), "to": g.get("to"), "dest": g.get("dest"), "ret_min": g.get("ret")}
