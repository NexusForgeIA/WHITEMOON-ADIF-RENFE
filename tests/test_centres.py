import json
import os
import sys
import threading
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import centres as C  # noqa: E402
import server  # noqa: E402


def app(*scenarios):
    a = server.App()
    for sid in scenarios:
        a.set_scenario(sid, True)
    a.tick()
    a.prox_tick()
    return a


def ids(s):
    return {t["n"] for t in s["trains"]}


def test_every_train_has_exactly_one_home_zone_and_regional_views_are_subsets():
    a = app()
    nat = a.centre_snapshot("nacional")
    home = {}
    for cid in ("madrid", "barcelona", "sevilla"):
        s = a.centre_snapshot(cid)
        assert ids(s) <= ids(nat)
        for t in s["trains"]:
            if not t["incoming"]:
                assert t["n"] not in home, "un tren con dos centros titulares"
                home[t["n"]] = cid
    assert set(home) == ids(nat)


def test_regional_view_hides_other_zones_and_data():
    a = app()
    mad, sev = a.centre_snapshot("madrid"), a.centre_snapshot("sevilla")
    assert "05124" in ids(mad) and "05124" not in ids(sev)          # Madrid→Cuenca: zona de Madrid
    assert len(sev["stations"]) < len(a.centre_snapshot("nacional")["stations"])
    assert sev["drivers"] == [] and sev["kpi"]["trains"] == len(sev["trains"])
    assert all(any(c in {st["c"] for st in sev["stations"]} for c in cor["stations"]) for cor in sev["corridors"])


def test_failure_in_one_zone_is_only_in_that_centres_queue():
    a = app("via_unica")                                             # Las Mellizas↔Álora: zona de Sevilla
    assert any("T-9005" in i["title"] for i in a.centre_snapshot("sevilla")["operator"])
    assert not any("T-9005" in i["title"] for i in a.centre_snapshot("barcelona")["operator"])
    assert not any("T-9005" in i["title"] for i in a.centre_snapshot("madrid")["operator"])
    assert any("T-9005" in i["title"] for i in a.centre_snapshot("nacional")["operator"])


def test_rearm_only_in_own_zone_but_restrictions_anywhere():
    a = app()
    z = a.zones["03113"]                                             # Zaragoza→Lleida
    other = next(c for c in ("madrid", "barcelona", "sevilla") if c != z)
    code, out = a.centre_post(other, "/api/centre/rearm", {"train": "03113"})
    assert code == 403 and "zona" in out["msg"]
    code, out = a.centre_post(other, "/api/centre/manual", {"train": "03113", "release": True})
    assert code == 403
    code, out = a.centre_post(other, "/api/centre/manual", {"train": "03113"})   # restringir sí
    assert code == 200 and out["ok"] and "03113" in a.engine.manual
    assert any("03113" in m["text"] and m["to"] == z for m in a.centres.messages)  # y se avisa al centro titular
    code, out = a.centre_post(z, "/api/centre/manual", {"train": "03113", "release": True})
    assert code == 200 and out["ok"]
    code, _ = a.centre_post(z, "/api/centre/rearm", {"train": "03113"})
    assert code == 200                                               # el titular puede intentarlo (el motor decide)


def test_ack_only_for_items_visible_to_your_centre():
    a = app("via_unica")
    key = next(i["key"] for i in a.centre_snapshot("sevilla")["operator"] if "T-9005" in i["title"])
    assert a.centre_post("barcelona", "/api/centre/ack", {"key": key})[0] == 403
    code, out = a.centre_post("sevilla", "/api/centre/ack", {"key": key, "who": "ana"})
    assert code == 200 and out["ok"]
    assert "Sevilla" in list(a.engine.acks.values())[-1]["who"] and "ana" in list(a.engine.acks.values())[-1]["who"]


def test_unacknowledged_critical_escalates_to_every_centre():
    a = app("via_unica")
    assert not any("T-9005" in i["title"] for i in a.centre_snapshot("madrid")["operator"])
    for k in a.item_first:
        a.item_first[k] -= (server.ESCALATE_ITEM_S + 5) * 1000
    it = next(i for i in a.centre_snapshot("madrid")["operator"] if "T-9005" in i["title"])
    assert it["escalated"] is True


def test_acknowledged_critical_does_not_escalate_but_unacknowledged_siblings_do():
    a = app("via_unica")
    assert a.centre_post("sevilla", "/api/centre/ack", {"key": "stop:T-9005"})[1]["ok"]
    for k in a.item_first:
        a.item_first[k] -= (server.ESCALATE_ITEM_S + 5) * 1000
    keys = {i["key"] for i in a.centre_snapshot("madrid")["operator"]}
    assert "stop:T-9005" not in keys                                  # reconocido por su centro: no sube
    assert "stop:T-9006" in keys                                      # el de al lado, sin reconocer: sí


def test_centre_that_drops_is_flagged_and_its_zone_escalated():
    a = app("via_unica")
    a.centre_snapshot("sevilla")                                     # el centro de Sevilla estuvo conectado...
    a.centres.seen["sevilla"] -= 120_000                             # ...y lleva 2 min sin dar señales
    a.centre_snapshot("madrid")
    mad = a.centre_snapshot("madrid")["operator"]
    assert any(i["key"] == "centre:sevilla" and i["level"] == "CRITICA" for i in mad)
    assert any("T-9005" in i["title"] and i["escalated"] for i in mad)   # su zona pasa a verse en los demás
    board = {c["id"]: c for c in a.centre_snapshot("nacional")["centres"]}
    assert board["sevilla"]["online"] is False and board["madrid"]["online"] is True


def test_never_connected_centre_is_not_reported_as_dropped():
    a = app("via_unica")
    assert not any(i["key"].startswith("centre:") for i in a.snapshot()["operator"])
    assert next(c for c in a.snapshot()["centres"] if c["id"] == "sevilla")["seen"] is False


def test_handover_is_sticky_logged_and_messaged():
    c = C.Centres(os.path.join(server.ROOT, "data", "centres.json"), "/tmp/_none.json")
    mx, my = c.c["madrid"]["xy"]
    bx, by = c.c["barcelona"]["xy"]
    mid = ((mx + bx) / 2, (my + by) / 2)
    first = c.assign("X", mid[0] - 30, mid[1])[0]
    assert c.assign("X", mid[0] + 1, mid[1])[0] == first            # pasa 1 km la mediatriz: no cambia (histéresis)
    assert c.assign("X", mid[0] + 60, mid[1])[0] == "barcelona"     # 60 km más allá: cambia
    a = app()
    a.centres.sticky["03113"] = "madrid"                             # forzamos un traspaso real en el servidor
    a.zones["03113"] = "madrid"
    a.tick()
    assert any(e["kind"] == "HANDOVER" and "03113" in e["msg"] for e in a.engine.events)
    assert any("03113" in m["text"] and m["to"] == "barcelona" for m in a.centres.messages)


def test_messages_are_scoped_and_validated():
    a = app()
    assert a.centre_post("madrid", "/api/centre/message", {"to": "sevilla", "text": "Hola Sevilla"})[0] == 200
    assert a.centre_post("madrid", "/api/centre/message", {"to": "mordor", "text": "x"})[0] == 400
    assert a.centre_post("madrid", "/api/centre/message", {"to": "sevilla", "text": "  "})[0] == 400
    texts = lambda cid: [m["text"] for m in a.centre_snapshot(cid)["messages"]]
    assert "Hola Sevilla" in texts("sevilla") and "Hola Sevilla" in texts("madrid") and "Hola Sevilla" in texts("nacional")
    assert "Hola Sevilla" not in texts("barcelona")
    a.centre_post("madrid", "/api/centre/message", {"to": "*", "text": "A todos " + "x" * 400})
    assert "A todos" in " ".join(texts("barcelona")) and max(len(t) for t in texts("barcelona")) <= 300


def test_tokens_hashed_issue_needs_admin_and_revocation_by_reissue(tmp_path):
    a = server.App()
    a.token = None
    assert a.post("/api/centre/issue", {"centre": "madrid"})[0] == 403
    a.token = "adm"
    a.centres.auth_path = str(tmp_path / "t.json")
    code, out = a.post("/api/centre/issue", {"centre": "madrid"})
    tok = out["token"]
    assert a.auth_centre(tok, "ip")[0] == "madrid" and tok not in open(a.centres.auth_path).read()
    assert a.post("/api/centre/issue", {"centre": "mordor"})[0] == 400
    tok2 = a.post("/api/centre/issue", {"centre": "madrid"})[1]["token"]
    assert a.auth_centre(tok, "ip")[0] is None and a.auth_centre(tok2, "ip")[0] == "madrid"   # el anterior queda revocado
    for _ in range(25):
        a.auth_centre("x", "9.9.9.9")
    assert a.auth_centre(tok2, "9.9.9.9")[1] == "demasiados intentos"


def test_http_layer_enforces_centre_token():
    a = app()
    server.APP = a
    srv = ThreadingHTTPServer(("127.0.0.1", 0), server.H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def call(path, tok=None, body=None):
        h = {"Content-Type": "application/json"}
        if tok:
            h["X-Centre-Token"] = tok
        r = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None, h)
        try:
            with urllib.request.urlopen(r) as f:
                return f.status, json.load(f)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)
    try:
        assert call("/api/centre/snapshot")[0] == 401
        assert call("/api/centre/snapshot", "mala")[0] == 401
        code, s = call("/api/centre/snapshot", "ctc-sevilla")
        assert code == 200 and s["centre"]["id"] == "sevilla" and s["kpi"]["trains"] < 30
        assert call("/api/centre/rearm", None, {"train": "03113"})[0] == 401
        assert call("/api/centre/rearm", "ctc-sevilla", {"train": "05124"})[0] == 403    # tren de Madrid
        assert call("/api/centre/ack", "ctc-sevilla", {"key": "nope"})[0] == 403
        with urllib.request.urlopen(base + "/centro") as f:
            assert f.status == 200 and b"RailGuard" in f.read()
    finally:
        srv.shutdown()
