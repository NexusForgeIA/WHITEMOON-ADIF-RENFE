import io
import math
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import Engine  # noqa: E402
from renfe_adapter import RenfeFeed, load_gtfs, product_of, project  # noqa: E402

T0 = 1_793_362_000  # s
KM_LON = 111.32 * math.cos(math.radians(40))


def vp(entities, ts):
    return {"header": {"gtfsRealtimeVersion": "2.0", "timestamp": str(ts)}, "entity": entities}


def ent(num, lat, lon, stop, status="IN_TRANSIT_TO", day="2026-10-30"):
    # forma EXACTA de las entidades reales de gtfsrt.renfe.com/vehicle_positions_LD.json
    return {"id": f"VP_{num}", "vehicle": {"trip": {"tripId": f"{num}1{day}"},
            "position": {"latitude": lat, "longitude": lon}, "currentStatus": status, "stopId": stop,
            "vehicle": {"id": num, "label": num}}}


def tu(trip, delay):
    return {"header": {"timestamp": str(T0)}, "entity": [{"id": "TUUPDATE_" + trip, "tripUpdate": {
        "trip": {"tripId": trip, "scheduleRelationship": "SCHEDULED"},
        "stopTimeUpdate": [{"stopId": "37500", "arrival": {"delay": delay, "time": "1793356260"}}], "delay": delay}}]}


def gtfs_zip(trips):
    """trips: {numero: (producto, [stops])}; stops S1,S2.. con coordenadas fijas"""
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("stops.txt", "stop_id,stop_name,stop_lat,stop_lon\nS1,Origen,41.0,-4.0\nS2,Destino,41.0,-2.0\nS3,Mitad,41.0,-3.0\n")
        f.writestr("routes.txt", "route_id,route_short_name,route_long_name\nR1,AVE,\nR2,MD,\n")
        f.writestr("trips.txt", "route_id,trip_id\n" + "".join(f"{'R1' if p == 'AVE' else 'R2'},{n}\n" for n, (p, _) in trips.items()))
        f.writestr("stop_times.txt", "trip_id,stop_id,stop_sequence\n" +
                   "".join(f"{n},{s},{i}\n" for n, (_, st) in trips.items() for i, s in enumerate(st)))
    z.seek(0)
    path = "/tmp/_gtfs_test.zip"
    open(path, "wb").write(z.read())
    return load_gtfs(path)


def feed_with(sequence, gtfs=None, delays=None):
    """sequence: lista de (ts, [entidades]); cada fetch() consume la siguiente."""
    it = iter(sequence)
    cur = {}

    def opener(url):
        if url.endswith("trip_updates_LD.json"):
            return delays or {"header": {"timestamp": str(T0)}, "entity": []}
        ts, ents = next(it)
        cur["ts"] = ts
        return vp(ents, ts)
    return RenfeFeed(gtfs, opener=opener, now=lambda: cur.get("ts", T0))


def test_projection_madrid_barcelona_within_3pct():
    ax, ay = project(40.4168, -3.7038)
    bx, by = project(41.3851, 2.1734)
    assert abs(math.hypot(bx - ax, by - ay) - 505) / 505 < 0.03


def test_parses_real_entity_shape():
    f = feed_with([(T0, [ent("12614", 42.4929, -6.8327165, "20204")])])
    _, tr = f.fetch()
    assert tr[0]["n"] == "12614" and tr[0]["sig"] == "20204" and tr[0]["ts"] == T0 * 1000


def test_speed_is_derived_from_successive_positions():
    dlat = 0.01 / 1  # 1,112 km al sur en 15 s -> 267 km/h
    f = feed_with([(T0, [ent("11111", 41.0, -3.0, "S2")]), (T0 + 15, [ent("11111", 41.0 + dlat, -3.0, "S2")])])
    f.fetch()
    _, tr = f.fetch()
    assert 250 < tr[0]["kmh"] < 285


def test_frozen_gps_keeps_old_timestamp_so_B1_sees_it_age():
    f = feed_with([(T0, [ent("11111", 41.0, -3.0, "S2")]), (T0 + 15, [ent("11111", 41.01, -3.0, "S2")]),
                   (T0 + 30, [ent("11111", 41.01, -3.0, "S2")]), (T0 + 45, [ent("11111", 41.01, -3.0, "S2")])])
    f.fetch()
    f.fetch()
    _, tr = f.fetch()
    _, tr = f.fetch()
    assert tr[0]["kmh"] > 200 and tr[0]["ts"] == (T0 + 15) * 1000   # sigue 'moviéndose' pero con la hora del último cambio


def test_genuinely_stopped_train_is_not_flagged_as_frozen():
    f = feed_with([(T0, [ent("11111", 41.0, -3.0, "S2")]), (T0 + 15, [ent("11111", 41.0, -3.0, "S2")]),
                   (T0 + 30, [ent("11111", 41.0, -3.0, "S2")])])
    f.fetch()
    f.fetch()
    _, tr = f.fetch()
    assert tr[0]["kmh"] == 0 and tr[0]["ts"] == (T0 + 30) * 1000


def test_delay_from_trip_updates():
    f = feed_with([(T0, [ent("00190", 41.0, -3.0, "37500")])], delays=tu("0019012026-10-30", 540))
    _, tr = f.fetch()
    assert tr[0]["ret"] == 9


def test_gtfs_gives_previous_stop_destination_and_product():
    g = gtfs_zip({"11111": ("AVE", ["S1", "S3", "S2"]), "22222": ("MD", ["S1", "S2"])})
    f = feed_with([(T0, [ent("11111", 41.0, -3.2, "S3"), ent("22222", 41.0, -3.0, "S1", "STOPPED_AT")])], gtfs=g)
    est, tr = f.fetch()
    a, b = {t["n"]: t for t in tr}["11111"], {t["n"]: t for t in tr}["22222"]
    assert (a["ant"], a["sig"], a["des"], a["p"]) == ("S1", "S3", "S2", 2)
    assert b["ant"] == b["sig"] == "S1" and b["kmh"] == 0 and b["p"] == 16
    assert set(est) == {"S1", "S2", "S3"}


def test_product_names():
    assert product_of("AVE", "") == 2 and product_of("ALVIA") == 11 and product_of("MD") == 16 and product_of("") == 0


def test_end_to_end_following_too_close_is_stopped_through_the_real_pipeline():
    g = gtfs_zip({"11111": ("AVE", ["S1", "S2"]), "22222": ("AVE", ["S1", "S2"])})
    d = lambda km: km / KM_LON  # km -> grados de longitud
    fl0, rl0 = -3.0, -3.0 - d(1.4)
    seq = [(T0, [ent("11111", 41.0, fl0, "S2"), ent("22222", 41.0, rl0, "S2")]),
           (T0 + 15, [ent("11111", 41.0, fl0 + d(0.5), "S2"), ent("22222", 41.0, rl0 + d(1.0417), "S2")])]
    f = feed_with(seq, gtfs=g)
    e = Engine(f.est, cfg={"km_per_px": 1.0})
    f.fetch()
    est, tr = f.fetch()
    e.step(tr, (T0 + 15) * 1000 + 2000)
    cmd = {t["n"]: t["cmd"] for t in e.snapshot()["trains"]}
    assert cmd["22222"] == "STOP", (cmd, [(h.barrier, h.msg) for h in e.hazards])
    assert {"B3", "B4"} <= {h.barrier for h in e.hazards}


def test_unknown_product_does_not_trigger_false_overspeed_for_an_ave():
    f = feed_with([(T0, [ent("33333", 41.0, -3.0, "S2")]), (T0 + 15, [ent("33333", 41.0, -3.0 + 1.1667 / KM_LON, "S2")])])  # 1,167 km en 15 s = 280 km/h
    e = Engine(f.est, cfg={"km_per_px": 1.0})
    f.fetch()
    _, tr = f.fetch()
    e.step(tr, (T0 + 15) * 1000 + 1000)
    assert [h for h in e.hazards if h.barrier == "B2"] == []


def test_train_detail_has_schedule_delay_and_position_text():
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("stops.txt", "stop_id,stop_name,stop_lat,stop_lon\nS1,Madrid,41.0,-4.0\nS2,Vigo,41.0,-2.0\nS3,Ourense,41.0,-3.0\n")
        f.writestr("routes.txt", "route_id,route_short_name,route_long_name\nR1,AVE,\n")
        f.writestr("trips.txt", "route_id,trip_id\nR1,11111\n")
        f.writestr("stop_times.txt", "trip_id,stop_id,stop_sequence,arrival_time,departure_time\n"
                   "11111,S1,0,12:00:00,12:00:00\n11111,S3,1,14:30:00,14:32:00\n11111,S2,2,15:16:00,15:16:00\n")
    z.seek(0)
    open("/tmp/_gtfs_t2.zip", "wb").write(z.read())
    g = load_gtfs("/tmp/_gtfs_t2.zip")
    f = feed_with([(T0, [ent("11111", 41.0, -3.2, "S3")])], gtfs=g, delays=tu("111111" + "2026-10-30", 4080))
    f.fetch()
    d = f.detail["11111"]
    assert d["product"] == "AVE" and d["ori"] == "Madrid" and d["des"] == "Vigo"
    assert (d["dest_sched"], d["dest_est"]) == ("15:16", "16:24")      # 15:16 + 68 min
    assert d["next"] == {"name": "Ourense", "sched": "14:30", "est": "15:38"}
    assert d["where"] == "Entre Madrid y Ourense"


def test_entity_without_stop_id_does_not_break_the_feed_or_the_detail():
    g = gtfs_zip({"11111": ("AVE", ["S1", "S3", "S2"])})
    e = ent("11111", 41.0, -3.2, None)
    e["vehicle"].pop("stopId")
    f = feed_with([(T0, [e, ent("22222", 41.0, -3.0, "S3")])], gtfs=g)
    _, tr = f.fetch()
    assert len(tr) == 1 and "11111" in f.detail           # el 22222 no está en el horario: no se dibuja
    assert f.stats["sin_horario"] == 1


def test_tren_terminado_no_se_dibuja():
    """Un tren parado en su última parada no está en circulación: ni mapa, ni peligros, ni KPIs."""
    g = gtfs_zip({"22222": ("MD", ["S1", "S2"])})
    f = feed_with([(T0, [ent("22222", 41.0, -3.0, "S2", "STOPPED_AT")])], gtfs=g)
    _, tr = f.fetch()
    assert tr == [] and f.stats["retrasos_caducados"] == 1


def test_mismo_tren_repetido_en_el_feed_sale_una_vez():
    """El feed publica a veces varias entidades con la misma etiqueta de tren: en el panel debe aparecer una sola."""
    a, b = ent("33333", 41.0, -3.0, "S1"), ent("33333", 41.0, -3.0, "S1")
    b["id"] = "VP_otra"; b["vehicle"]["vehicle"]["id"] = "v2"
    f = feed_with([(T0, [a, b, ent("44444", 40.0, -3.0, "S1")])])
    _, tr = f.fetch()
    assert sorted(t["n"] for t in tr) == ["33333", "44444"] and f.stats["duplicados"] == 1


def test_duplicado_prefiere_el_que_tiene_parada():
    """En el feed real el mismo tren llega con 2-6 viajes (sufijos 1,2,3…); algunos sin stopId: gana el que lo tiene."""
    sin, con = ent("55555", 41.0, -3.0, "S1"), ent("55555", 41.0, -3.0, "S1")
    del sin["vehicle"]["stopId"]
    con["vehicle"]["trip"]["tripId"] = "55555312026-10-30"
    _, tr = feed_with([(T0, [sin, con])]).fetch()
    assert len(tr) == 1 and tr[0]["sig"] == "S1"
