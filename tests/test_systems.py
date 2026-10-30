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


def test_outages_always_listed_with_who_covers_barrier_fault():
    a = app()
    assert not any(o["sev"] in ("CRIT", "WARN") for o in a.snapshot()["outages"] if o["id"].startswith("FAULT"))
    a.set_scenario("fallo_barrera", True)
    a.tick()
    o = next(o for o in a.snapshot()["outages"] if o["id"] == "FAULT-B3")
    assert o["sev"] == "CRIT" and "restricción preventiva" in o["applying"].lower()
    assert {c["id"] for c in o["covering"]} == {"B4", "PROX", "SYS", "B5"}


def test_outages_lzb_isolated_shows_system_trains_and_compensation():
    a = app()
    a.set_scenario("atp_aislado", True)
    a.tick()
    a.tick()
    o = next(o for o in a.snapshot()["outages"] if o["id"].startswith("ATP-LZB-ATP_ISOLATED"))
    assert o["sev"] == "CRIT" and "T-9007" in o["trains"] and "LZB" in o["title"]
    assert {c["id"] for c in o["covering"]} == {"B2", "B3", "B4", "B5"}
    a.set_scenario("atp_aislado", False)
    a.tick()
    a.tick()
    assert not any(o["id"].startswith("ATP-LZB") for o in a.snapshot()["outages"])


def test_outages_info_when_no_atp_telemetry_is_not_an_alarm():
    a = server.App()
    for _ in range(3):
        a.tick()
    info = [o for o in a.snapshot()["outages"] if o["id"] == "ATP-NODATA"]
    assert info and info[0]["sev"] == "INFO"
