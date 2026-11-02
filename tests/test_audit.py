import json

import audit


def mk(tmp_path, **kw):
    return audit.Audit(str(tmp_path / "a.jsonl"), **kw)


def test_cadena_integra_y_persistente(tmp_path):
    A = mk(tmp_path)
    for i in range(5):
        A.append({"t": 1000 + i, "kind": "HAZARD", "msg": f"m{i}"})
    v = A.verify()
    assert v["ok"] and v["n"] == 5 and v["last_seq"] == 5
    B = mk(tmp_path)                      # reinicio: continúa la misma cadena
    B.append({"t": 2000, "kind": "ACTUATE", "msg": "x"})
    assert B.verify()["ok"] and B.seq == 6 and B.verify()["n"] == 6


def test_detecta_alteracion_borrado_y_reordenacion(tmp_path):
    A = mk(tmp_path)
    for i in range(6):
        A.append({"t": i, "msg": f"m{i}"})
    lines = open(A.path).read().splitlines()
    # 1) contenido alterado
    bad = json.loads(lines[2]); bad["e"]["msg"] = "otro"
    open(A.path, "w").write("\n".join(lines[:2] + [json.dumps(bad)] + lines[3:]) + "\n")
    v = A.verify(); assert not v["ok"] and v["bad_seq"] == 3 and "alterado" in v["why"]
    # 2) registro borrado
    open(A.path, "w").write("\n".join(lines[:2] + lines[3:]) + "\n")
    v = A.verify(); assert not v["ok"] and v["bad_seq"] == 4
    # 3) reordenado
    open(A.path, "w").write("\n".join([lines[0], lines[2], lines[1]] + lines[3:]) + "\n")
    assert not A.verify()["ok"]
    # 4) cola truncada (se pierden los últimos registros)
    open(A.path, "w").write("\n".join(lines[:4]) + "\n")
    v = A.verify(); assert not v["ok"] and "cabeza" in v["why"]


def test_rotacion_conserva_ancla_valida(tmp_path):
    A = mk(tmp_path, max_bytes=3000)
    for i in range(80):
        A.append({"t": i, "msg": "x" * 40})
    v = A.verify()
    assert v["ok"] and v["first_seq"] > 1 and v["last_seq"] == 80


def test_export_por_ventana(tmp_path):
    A = mk(tmp_path)
    for i in range(10):
        A.append({"t": i * 100, "msg": str(i)})
    r = A.export(300, 600)
    assert [x["e"]["t"] for x in r] == [300, 400, 500, 600]
