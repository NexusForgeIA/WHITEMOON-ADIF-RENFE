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


def test_on_segment():
    st = {"A": (0, 0), "B": (10, 0)}
    i = {"c0": "A", "c1": "B"}
    assert ltv.on_segment(i, st, 5, 0.5) is True
    assert ltv.on_segment(i, st, 5, 5) is False
    assert ltv.on_segment({"c0": "A", "c1": "Z"}, st, 5, 0) is None


def test_b2_ltv_otra_via_no_avisa():
    _, e = _run(10, [])
    item = {"id": 1, "line": "200", "kmh": 30, "x": 100 * e.cfg["km_per_px"], "y": 0, "c0": "A", "c1": "B"}
    assert _run(200, [item])[0]
    # mismas estaciones pero el tren circula lejos de ese tramo: no aplica
    item2 = {**item, "y": 0}
    est_lejos = _run(200, [{**item2, "c0": "A", "c1": "B"}], x=100.0)
    assert est_lejos[0]


TR = [{"attributes": {"COD_LINEA": "200 - X", "PKI": 10.0, "PKD": 20.0},
       "geometry": {"paths": [[[-3.0, 40.0], [-3.0, 40.045], [-3.0, 40.09]]]}}]


def test_geometria_de_ltv_desde_tramos():
    tr = ltv.parse_tramos(TR)
    g = ltv.geometry(tr, "200", 12, 14)
    assert g and len(g[0]) >= 2
    (x0, y0), (x1, y1) = g[0][0], g[0][-1]
    assert 1.5 < ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** .5 < 2.5   # ~2 km de 10 PK
    assert ltv.geometry(tr, "999", 12, 14) == [] and ltv.geometry(tr, "200", 30, 31) == []


def test_matching_con_geometria_ignora_el_radio_del_punto():
    tr = ltv.parse_tramos(TR)
    g = ltv.geometry(tr, "200", 10, 20)
    i = {"id": 1, "kmh": 30, "x": g[0][0][0], "y": g[0][0][1], "g": g}
    mx, my = g[0][len(g[0]) // 2]
    assert ltv.matching([i], {}, mx, my) == [i]                 # a mitad del tramo, lejos del punto
    assert ltv.matching([i], {}, mx + 5, my) == []
