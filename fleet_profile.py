"""
Perfil de velocidad APRENDIDO de la flota (por tramo, punto kilométrico y clase de tren).

Detecta, sin boletín oficial de limitaciones, dos cosas:
  * limitaciones probables (LTV virtuales): zonas donde los trenes previos pasan sistemáticamente despacio;
  * desvíos de un tren respecto al comportamiento del grupo que le precedió.

Reglas de seguridad de esta capa:
  * es SOLO asesora (máximo CAUTION): nunca restringe por sí sola ni relaja ningún límite de B2/B3/B4;
  * una limitación inferida se muestra como "probable" con el nº de trenes que la sostienen, no como dato oficial;
  * si el patrón aprendido supera el límite de referencia, se avisa para no normalizar un exceso sistemático.
"""
from __future__ import annotations

import math
from statistics import median

NB_MAX = 30          # como mucho 30 puntos por tramo (≈1 km cada uno)
WINDOW_S = 6 * 3600  # solo cuentan los trenes de las últimas 6 h
MIN_TRAINS = 4       # trenes distintos para considerar que hay "grupo"
SLOW_RATIO = 0.70    # mediana < 70 % del límite de referencia => limitación probable
DEV_FAST = 1.25      # tren > 125 % de la mediana del grupo (y +20 km/h) => desvío al alza
DEV_MIN_ABS = 20
OVER_REF = 1.03      # mediana del grupo > límite de referencia ×1,03 => patrón de exceso


def locate(est, k, ant, sig, x, y):
    """(clave de tramo, bin) del punto (x,y) en km. None si no se puede ubicar."""
    a, b = est.get(ant), est.get(sig)
    if not a or not b or ant == sig:
        return None
    lo, hi = sorted((ant, sig))
    p0, p1 = est[lo], est[hi]
    x0, y0, x1, y1 = p0["x"] * k, p0["y"] * k, p1["x"] * k, p1["y"] * k
    dx, dy = x1 - x0, y1 - y0
    L = math.hypot(dx, dy)
    if L < 0.5:
        return None
    f = max(0.0, min(1.0, ((x - x0) * dx + (y - y0) * dy) / (L * L)))
    nb = max(1, min(NB_MAX, round(L)))
    return (lo, hi), min(nb - 1, int(f * nb)), L


class Profile:
    def __init__(self):
        self.cells: dict[tuple, dict[str, tuple[int, float]]] = {}

    def _alive(self, cell, now_ms, skip=None):
        lim = now_ms - WINDOW_S * 1000
        return {n: v for n, v in cell.items() if v[0] >= lim and n != skip}

    def group(self, key, now_ms, skip=None):
        cell = self.cells.get(key)
        if not cell:
            return []
        return [v[1] for v in self._alive(cell, now_ms, skip).values()]

    def learn(self, key, train, ts, kmh):
        cell = self.cells.setdefault(key, {})
        cell[train] = (ts, kmh)
        if len(cell) > 60:   # acotar memoria: se descartan los más antiguos
            for n, _ in sorted(cell.items(), key=lambda i: i[1][0])[:len(cell) - 40]:
                del cell[n]

    def probable_limits(self, now_ms, ref_of):
        """Zonas donde el grupo pasa sistemáticamente despacio: [{seg, bin, n, median, ref}]."""
        out = []
        for key, cell in self.cells.items():
            sp = [v[1] for v in self._alive(cell, now_ms).values()]
            if len(sp) < MIN_TRAINS:
                continue
            m = median(sp)
            ref = ref_of(key)
            if ref and m < SLOW_RATIO * ref:
                out.append({"seg": list(key[0]), "bin": key[1], "cls": key[2], "n": len(sp),
                            "median": round(m), "ref": round(ref)})
        return out
