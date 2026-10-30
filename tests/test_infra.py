import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from infra import Infra, build, section_changes, simplify, signalling_of  # noqa: E402


def way(i, tracks, pts, **tags):
    return {"type": "way", "id": i, "tags": {"railway": "rail", "usage": "main", **({"tracks": str(tracks)} if tracks else {}), **tags},
            "geometry": [{"lat": a, "lon": b} for a, b in pts]}


def test_build_tracks_signalling_and_points():
    els = [way(1, 2, [(40.0, -3.0), (40.0, -3.1), (40.0, -3.2)], **{"railway:lzb": "yes"}),
           {"type": "node", "id": 9, "lat": 40.0, "lon": -3.1, "tags": {"railway": "signal", "railway:signal:main": "ES-ADIF:main"}},
           {"type": "node", "id": 10, "lat": 40.0, "lon": -3.15, "tags": {"railway": "switch", "railway:switch": "default"}}]
    ways, pts = build(els)
    assert ways[0]["t"] == 2 and ways[0]["s"] == "LZB" and len(ways[0]["p"]) == 2   # colineal: se simplifica a 2 puntos
    assert {p["k"] for p in pts} == {"signal", "switch"} and [p for p in pts if p["k"] == "signal"][0]["d"] == "principal"


def test_unknown_signalling_is_not_invented():
    assert signalling_of({"railway": "rail"}) is None and signalling_of({"railway:etcs": "no"}) is None
    assert signalling_of({"railway:etcs": "2"}) == "ETCS"


def test_section_change_marks_where_track_count_changes():
    ways, _ = build([way(1, 2, [(40.0, -3.0), (40.0, -3.1)]), way(2, 1, [(40.0, -3.1), (40.0, -3.2)]),
                     way(3, 2, [(41.0, -3.0), (41.0, -3.1)])])
    ch = section_changes(ways)
    assert len(ch) == 1 and ch[0]["d"] == "2→1 vías"


def test_simplify_keeps_corners():
    p = [(0, 0), (5, 0), (10, 0), (10, 5), (10, 10)]
    assert simplify(p, 0.05) == [(0, 0), (10, 0), (10, 10)]


def test_loader_tolerates_failed_tiles_and_never_fabricates(tmp_path):
    calls = {"n": 0}

    def opener(ep, q):
        calls["n"] += 1
        if calls["n"] % 2:
            raise OSError("502")
        return {"elements": [way(1, 2, [(40.0, -3.0), (40.0, -3.5)])]}
    import infra
    infra.time.sleep = lambda s: None
    i = Infra(cache=str(tmp_path / "c.json"), extra=str(tmp_path / "x.json"), opener=opener)
    i.run()
    assert i.status["state"] == "listo" and i.data["meta"]["counts"]["ways"] >= 1 and i.data["meta"]["official"] is False


def test_extra_official_data_is_loaded_and_flagged(tmp_path):
    import json
    (tmp_path / "x.json").write_text(json.dumps({"source": "Adif (cesión)", "points": [{"k": "balise", "lat": 40.0, "lon": -3.0}],
                                                 "cantones": [{"id": "C1", "points": [[40.0, -3.0], [40.0, -3.1]]}]}))
    i = Infra(cache=str(tmp_path / "c.json"), extra=str(tmp_path / "x.json"))
    i._set({"ways": [], "points": []})
    assert i.data["meta"]["extra_source"] == "Adif (cesión)" and i.data["points"][0]["official"] and len(i.data["cantones"]) == 1


def test_build_ignora_nodos_nulos_de_la_geometria():
    """Overpass pone null en los nodos de una vía que caen fuera de la tesela; no debe tumbar la descarga."""
    els = [{"type": "way", "id": 1, "tags": {"tracks": "2"}, "geometry": [{"lat": 40.0, "lon": -3.0}, None, {"lat": 40.1, "lon": -3.1}, None]},
           {"type": "way", "id": 2, "tags": {}, "geometry": [None, None]}]
    ways, _ = build(els)
    assert len(ways) == 1 and ways[0]["t"] == 2


def test_consulta_pide_coordenadas_de_los_nodos():
    """Con «out tags» Overpass devuelve los nodos SIN lat/lon y se pierden todas las señales y desvíos."""
    from infra import query
    q = query((40, -4, 41, -3))
    assert q.rstrip().endswith("out body qt;") and "out tags qt;" not in q.split("->.r;")[1].split("node(w.r)")[1]
