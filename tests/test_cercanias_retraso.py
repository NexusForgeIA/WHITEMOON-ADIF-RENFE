import cercanias

VP = {"header": {"timestamp": 1000}, "entity": [
    {"id": "a", "vehicle": {"trip": {"tripId": "T1"}, "position": {"latitude": 40.4, "longitude": -3.7}, "vehicle": {"id": "1", "label": "C5-23737-PLATF.(5)"}, "currentStatus": "IN_TRANSIT_TO", "stopId": "S"}},
    {"id": "b", "vehicle": {"trip": {"tripId": "T2"}, "position": {"latitude": 40.5, "longitude": -3.6}, "vehicle": {"id": "2", "label": "C5-23738"}, "currentStatus": "IN_TRANSIT_TO", "stopId": "S"}}]}
TU = {"entity": [{"id": "x", "tripUpdate": {"trip": {"tripId": "T1"}, "delay": 600}}, {"id": "y", "tripUpdate": {"trip": {"tripId": "T9"}, "delay": 60}}]}


def test_retraso_de_cercanias_solo_con_dato_informado():
    f = cercanias.CercaniasFeed(1.0, opener=lambda: VP, alerts_opener=lambda: {"entity": []}, tu_opener=lambda: TU, now=lambda: 1000)
    f.poll()
    assert f.delays_ok and f.delay_rows() == [("C5 23737", 10, "CER")]    # T2 no tiene dato: no se cuenta como puntual
    snap = f.snapshot()
    assert snap["delay_n"] == 1 and snap["trains"][0][6] == 10 and snap["trains"][1][6] is None


def test_si_falla_trip_updates_las_posiciones_siguen():
    def boom():
        raise OSError("caído")
    f = cercanias.CercaniasFeed(1.0, opener=lambda: VP, alerts_opener=lambda: {"entity": []}, tu_opener=boom, now=lambda: 1000)
    f.poll()
    assert f.delays_ok is False and f.snapshot()["count"] == 2 and f.delay_rows() == []
