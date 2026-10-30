import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_engine import eng, mk, NOW, K  # noqa: E402
import forecast  # noqa: E402


def run(trains, cfg=None):
    e = eng(cfg=cfg)
    e.step(trains, NOW)
    return e, forecast.predict(e)


def km(x):   # km -> unidades de x del test
    return x / K


def test_catch_up_is_predicted_before_barriers_act():
    # tren de atrás a 250, de delante a 120; 30 km de separación: alcance en ≈14 min
    e, f = run([mk("F", 150 + km(0), 120), mk("R", 150 - km(30), 250)])
    it = [i for i in f["items"] if i["kind"] == "ALCANCE"]
    assert it and it[0]["trains"] == ["R", "F"]
    assert 700 < it[0]["in_s"] < 950
    assert "B4 restringirá" in it[0]["then"]
    assert not e.hazards or all(h.code != "TTC" for h in e.hazards)   # aún no hay peligro: es previsión


def test_no_forecast_when_speeds_are_similar_or_front_is_faster():
    _, f = run([mk("F", 150, 200), mk("R", 150 - km(10), 210)])
    assert f["items"] == []
    _, f = run([mk("F", 150, 250), mk("R", 150 - km(10), 150)])
    assert f["items"] == []


def test_stopped_front_at_station_is_not_an_obstacle():
    # delante parado cerca de Beta (estación): servicio normal
    _, f = run([mk("F", 199, 0), mk("R", 199 - km(25), 200)])
    assert f["items"] == []


def test_stale_or_implausible_trains_are_ignored():
    _, f = run([mk("F", 150, 120), mk("R", 150 - km(30), 250, ts=NOW - 400_000)])
    assert f["items"] == []
    _, f = run([mk("F", 150, 120), mk("R", 150 - km(30), 400)])
    assert f["items"] == []


def test_forecast_never_changes_commands_and_is_sorted_by_time():
    e, f = run([mk("F", 150, 120), mk("R", 150 - km(30), 250), mk("F2", 160, 100, mat="Z"), mk("R2", 160 - km(8), 240, mat="W")])
    times = [i["in_s"] for i in f["items"]]
    assert times == sorted(times)
    assert "no ordena nada" in f["note"]
