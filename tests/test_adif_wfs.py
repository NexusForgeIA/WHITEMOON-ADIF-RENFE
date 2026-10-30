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
