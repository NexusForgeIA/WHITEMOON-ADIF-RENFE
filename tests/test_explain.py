import engine
import explain


def test_todos_los_codigos_del_motor_tienen_explicacion():
    import re
    src = open(engine.__file__, encoding="utf-8").read()
    codes = set(re.findall(r'Hazard\("[A-Z0-9]+",[^"]*?"([A-Z_]+)"', src, re.S))
    assert codes, "no se detectaron códigos"
    assert not (codes - set(explain.CATALOG)), f"sin explicación: {codes - set(explain.CATALOG)}"


def test_build_incluye_datos_medidos():
    h = engine.Hazard("B3", 2, ("1",), None, "SPACING", "x", {"gap_km": 1.2, "need_km": 3.0, "front": "9"})
    w = explain.build(h)
    assert w["kind"] == "inferido" and ["Distancia actual", "1.2 km"] in w["data"] and ["Tren delantero", "9"] in w["data"] and w["recommend"]
    assert explain.build(engine.Hazard("B9", 1, ("1",), None, "NUEVO", "x"))["recommend"]
