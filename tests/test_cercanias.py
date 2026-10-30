import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cercanias

DOC = {"header": {"timestamp": "1000"}, "entity": [
    {"id": "VP_C3-1", "vehicle": {"position": {"latitude": 37.39, "longitude": -5.97}, "currentStatus": "INCOMING_AT",
     "timestamp": "995", "stopId": "51003", "vehicle": {"id": "1", "label": "C1-23559-PLATF.(6)"}}},
    {"id": "sinpos", "vehicle": {"vehicle": {"id": "2"}}},
    {"id": "fuera", "vehicle": {"position": {"latitude": 0, "longitude": 0}, "vehicle": {"id": "3"}}}]}


def test_parse_filtra_y_limpia_etiqueta():
    tr, hdr = cercanias.parse(DOC, now=1000)
    assert hdr == 1000 and len(tr) == 1
    assert tr[0]["n"] == "C1 23559" and tr[0]["line"] == "C1" and tr[0]["age_s"] == 5


def test_feed_caido_no_lanza_y_se_marca_sin_datos():
    def boom():
        raise OSError("sin red")
    f = cercanias.CercaniasFeed(1.0, opener=boom)
    f.poll()
    s = f.snapshot()
    assert s["ok"] is False and s["trains"] == [] and "sin red" in s["err"]


def test_feed_ok_y_caducidad():
    t = [1000.0]
    f = cercanias.CercaniasFeed(1.0, opener=lambda: DOC, now=lambda: t[0])
    f.poll()
    assert f.snapshot()["ok"] and f.snapshot()["count"] == 1
    t[0] += 300
    assert not f.snapshot()["ok"] and f.snapshot()["trains"] == []


def test_fixture_real_si_existe():
    p = "/mnt/user-data/attachments/2923e8fe-3b88-58fa-8ce1-1dfe19dbbebf/61a04746-attachment.txt"
    if not os.path.exists(p):
        return
    tr, _ = cercanias.parse(json.load(open(p)))
    assert len(tr) > 100 and all(t["line"] for t in tr[:50])
