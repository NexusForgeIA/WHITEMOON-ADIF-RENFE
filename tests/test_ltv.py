import ltv

F = [{"attributes": {"CODLINEA": 200, "PKINI": 1, "PKFIN": 2, "RESTRICCIONVELOCIDAD": 30, "VIAS": "U", "DESCPSINI": "A", "DESCPSFIN": "", "LTVID": 1}, "geometry": {"x": -3.7, "y": 40.4}},
     {"attributes": {"RESTRICCIONVELOCIDAD": None}, "geometry": {"x": -3.7, "y": 40.4}},
     {"attributes": {"RESTRICCIONVELOCIDAD": 50}, "geometry": {"x": 99, "y": 0}}]


def test_parse_descarta_invalidos():
    r = ltv.parse(F)
    assert len(r) == 1 and r[0]["kmh"] == 30 and r[0]["line"] == "200"


def test_near():
    r = ltv.parse(F)
    assert ltv.near(r, r[0]["x"] + 1, r[0]["y"]) and not ltv.near(r, r[0]["x"] + 10, r[0]["y"])


def test_refresh_y_cache(tmp_path):
    c = tmp_path / "c.json"
    L = ltv.Ltv(str(c), opener=lambda p: {"features": F})
    L.refresh()
    assert L.api()["ready"] and L.status["state"] == "oficial"
    assert ltv.Ltv(str(c), opener=lambda p: {}).items == L.items


def test_error_conserva_cache(tmp_path):
    c = tmp_path / "c.json"
    L = ltv.Ltv(str(c), opener=lambda p: {"error": {"code": 500}})
    try:
        L.refresh(); assert False
    except RuntimeError:
        pass


def _run(kmh, ltv_items, x=100.0, cfg=None):
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from test_engine import NOW, mk, Engine
    est = {"A": {"n": "A", "x": 0, "y": 0}, "B": {"n": "B", "x": 200, "y": 0}}
    e = Engine(est, cfg={"ltv_items": ltv_items, **(cfg or {})}, enabled={"B2"})
    for c in range(4):
        t = mk("X", x, kmh, a="A", s="B", des="B", y=0)
        t["product"] = "AVE"
        e.step([t], NOW + c * 1000)
    return [h for h in e.hazards if h.code == "OVERSPEED"], e


def test_b2_aviso_ltv_solo_caution():
    _, e = _run(10, [])
    k = e.cfg["km_per_px"]
    item = {"id": 1, "line": "200", "pk0": 1, "pk1": 2, "kmh": 30, "x": 100 * k, "y": 0}
    hz, _ = _run(200, [item])
    assert hz and all(h.sev == 1 for h in hz) and "LTV" in hz[0].msg


def test_b2_ltv_lejos_o_dentro_de_margen_no_avisa():
    _, e = _run(10, [])
    k = e.cfg["km_per_px"]
    lejos = {"id": 1, "line": "200", "kmh": 30, "x": 100 * k + 50, "y": 0}
    cerca = {"id": 2, "line": "200", "kmh": 30, "x": 100 * k, "y": 0}
    assert _run(200, [lejos])[0] == []
    assert _run(35, [cerca])[0] == []
