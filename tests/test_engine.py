import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import Engine, STOP, RESTRICT, CAUTION  # noqa: E402

K = 1.2
NOW = 1_800_000_000_000
EST = {"A": {"n": "Alfa", "x": 100, "y": 100}, "B": {"n": "Beta", "x": 200, "y": 100}}


def v(kmh):
    return kmh / 3600 / K


def mk(n, x, kmh, a="A", s="B", des="B", p=2, mat=None, ts=NOW, direction=1, y=100):
    return dict(n=n, p=p, x=x, y=y, kmh=kmh, vx=direction * v(kmh), vy=0, ts=ts, ant=a, sig=s,
                des=des, mat=mat or f"M{n}", ret=0)


def eng(enabled=None, cfg=None):
    return Engine(EST, cfg=cfg, enabled=enabled)


def cmds(e):
    return {t["n"]: t["cmd"] for t in e.snapshot()["trains"]}


def following(gap_km=1.4, rear_kmh=250, front_kmh=120):
    return [mk("F", 150, front_kmh), mk("R", 150 - gap_km / K, rear_kmh)]


def test_safe_spacing_no_hazard():
    e = eng()
    e.step(following(gap_km=20, rear_kmh=120, front_kmh=120), NOW)
    assert e.hazards == [] and e.state == {}


def test_following_too_close_each_barrier_alone_stops_rear():
    for b in ("B3", "B4"):  # independencia: cualquiera de las dos basta
        e = eng(enabled={b})
        e.step(following(), NOW)
        assert cmds(e)["R"] == "STOP", b


def test_overspeed_on_braking_curve():
    e = eng(enabled={"B2"})
    e.step([mk("X", 200 - 2 / K, 300)], NOW)
    assert cmds(e)["X"] == "STOP"


def test_headon_on_single_track():
    e = eng(cfg={"single_track": [["A", "B"]]})
    e.step([mk("E", 140, 80), mk("W", 160, 80, a="B", s="A", des="A", direction=-1)], NOW)
    assert cmds(e)["E"] == "STOP" and cmds(e)["W"] == "STOP"


def test_double_track_opposing_is_not_an_alarm():
    e = eng()
    e.step([mk("E", 140, 80), mk("W", 160, 80, a="B", s="A", des="A", direction=-1)], NOW)
    assert [h for h in e.hazards if h.barrier in ("B3", "B4")] == []


def test_stale_position_restricts():
    e = eng()
    e.step([mk("X", 120, 100, ts=NOW - 200_000), mk("Y", 150, 100)], NOW)
    assert any(h.code == "STALE" for h in e.hazards)
    assert cmds(e)["X"] == "RESTRICT"


def test_gps_jump_detected():
    e = eng()
    e.step([mk("X", 100, 100)], NOW)
    e.step([mk("X", 150, 100, ts=NOW + 10_000)], NOW + 10_000)
    assert any(h.code == "JUMP" for h in e.hazards)


def test_coupled_consist_is_not_duplicate():
    e = eng()
    e.step([mk("1", 130, 150, mat="SAME"), mk("2", 130, 150, mat="SAME")], NOW)
    assert not any(h.code == "DUP_POS" for h in e.hazards)


def test_stop_latches_and_release_needs_proof_and_human():
    e = eng()
    e.step(following(), NOW)
    assert cmds(e)["R"] == "STOP"
    ok, _ = e.rearm("R", "op")
    assert not ok  # la condición sigue activa
    safe = [mk("F", 170, 120), mk("R", 120, 0)]
    for i in range(1, 12):  # 11 ciclos limpios: NO se libera solo
        e.step(safe, NOW + i * 2000)
    assert "R" in e.state and e.state["R"]["sev"] == STOP
    assert e.operator_queue()[0]["can_rearm"] is True
    ok, msg = e.rearm("R", "op", principal="madrid")
    assert not ok and "Primera autorización" in msg and "R" in e.state     # B7: una sola persona no basta
    ok, msg = e.rearm("R", "op2", principal="madrid")
    assert not ok and "R" in e.state                                        # mismo principal: tampoco
    ok, msg = e.rearm("R", "otro", principal="nacional")
    assert ok and "R" not in e.state, msg


def _stop_clear(e):
    e.step(following(), NOW)
    for i in range(1, 6):
        e.step([mk("F", 170, 120), mk("R", 120, 0)], NOW + i * 2000)
    return NOW + 10_000


def test_b7_refuses_rearm_while_supervisor_is_degraded():
    e = eng()
    t = _stop_clear(e)
    e.degraded = "Feed de posiciones perdido: supervisor ciego"
    ok, msg = e.rearm("R", "op", principal="a")
    assert not ok and "degradado" in msg and e.guard["refused"] == 1
    assert any(x["kind"] == "GUARD" for x in e.events)


def test_b7_refuses_rearm_during_real_proximity_conflict():
    e = eng()
    _stop_clear(e)
    e.prox = [{"a": "R", "b": "F", "level": "RED"}]
    ok, msg = e.rearm("R", "op", principal="a")
    assert not ok and "proximidad" in msg


def test_b7_dual_authorization_expires():
    e = eng()
    t = _stop_clear(e)
    e.rearm("R", "op", principal="madrid")
    e.now_ms = t + 400_000
    ok, msg = e.rearm("R", "otro", principal="nacional")     # la primera ya caducó: cuenta como primera
    assert not ok and "Primera autorización" in msg and "R" in e.state


def test_b7_rate_limit_per_principal():
    e = eng()
    e.cfg["rearm_dual"] = False
    for i in range(3):
        e.state["X%d" % i] = {"sev": STOP, "since": 0, "clear": 9, "seg": None, "why": set(), "barriers": set()}
        assert e.rearm("X%d" % i, "op", principal="p")[0]
    e.state["X9"] = {"sev": STOP, "since": 0, "clear": 9, "seg": None, "why": set(), "barriers": set()}
    ok, msg = e.rearm("X9", "op", principal="p")
    assert not ok and "límite" in msg and e.guard["rate_blocked"] == 1


def test_b7_adding_restrictions_is_never_refused():
    e = eng()
    ok, _ = e.manual_restrict("R", "cualquiera")
    assert ok


def test_rearm_rejected_before_proof():
    e = eng()
    e.step(following(), NOW)
    e.step([mk("F", 170, 120), mk("R", 120, 0)], NOW + 2000)  # solo 1 ciclo limpio
    ok, msg = e.rearm("R", "op")
    assert not ok and "vía libre" in msg


def test_restrict_releases_itself():
    e = eng()
    e.step(following(gap_km=1.5, rear_kmh=150, front_kmh=150), NOW)  # necesita 1,95 km; STOP si <0,97 km
    assert cmds(e)["R"] == "RESTRICT"
    for i in range(1, 5):
        e.step([mk("F", 170, 150), mk("R", 120, 150)], NOW + i * 2000)
    assert "R" not in e.state


def test_barrier_fault_fails_closed():
    e = eng()
    e.fault_inject = {"B3"}
    e.step(following(gap_km=20), NOW)
    assert "B3" in e.faults
    assert set(cmds(e).values()) == {"CAUTION"}
    assert any(i["key"] == "fault:B3" for i in e.operator_queue())


def test_blind_feed_degrades_and_escalates():
    e = eng()
    e.step(following(gap_km=20), NOW)
    e.step(None, NOW + 130_000)
    assert e.degraded and "NONE" not in set(cmds(e).values())  # nunca queda un tren sin restricción
    assert any(i["key"] == "sys:blind" for i in e.operator_queue())


def test_manual_restriction_always_accepted_but_cannot_lift_automatic_stop():
    e = eng()
    e.step(following(), NOW)
    assert e.manual_restrict("F", "op")[0]
    e.release_manual("R", "op")
    assert cmds(e)["R"] == "STOP"


def test_operator_not_bothered_by_minor_caution():
    e = eng()
    e.step([mk("X", 120, 168, p=16, des="Z")], NOW)  # 5 % sobre 160 -> CAUTION
    assert cmds(e)["X"] == "CAUTION" and e.operator_queue() == []


def test_operator_sees_only_contained_situations():
    e = eng()
    e.step(following(), NOW)
    item = e.operator_queue()[0]
    assert item["level"] == "CRITICA" and "Freno de emergencia ordenado" in item["auto"]
    assert {"B3", "B4"} <= set(item["barriers"])
