import exercise as X


def mk():
    logs = []
    return X.Exercises(log=lambda k, m, **d: logs.append((k, m, d))), logs


def test_full_cycle_grade():
    ex, logs = mk()
    ex.start("a", 1000)
    ex.event({"kind": "HAZARD", "t": 3000})
    ex.event({"kind": "ACK", "t": 23000})
    ex.event({"kind": "CLEAR", "t": 63000})
    v = ex.view(70000)
    assert not v["running"] and v["done"][0]["detect_s"] == 2.0
    assert v["done"][0]["response_s"] == 20.0 and v["done"][0]["grade"] == "Excelente" and v["done"][0]["resolve_s"] == 60.0
    assert logs and logs[0][0] == "EXERCISE"


def test_slow_and_no_response():
    ex, _ = mk()
    ex.start("a", 0); ex.event({"kind": "HAZARD", "t": 0}); ex.event({"kind": "MANUAL", "t": 200000})
    ex.stop("a", 210000)
    assert ex.done[0]["grade"] == "Lento" and ex.done[0]["result"] == "retirado"
    ex.start("b", 0); ex.event({"kind": "HAZARD", "t": 0}); ex.stop("b", 5000)
    assert ex.done[0]["grade"] == "Sin respuesta"


def test_ignores_action_before_detection():
    ex, _ = mk()
    ex.start("a", 0)
    ex.event({"kind": "ACK", "t": 1000})
    assert ex.cur["a"]["resp"] is None
