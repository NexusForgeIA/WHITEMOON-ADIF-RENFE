import redata as R

RESP = lambda vals: {"included": [{"attributes": {"values": [{"value": v, "datetime": f"2026-10-{20 + i}T00:00:00.000+01:00"} for i, v in enumerate(vals)]}}]}


def test_url_geo_params():
    u = R.url("demanda", "evolucion", "2026-10-30T00:00", "2026-11-02T23:59", "day", "canarias")
    assert "geo_limit=canarias&geo_ids=8742" in u and "geo_trunc=electric_system" in u and "demanda/evolucion" in u
    assert "geo_" not in R.url("demanda", "evolucion", "a", "b")


def test_summarize_and_alert():
    s = R.summarize(R.daily_values(RESP([100, 100, 100, 60])))
    assert s["deviation"] == -0.4 and s["mwh"] == 60
    rd = R.RedData(get=lambda u: RESP([100, 100, 100, 60]), cache="/tmp/claude-0/rd_test.json")
    rd.refresh()
    a = rd.alerts()
    assert len(a) == 5 and a[0]["type"] == "red-electrica" and "-40 %" in a[0]["title"]


def test_errors_are_tolerated():
    def bad(u):
        raise OSError("x")
    rd = R.RedData(get=bad, cache="/tmp/claude-0/rd_test2.json")
    rd.refresh()
    assert rd.view()["status"]["state"] == "error" and rd.alerts() == []
