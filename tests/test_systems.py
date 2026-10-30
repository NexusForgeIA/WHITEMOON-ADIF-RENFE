import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server  # noqa: E402


def app():
    a = server.App()
    for _ in range(4):
        a.tick()
    return a


def test_catalogue_lists_all_layers_with_live_state_and_cover():
    a = app()
    r = a.systems()
    ids = [s["id"] for s in r["systems"]]
    assert ids == ["B0", "B1", "B2", "B3", "B4", "PROX", "B5", "SYS", "B6", "B7"]
    b3 = next(s for s in r["systems"] if s["id"] == "B3")
    assert b3["status"] in ("OK", "ALERT") and b3["params"] and b3["on_failure"]
    assert {c["id"] for c in b3["covering"]} == {"B4", "PROX", "SYS", "B5"}
    assert r["total"] == 10 and 0 < r["healthy"] <= 10


def test_barrier_fault_shows_fault_and_who_covers():
    a = app()
    a.set_scenario("fallo_barrera", True)
    a.tick()
    r = a.systems()
    b3 = next(s for s in r["systems"] if s["id"] == "B3")
    assert b3["status"] == "FAULT" and "fallo inyectado" in b3["detail"]
    assert next(s for s in r["systems"] if s["id"] == "SYS")["status"] == "ALERT"          # el modo degradado responde
    assert any(c["id"] == "B4" and c["healthy"] for c in b3["covering"])


def test_b7_counters_visible_in_catalogue():
    a = app()
    a.engine.degraded = "x"
    a.engine.state["Z"] = {"sev": 3, "since": 0, "clear": 9, "seg": None, "why": set(), "barriers": {"B3"}}
    a.engine.rearm("Z", "op", principal="a")
    b7 = next(s for s in a.systems()["systems"] if s["id"] == "B7")
    assert b7["fired"] == 1 and "1 rechazados" in b7["detail"]
