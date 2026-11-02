from datetime import datetime
from zoneinfo import ZoneInfo
import hazmap

TZ = ZoneInfo("Europe/Madrid")
T = lambda h: int(datetime(2026, 11, 2, h, 30, tzinfo=TZ).timestamp() * 1000)
NOW = T(23)


def ev(h, sev="STOP", trains=("04929",), kind="HAZARD"):
    return {"e": {"kind": kind, "t": T(h), "sev": sev, "trains": list(trains)}}


def test_buckets_and_peak():
    r = hazmap.hourly([ev(8), ev(8, "RESTRICT"), ev(18, "CAUTION")], 7, NOW)
    assert r["total"] == 3 and r["peak"] == 8
    assert r["hours"][8]["STOP"] == 1 and r["hours"][8]["RESTRICT"] == 1 and r["hours"][18]["CAUTION"] == 1


def test_excludes_synthetic_other_kinds_and_old():
    old = {"e": {"kind": "HAZARD", "t": NOW - 9 * 86400_000, "sev": "STOP", "trains": ["1"]}}
    r = hazmap.hourly([ev(9, trains=("T-9003", "T-9004")), ev(9, kind="ACK"), old], 7, NOW)
    assert r["total"] == 0 and r["peak"] is None
