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
