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


def test_avisos_filtra_ascensores_y_antiguos_y_mapea_lineas():
    doc = {"header": {"timestamp": "100000"}, "entity": [
        {"id": "A", "alert": {"activePeriod": [{"start": "96400"}], "informedEntity": [{"routeId": "51T0244R3"}, {"routeId": "51T0015R3"}],
         "descriptionText": {"translation": [{"text": "Sin servicio ferroviario. "}]}}},
        {"id": "B", "alert": {"activePeriod": [{"start": "96400"}], "informedEntity": [{"stopId": "70100"}],
         "descriptionText": {"translation": [{"text": "Ascensor de Vicálvaro fuera de servicio"}]}}},
        {"id": "C", "alert": {"activePeriod": [{"start": "999999"}], "informedEntity": [{"routeId": "10T0011C4"}],
         "descriptionText": {"translation": [{"text": "Sin servicio futuro"}]}}},
        {"id": "D", "alert": {"activePeriod": [{"start": "1"}], "informedEntity": [{"routeId": "10T0014C4a"}],
         "descriptionText": {"translation": [{"text": "Por reajuste de servicio, tren con salida a las 09:05h inicia su recorrido en Tres Cantos"}]}}}]}
    al = cercanias.parse_alerts(doc, now=100000)
    assert [a["id"] for a in al] == ["A"]   # D: sin fin y de 1970 → caducado
    assert al[0]["lines"] == ["R3"] and al[0]["region"] == "Rodalies Catalunya" and al[0]["age_h"] == 1
    assert al[0]["age_min"] == 60


def _al(i, text, start, end=None):
    per = {"start": str(start)}
    if end:
        per["end"] = str(end)
    return {"id": i, "alert": {"activePeriod": [per], "informedEntity": [{"routeId": "10T0014C4"}],
            "descriptionText": {"translation": [{"text": text}]}}}


def test_avisos_edad_con_hora_real_y_caducidad():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    now = int(datetime(2026, 10, 30, 21, 16, tzinfo=ZoneInfo("Europe/Madrid")).timestamp())
    h = now - 12 * 3600   # cabecera del feed atrasada no debe rejuvenecer avisos
    doc = {"header": {"timestamp": str(h)}, "entity": [
        _al("viejo_hora", "Tren con salida a las 08:30h no efectúa parada en Atocha. Servicio afectado", now - 3600),
        _al("viejo_sinfin", "Retrasos por incidencia en la línea, servicio afectado", now - 9 * 3600),
        _al("caducado", "Servicio interrumpido por obras", now - 5 * 3600, now - 600),
        _al("vigente", "Servicio interrumpido entre Atocha y Chamartín por incidencia", now - 25 * 60),
        _al("hora_reciente", "Tren con salida a las 20:50h suprimido por incidencia", now - 30 * 60)]}
    al = cercanias.parse_alerts(doc, now=now)
    assert [a["id"] for a in al] == ["vigente", "hora_reciente"]
    assert {a["id"]: a["age_min"] for a in al}["vigente"] == 25
