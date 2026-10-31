"""Puntualidad de la red: KPIs calculados con el feed de Renfe que ya usa RailGuard (no se copian datos de terceros).

Umbrales de indemnización: «Compromiso de puntualidad» de Renfe (renfe.com, consultado 30/10/2026). Se aplican al retraso ACTUAL del tren
como aproximación: la indemnización real depende del retraso a la llegada. Informativo; no interviene en ninguna barrera de seguridad.
"""
import json
import os
import threading
import time
from collections import deque
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Madrid")
DELAY_MIN = 5   # umbral de «con retraso» (criterio habitual de puntualidad)
# categoría -> minutos de retraso a partir de los cuales hay indemnización (Renfe: «60 min o más» en AVE/LD; «más de» en el resto)
INDEM_MIN = {"AVE": 60, "AVLO": 60, "LD": 60, "AVANT": 16, "MD": 16, "REG": 31}
LABEL = {"AVE": "AVE", "AVLO": "Avlo", "LD": "Larga Distancia", "AVANT": "Avant", "MD": "Media Distancia", "REG": "Regional", "OTRO": "Otros"}
# Segmentos como en retrasados.es: Alta velocidad = AVE, Avlo y Avant (circulan por línea de alta velocidad); Convencional = el resto de larga/media distancia
SEGMENTS = {"all": None, "av": {"AVE", "AVLO", "AVANT"}, "conv": {"LD", "MD", "REG", "OTRO"}}
SEG_LABEL = {"all": "Toda la red (sin Cercanías)", "av": "Alta velocidad", "conv": "Convencional", "cer": "Cercanías"}
BUCKETS = [(0, 5, "< 5 min"), (5, 15, "5–15"), (15, 30, "15–30"), (30, 60, "30–60"), (60, 90, "60–90"), (90, 10 ** 6, "> 90")]


def category(rname):
    t = (rname or "").upper().replace(".", " ")
    toks = set(t.replace("-", " ").split())
    for key, cat in (("AVLO", "AVLO"), ("AVE", "AVE"), ("AVANT", "AVANT"), ("ALVIA", "LD"), ("EUROMED", "LD"), ("INTERCITY", "LD"),
                     ("ALTARIA", "LD"), ("TALGO", "LD"), ("TRENHOTEL", "LD"), ("REGIONAL", "REG"), ("EXPRES", "REG"), ("MD", "MD")):
        if key in toks:
            return cat
    return "OTRO"


def compute(rows, seg="all"):
    """rows: iterable de (nº tren, retraso en min, categoría). Una fila por vehículo del feed, igual que el contador de trenes."""
    cats = SEGMENTS.get(seg)
    L = [(n, max(0, int(ret or 0)), cat or "OTRO") for n, ret, cat in rows if cats is None or (cat or "OTRO") in cats]   # mismo recuento que la barra superior (un registro por vehículo)
    N = len(L)
    delayed = [r for r in L if r[1] >= DELAY_MIN]
    indem = [r for r in L if INDEM_MIN.get(r[2]) and r[1] >= INDEM_MIN[r[2]]]
    total = sum(r[1] for r in L)
    prod = {}
    for _, ret, cat in L:
        p = prod.setdefault(cat, {"cat": cat, "label": LABEL.get(cat, cat), "n": 0, "delayed": 0})
        p["n"] += 1
        p["delayed"] += ret >= DELAY_MIN
    return {"n": N, "delayed": len(delayed), "pct_delayed": round(100 * len(delayed) / N, 1) if N else 0.0,
            "mean_min": round(total / N, 1) if N else 0.0, "max_min": max((r[1] for r in L), default=0), "sum_min": total,
            "indem": len(indem), "pct_indem": round(100 * len(indem) / N, 1) if N else 0.0,
            "on_time": N - len(delayed), "pct_on_time": round(100 * (N - len(delayed)) / N, 1) if N else 0.0,
            "median_min": sorted(r[1] for r in L)[N // 2] if N else 0,
            "worst": [{"n": r[0], "min": r[1], "cat": r[2], "label": LABEL.get(r[2], r[2])} for r in sorted(L, key=lambda r: -r[1])[:6] if r[1] >= DELAY_MIN],
            "by_product": sorted(prod.values(), key=lambda p: -p["n"]),
            "buckets": [{"label": lb, "n": sum(1 for r in L if lo <= r[1] < hi)} for lo, hi, lb in BUCKETS],
            "thresholds": {LABEL[k]: v for k, v in INDEM_MIN.items()}, "seg": seg, "seg_label": SEG_LABEL.get(seg, seg)}


class History:
    """Serie del día (una muestra por minuto) en memoria y en disco; al cambiar el día (hora de Madrid) se reinicia."""
    def __init__(self, path=None, every=60):
        self.path, self.every, self.lock = path, every, threading.Lock()
        self.day, self.pts, self._last = None, deque(maxlen=1500), 0
        try:
            d = json.load(open(path, encoding="utf-8"))
            if d.get("day") == self._today():
                self.day, self.pts = d["day"], deque(d["pts"], maxlen=1500)
        except Exception:
            pass

    @staticmethod
    def _today(now=None):
        return datetime.fromtimestamp(now or time.time(), TZ).strftime("%Y-%m-%d")

    def add(self, k, now=None):
        now = now or time.time()
        with self.lock:
            if now - self._last < self.every:
                return False
            if self.day != self._today(now):
                self.day, self.pts = self._today(now), deque(maxlen=1500)
            self._last = now
            self.pts.append([int(now), k["n"], k["mean_min"], k["sum_min"], k["pct_indem"], k["pct_delayed"]])
            if self.path:
                try:
                    os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
                    json.dump({"day": self.day, "pts": list(self.pts)}, open(self.path, "w"), separators=(",", ":"))
                except OSError:
                    pass
            return True

    def series(self):
        with self.lock:
            return {"day": self.day, "cols": ["t", "n", "mean_min", "sum_min", "pct_indem", "pct_delayed"], "pts": list(self.pts)}
