import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_engine import NOW, mk, v, Engine  # noqa: E402
import speed_profile as sp  # noqa: E402

# Eje sintético en km (x creciente = hacia el sur): Atocha 0, Ciudad Real 170.747, Puertollano 209.762, Córdoba 343, Sevilla 471.8
EST = {"60000": {"n": "Madrid", "x": 0, "y": 0}, "37200": {"n": "Ciudad Real", "x": 170.747 / 1.2, "y": 0},
       "37300": {"n": "Puertollano", "x": 209.762 / 1.2, "y": 0}, "50500": {"n": "Córdoba", "x": 343 / 1.2, "y": 0},
       "51003": {"n": "Sevilla", "x": 471.8 / 1.2, "y": 0}}


def train(n, pk, kmh):
    t = mk(n, pk / 1.2, kmh, a="37200", s="37300", des="37300", y=0)
    t["product"] = "AVE"
    return t


def run(pk, kmh, cfg=None):
    e = Engine(EST, cfg=cfg, enabled={"B2"})
    for c in range(4):
        e.step([train("X", pk, kmh)], NOW + c * 1000)
    return [h for h in e.hazards if h.code == "OVERSPEED"]


def test_zona_lenta_de_ciudad_real_da_aviso_y_solo_caution():
    hz = run(171.7, 290)
    assert hz and all(h.sev == 1 for h in hz)
    assert "zona lenta" in hz[0].msg and "no oficial" in hz[0].msg


def test_fuera_de_zona_lenta_no_cambia_nada():
    assert run(120.0, 280) == []


def test_extremos_de_zona_se_estrechan_por_tolerancia():
    assert sp.slow_limit({c: (s["x"] * 1.2, 0) for c, s in EST.items()}, 170.4, 0) is None


def test_se_puede_desactivar_por_config():
    assert run(171.7, 290, cfg={"speed_profile": False}) == []


def test_tren_lejos_del_eje_se_ignora():
    st = {c: (s["x"] * 1.2, 0) for c, s in EST.items()}
    assert sp.slow_limit(st, 171.7, 40) is None
