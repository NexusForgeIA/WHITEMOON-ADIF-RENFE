import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import adif_wfs as A  # noqa: E402


def test_feature_types_ignores_namespace_prefix():
    xml = "<a><wfs:FeatureType><wfs:Name>tn-ra:RailwayLink</wfs:Name></wfs:FeatureType><FeatureType><Name>RailwayNode</Name></FeatureType></a>"
    assert A.feature_types(xml) == ["tn-ra:RailwayLink", "RailwayNode"]


def test_pick_is_case_and_separator_insensitive():
    p = {"Number_Of_Tracks": "2", "nominalTrackGauge": "1668", "x": None}
    assert A.pick(p, "numberoftracks") == "2"
    assert A.pick(p, "gauge") == "1668"
    assert A.pick(p, "nada") is None


def test_axis_order_detection():
    assert A.looks_swapped([[40.4, -3.7], [40.5, -3.6]]) is True    # lat,lon
    assert A.looks_swapped([[-3.7, 40.4], [-3.6, 40.5]]) is False   # lon,lat


def test_electrified_text():
    assert A._electrified("notElectrified") is False
    assert A._electrified("contactLineSystem") is True
    assert A._electrified(None) is None


def test_tracks_between_votes_nearest_official_way():
    ways = [{"t": 2, "p": [[0, 0], [100, 0]]}, {"t": 1, "p": [[0, 50], [100, 50]]}]
    assert A.tracks_between(ways, (10, 0.2), (90, 0.2)) == 2
    assert A.tracks_between(ways, (10, 50.1), (90, 50.1)) == 1
    assert A.tracks_between(ways, (10, 20), (90, 20)) is None       # nada a menos de 1,5 km: no se inventa


def test_ign_parse_links_reads_gml_and_flags_fictitious():
    import ign_wfs
    gml = b"""<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0" xmlns:gml="http://www.opengis.net/gml/3.2"
      xmlns:tn-ra="urn:x" xmlns:net="urn:y"><wfs:member><tn-ra:RailwayLink><net:centrelineGeometry><gml:LineString>
      <gml:posList>40.0 -3.0 40.1 -3.1</gml:posList></gml:LineString></net:centrelineGeometry><net:fictitious>true</net:fictitious>
      </tn-ra:RailwayLink></wfs:member><wfs:member><tn-ra:RailwayLink><net:centrelineGeometry><gml:LineString>
      <gml:posList>41.0 -2.0 41.2 -2.2 41.3 -2.4</gml:posList></gml:LineString></net:centrelineGeometry><net:fictitious>false</net:fictitious>
      </tn-ra:RailwayLink></wfs:member></wfs:FeatureCollection>"""
    r = ign_wfs.parse_links(gml)
    assert [f for f, _ in r] == [True, False]
    assert r[1][1][0] == (41.0, -2.0) and len(r[1][1]) == 3


def test_ign_tolera_una_pagina_caida(monkeypatch):
    import ign_wfs, time
    monkeypatch.setattr(time, "sleep", lambda s: None)
    gml = b'<r xmlns:a="x"><a:RailwayLink><a:fictitious>false</a:fictitious><a:posList>40.0 -3.0 40.1 -3.1</a:posList></a:RailwayLink></r>'
    n = {"c": 0}

    def fake(url, timeout=0):
        if "resultType=hits" in url:
            return b'numberMatched="%d"' % (ign_wfs.PAGE * 10)
        if "startIndex=%d" % (3 * ign_wfs.PAGE) in url:
            raise OSError("502")
        return gml
    monkeypatch.setattr(ign_wfs, "_get", fake)
    diag = {}
    ways = ign_wfs.load(diag, lambda p: p)
    assert len(ways) == 10 and diag["failed_pages"] == [3]
