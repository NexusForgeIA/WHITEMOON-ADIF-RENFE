import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_safety_systems_json_valido_y_con_fuente():
    d = json.load(open(os.path.join(ROOT, "data", "safety_systems.json"), encoding="utf-8"))
    assert d["source"] and d["lines"] and d["available_at_adif"]
    ids = {l["id"] for l in d["lines"]}
    assert {"mad-sev", "cor-mal", "l400"} <= ids
    for l in d["lines"]:
        assert l["facts"] and l["summary"] and l["railguard"]


def test_madrid_sevilla_sin_etcs_segun_documento():
    inf = json.load(open(os.path.join(ROOT, "data", "infrastructure.json"), encoding="utf-8"))
    sev = next(c for c in inf["corridors"] if c["id"] == "mad-sev")
    assert "ETCS" in sev["signalling"] and "sin ETCS" in sev["signalling"]
