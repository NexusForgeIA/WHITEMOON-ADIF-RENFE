"""Perfil de velocidad máxima por punto kilométrico (PK) de la LAV Madrid–Sevilla, SOLO zonas lentas.

Fuente: FCMAF (fcmaf.es, divulgativa, NO oficial de Adif) en data/fcmaf_lineas.json; PK de Córdoba y Sevilla de un texto
sin fuente aportado por el usuario (sin verificar). Por eso:
- Solo se usan zonas ≤ 200 km/h (las de 270-300 pueden estar desactualizadas y darían falsos avisos a trenes que hoy circulan a 300).
- La posición del tren se convierte a PK interpolando entre estaciones ancla; se exige estar cerca del eje y se estrecha cada zona
  por `TOL_KM` en cada extremo para absorber el error de esa conversión.
- La barrera B2 nunca pasa de CAUTION cuando el límite sale de este perfil.
"""
import json
import math
import os

ANCHORS = [("60000", 0.0), ("37200", 170.747), ("37300", 209.762), ("50500", 343.0), ("51003", 471.8)]
MAX_OFF_KM = 3.0   # distancia máxima al eje para considerar que el tren está en la línea
TOL_KM = 1.0
SLOW_KMH = 200
_zones = None


def zones():
    global _zones
    if _zones is None:
        try:
            d = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "fcmaf_lineas.json"), encoding="utf-8"))
            z = []
            for s in d["lineas"]["010"]["velocidades_max_kmh"]:
                v = s["v"]
                if isinstance(v, str):
                    v = 200  # «70-200»: se usa la cota superior (el 70 solo rige en la propia estación)
                if v <= SLOW_KMH:
                    z.append((s["pk_desde"], s["pk_hasta"], v))
            _zones = z
        except Exception:
            _zones = []
    return _zones


def pk_of(st, x, y):
    """(PK, distancia al eje en km) interpolando entre las estaciones ancla presentes en `st`; None si no hay eje."""
    pts = [(st[c], pk) for c, pk in ANCHORS if c in st]
    if len(pts) < 2:
        return None
    best = None
    for ((ax, ay), apk), ((bx, by), bpk) in zip(pts, pts[1:]):
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        if L2 <= 0:
            continue
        f = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / L2))
        off = math.hypot(x - (ax + f * dx), y - (ay + f * dy))
        if best is None or off < best[1]:
            best = (apk + f * (bpk - apk), off)
    return best


def slow_limit(st, x, y):
    """Límite (km/h, PK) si el punto cae dentro de una zona lenta (estrechada); si no, None."""
    r = pk_of(st, x, y)
    if not r or r[1] > MAX_OFF_KM:
        return None
    pk = r[0]
    for lo, hi, v in zones():
        if lo + TOL_KM <= pk <= hi - TOL_KM:
            return v, pk
    return None
