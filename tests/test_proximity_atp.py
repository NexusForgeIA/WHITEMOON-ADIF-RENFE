import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server  # noqa: E402
from engine import Engine, RESTRICT  # noqa: E402
from tests.test_engine import mk, NOW, K  # noqa: E402

EST = {"A": {"n": "Alfa", "x": 100, "y": 100}, "B": {"n": "Beta", "x": 400, "y": 100},
       "C": {"n": "Ce", "x": 400, "y": 130}}


def eng(**cfg):
    return Engine(EST, cfg={"single_track": [["A", "C"]], **cfg}, enabled={"B1"})


def run(e, raws, tablets=None, now=NOW):
    e.step(raws, now)
    e.proximity_update(tablets or {}, now)
    return {p["key"]: p for p in e.prox}


def levels(e):
    return {k: p["level"] for k, p in {p["key"]: p for p in e.prox}.items()}


def test_same_segment_same_direction_under_3km_is_red():
    e = eng()
    r = run(e, [mk("F", 150, 160), mk("R", 150 - 2.5 / K, 160)])
    assert r["F|R"]["level"] == "RED" and r["F|R"]["reason"] == "mismo tramo y sentido"
    assert abs(r["F|R"]["dist_km"] - 2.5) < 0.01


def test_just_over_3km_not_red_but_in_hysteresis_band_stays_amber():
    e = eng()
    assert run(e, [mk("F", 150, 160), mk("R", 150 - 3.2 / K, 160)])["F|R"]["level"] == "AMBER"


def test_hysteresis_holds_red_until_33km():
    e = eng()
    run(e, [mk("F", 150, 160), mk("R", 150 - 2.9 / K, 160)])
    assert levels(e)["F|R"] == "RED"
    run(e, [mk("F", 150, 160), mk("R", 150 - 3.2 / K, 160)], now=NOW + 1000)
    assert levels(e)["F|R"] == "RED"          # 3,2 km: dentro de la banda, sigue rojo
    run(e, [mk("F", 150, 160), mk("R", 150 - 3.6 / K, 160)], now=NOW + 2000)
    assert "F|R" not in levels(e)              # fuera de banda: sale del conjunto
    run(e, [mk("F", 150, 160), mk("R", 150 - 3.6 / K, 160)], now=NOW + 9000)
    assert "F|R" not in e.prox_state           # y el estado se limpia pasado el 'hold'


def test_double_track_crossing_is_amber_not_red():
    """Cruce en vía doble (sentidos opuestos, distinto sentido de segmento): no debe sonar la sirena."""
    e = eng()
    r = run(e, [mk("P", 150, 160, direction=1), mk("Q", 150 + 2 / K, 160, a="B", s="A", direction=-1)])
    assert r["P|Q"]["level"] == "AMBER"


def test_single_track_head_on_is_red():
    e = eng()
    r = run(e, [mk("P", 150, 90, a="A", s="C", direction=1), mk("Q", 150 + 2 / K, 90, a="C", s="A", direction=-1)])
    assert r["P|Q"]["level"] == "RED" and r["P|Q"]["reason"] == "vía única"


def test_strict_mode_makes_every_close_pair_red():
    e = eng(proximity_mode="strict")
    r = run(e, [mk("P", 150, 160, direction=1), mk("Q", 150 + 2 / K, 160, a="B", s="A", direction=-1)])
    assert r["P|Q"]["level"] == "RED"


def test_coupled_or_stopped_pairs_ignored():
    e = eng()
    assert run(e, [mk("P", 150, 0, mat="X1"), mk("Q", 150.5, 0, mat="X2")]) == {}
    assert run(e, [mk("P", 150, 80, mat="Z"), mk("Q", 150.5, 80, mat="Z")]) == {}


def test_tablet_gps_overrides_feed_when_fresh_and_not_when_stale():
    e = eng()
    raws = [mk("F", 150, 160), mk("R", 150 - 5 / K, 160)]       # feed: 5 km -> no alerta
    tab = {"R": {"x": 150 * K - 2.0, "y": 100 * K, "ts": NOW, "acc": 5}}   # la tablet de R dice 2 km (en km)
    r = run(e, raws, tab)
    assert r["F|R"]["level"] == "RED" and {r["F|R"]["src_a"], r["F|R"]["src_b"]} == {"feed", "tablet"}
    tab["R"]["ts"] = NOW - 60_000                                # tablet caducada: vuelve al feed
    e2 = eng()
    assert run(e2, raws, tab) == {}


def test_atp_isolated_on_atp_required_line_restricts_and_escalates():
    e = eng()
    e.set_lines([{"id": "L", "name": "L", "stations": ["A", "B"], "signalling": "LZB", "atp_required": True, "verified": False}])
    e.enabled = {"B0"}
    e.set_atp("X", {"system": "LZB", "mode": "IS", "protected": False, "intervention": False}, NOW)
    e.step([mk("X", 200, 200)], NOW)
    h = [h for h in e.hazards if h.code == "ATP_ISOLATED"]
    assert h and h[0].sev == RESTRICT and "exige ATP" in h[0].msg
    assert any(q["title"].startswith("ATP") for q in e.operator_queue())


def test_atp_discrepancy_and_stale_telemetry():
    e = eng()
    e.enabled = {"B0"}
    e.set_atp("X", {"system": "ETCS", "mode": "FS", "protected": True, "intervention": False, "supervised_kmh": 150}, NOW)
    e.step([mk("X", 200, 240)], NOW)
    assert any(h.code == "ATP_DISCREPANCY" for h in e.hazards)
    e.step([mk("X", 200, 240, ts=NOW + 60_000)], NOW + 60_000)       # telemetría de hace 60 s
    assert any(h.code == "ATP_STALE" for h in e.hazards) and not any(h.code == "ATP_DISCREPANCY" for h in e.hazards)


def test_atp_without_telemetry_is_not_a_hazard():
    e = eng()
    e.enabled = {"B0"}
    e.step([mk("X", 200, 240)], NOW)
    assert e.hazards == [] and e.snapshot()["barriers"][0]["status"] == "NODATA"


# ---- canal de cabina ----
def app_with_convoy():
    a = server.App()
    a.tick()
    a.set_scenario("convoy_3km", True)
    a.tick()
    return a


def test_tablet_requires_valid_token_and_throttles_guessing():
    a = server.App()
    assert a.auth_tablet("nope", "1.2.3.4")[0] is None
    assert a.auth_tablet("demo-03123", "1.2.3.4")[0]["train"] == "03123"
    for _ in range(25):
        a.auth_tablet("x", "9.9.9.9")
    assert a.auth_tablet("demo-03123", "9.9.9.9")[1] == "demasiados intentos"


def test_convoy_alert_reaches_both_tablets_and_tracks_ack():
    a = app_with_convoy()
    ra, _ = a.auth_tablet("demo-T-9009", "ip")
    rb, _ = a.auth_tablet("demo-T-9010", "ip")
    a.tablet_pos(ra, {"demo": True})
    a.tablet_pos(rb, {"demo": True})
    a.prox_tick()
    code, sa = a.tablet_pos(ra, {"demo": True})
    _, sb = a.tablet_pos(rb, {"demo": True})
    assert code == 200 and len(sa["alerts"]) == 1 and len(sb["alerts"]) == 1
    assert 2.0 < sa["alerts"][0]["dist_km"] < 3.0 and sa["alerts"][0]["other"] == "T-9010"
    assert sa["alerts"][0]["acked"] is False
    # privacidad: la respuesta no contiene identidad del otro maquinista ni de tablets ajenas
    assert "demo-T-9010" not in str(sa)
    key = sa["alerts"][0]["key"]
    a.tablet_ack(ra, key)
    _, sa2 = a.tablet_pos(ra, {"demo": True})
    _, sb2 = a.tablet_pos(rb, {"demo": True})
    assert sa2["alerts"][0]["acked"] is True and sb2["alerts"][0]["acked"] is False
    q = [i for i in a.snapshot()["operator"] if i["key"].startswith("prox:")]
    assert q and "enterado" in q[0]["auto"][1] and "entregada" in q[0]["auto"][1]


def test_alert_without_tablet_channel_escalates_to_operator():
    a = app_with_convoy()
    a.prox_tick()
    item = next(i for i in a.snapshot()["operator"] if i["key"].startswith("prox:"))
    assert "sin canal de cabina" in item["auto"][1] and item["level"] == "AVISO"
    for d in a.deliv.values():
        d["sent"] -= 30_000           # 30 s sin canal ni enterado
    item = next(i for i in a.snapshot()["operator"] if i["key"].startswith("prox:"))
    assert item["level"] == "CRITICA" and "GSM-R" in item["action"]


def test_real_gps_validation():
    a = server.App()
    a.tick()
    rec, _ = a.auth_tablet("demo-03123", "ip")
    assert a.tablet_pos(rec, {"lat": 0, "lon": 0})[0] == 400
    assert a.tablet_pos(rec, {"lat": "x", "lon": 1})[0] == 400
    code, out = a.tablet_pos(rec, {"lat": 28.1, "lon": -15.4, "acc": 8})   # Canarias: lejos del tren
    assert code == 200 and out["warn"] and "03123" not in a.tablets


def test_token_issue_requires_admin_token_and_stores_only_hash(tmp_path):
    a = server.App()
    a.token = None
    assert a.post("/api/driver/issue", {"id": "m1", "operator": "iryo", "train": "9001"})[0] == 403
    a.token = "adm"
    a.drivers.path = str(tmp_path / "d.json")
    code, out = a.post("/api/driver/issue", {"id": "m1", "operator": "iryo", "train": "9001"})
    tok = out["token"]
    assert a.auth_tablet(tok, "ip")[0]["train"] == "9001"
    assert tok not in open(a.drivers.path).read()
    a.post("/api/driver/revoke", {"id": "m1"})
    assert a.auth_tablet(tok, "ip")[0] is None


def test_tablet_only_train_enters_the_system_and_triggers_alert():
    """Operador sin feed público (p. ej. Iryo): su tren existe solo por la tablet y también protege/está protegido."""
    import math
    a = server.App()
    a.tick()
    a.drivers.add_demo("tk-iryo", {"id": "m-iryo", "operator": "iryo", "train": "IRYO-1"})
    ref = next(t for t in a.engine.trains if t.n == "03123")        # tren real de la captura, rumbo ENE
    ux, uy = ref.vx / math.hypot(ref.vx, ref.vy), ref.vy / math.hypot(ref.vx, ref.vy)
    x, y = ref.x + ux * 2.0, ref.y + uy * 2.0                     # 2 km por delante, misma alineación
    lat, lon = server.LAT_N - y / server.KM_LAT, x / server.KM_LON + server.LON_W
    hdg = math.degrees(math.atan2(ux, -uy)) % 360
    rec, _ = a.auth_tablet("tk-iryo", "ip")
    code, out = a.tablet_pos(rec, {"lat": lat, "lon": lon, "acc": 6, "spd": 40.0, "hdg": hdg})
    assert code == 200
    a.prox_tick()
    _, out = a.tablet_pos(rec, {"lat": lat, "lon": lon, "acc": 6, "spd": 40.0, "hdg": hdg})
    assert out["alerts"] and out["alerts"][0]["other"] == "03123"
    assert out["alerts"][0]["reason"].startswith("misma alineación")
    snap = a.snapshot()
    t = next(t for t in snap["trains"] if t["n"] == "IRYO-1")
    assert t["op"] == "iryo" and t["src"] == "tablet"
    a.tick()                                                         # el ciclo del feed lo conserva
    assert any(t.n == "IRYO-1" for t in a.engine.trains)
    for tb in a.tablets.values():
        tb["ts"] -= 60_000                                           # la tablet calla: el tren sale del sistema
    a.tick()
    assert not any(t.n == "IRYO-1" for t in a.engine.trains)


def test_operator_registry_matches_official_list():
    a = server.App()
    names = " ".join(o["name"] for o in a.operators)
    for needed in ("Renfe Viajeros", "Ouigo", "Iryo", "Euskotren", "FGC", "Alsa Ferrocarril", "Arriva", "Renfe Mercancías", "Medway", "TRAMESA"):
        assert needed in names, needed
    assert len({o["id"] for o in a.operators}) == len(a.operators)
