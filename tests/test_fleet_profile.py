import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_engine import K, NOW, EST, eng, mk, v  # noqa: E402


def run(e, trains, t0):
    e.step(trains, t0)


def seed(e, n_trains=6, kmh=60, x=150):
    """Trenes previos que pasan despacio por el mismo punto del tramo A-B."""
    for i in range(n_trains):
        e.step([mk(f"P{i}", x, kmh, ts=NOW + i * 60_000)], NOW + i * 60_000)


def test_tren_mas_rapido_que_el_grupo_se_avisa_solo_como_caution():
    e = eng(enabled={"BP"})
    seed(e)
    t = NOW + 10 * 60_000
    for c in range(3):  # persistencia de 2 ciclos
        e.step([mk("X", 150, 140, ts=t + c * 1000)], t + c * 1000)
    hz = [h for h in e.hazards if h.code == "FLEET_DEVIATION"]
    assert hz and all(h.sev == 1 for h in hz)  # CAUTION: nunca restringe sola
    assert "X" in hz[0].trains


def test_sin_grupo_suficiente_no_hay_aviso():
    e = eng(enabled={"BP"})
    seed(e, n_trains=2)
    t = NOW + 10 * 60_000
    for c in range(3):
        e.step([mk("X", 150, 140, ts=t + c * 1000)], t + c * 1000)
    assert e.hazards == []


def test_tren_que_va_como_el_grupo_no_se_avisa():
    e = eng(enabled={"BP"})
    seed(e)
    t = NOW + 10 * 60_000
    for c in range(3):
        e.step([mk("X", 150, 62, ts=t + c * 1000)], t + c * 1000)
    assert [h for h in e.hazards if h.code == "FLEET_DEVIATION"] == []


def test_limitacion_probable_se_infiere_y_no_cambia_limites_de_b2():
    e = eng(enabled={"B2", "BP"})
    seed(e, n_trains=6, kmh=60)
    snap = e.snapshot()
    assert snap["learned_limits"] and snap["learned_limits"][0]["median"] == 60
    # B2 sigue usando el límite de referencia (310): un tren a 200 NO es exceso para B2
    e.step([mk("Y", 150, 200, ts=NOW + 20 * 60_000)], NOW + 20 * 60_000)
    assert [h for h in e.hazards if h.barrier == "B2"] == []


def test_patron_sistematico_de_exceso_se_avisa():
    e = eng(enabled={"BP"})
    seed(e, n_trains=6, kmh=330)  # la flota pasa a 330 con referencia 310
    t = NOW + 10 * 60_000
    for c in range(3):
        e.step([mk("Z", 150, 330, ts=t + c * 1000)], t + c * 1000)
    assert any(h.code == "FLEET_OVER_REF" for h in e.hazards)


def test_convergencia_en_estacion_solo_restringe_si_llegan_casi_a_la_vez():
    from engine import Engine
    est = {"A": {"n": "A", "x": 100, "y": 100}, "B": {"n": "B", "x": 200, "y": 100}, "C": {"n": "C", "x": 150, "y": 160}}
    def run(dx):
        e = Engine(est, enabled={"B4"})
        a = mk("A1", 195, 120, a="A", s="B", des="B", mat="MA")
        b = mk("B1", 195 - dx, 120, a="C", s="B", des="B", mat="MB", y=100)
        e.step([a, b], NOW)
        return [h.sev for h in e.hazards if h.code == "CONVERGE"]
    assert run(0.2) == [2]   # ~7 s de diferencia: RESTRICT
    assert run(0.6) == [1]   # ~22 s: solo CAUTION
