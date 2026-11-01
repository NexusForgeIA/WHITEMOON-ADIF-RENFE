import json
from datetime import datetime
from zoneinfo import ZoneInfo

import stats


def ts(d, h=12):
    return datetime(2026, 10, d, h, 0, tzinfo=ZoneInfo("Europe/Madrid")).timestamp()


def test_agrega_por_estacion_y_tren_y_ventanas(tmp_path):
    D = stats.Daily(str(tmp_path / "s.json"), every=0)
    for d in (28, 29, 30):
        for k in range(40):   # 40 muestras por día
            D.add([("05962", 10 if k % 2 else 0, "AVE", "60000", "Madrid Atocha"), ("04110", 0, "MD", "71801", "Barcelona Sants")], ts(d) + k)
    s = D.station("60000", "7d", ts(30))
    assert s["samples"] == 120 and s["days"] == 3 and s["pct_delayed"] == 50.0 and s["mean_min"] == 5.0 and s["max_min"] == 10
    assert D.station("60000", "1d", ts(30))["samples"] == 40
    assert D.station("60000", "1d", ts(31))["samples"] == 0          # ayer-hoy: sin datos hoy
    assert D.train("04110", "7d", ts(30))["pct_delayed"] == 0.0
    assert D.train("nope", "7d", ts(30))["pct_delayed"] is None


def test_ranking_exige_minimo_de_muestras_y_ordena(tmp_path):
    D = stats.Daily(None, every=0)
    for k in range(40):
        D.add([("A", 30, "AVE", "1", "Uno"), ("B", 2, "AVE", "2", "Dos"), ("C", 99, "AVE", "3", "Tres")], ts(30) + k) if k < 40 else None
    D.add([("RARO", 120, "AVE", "9", "Raro")], ts(30) + 100)         # 1 sola muestra: no entra
    top = D.top("7d", now=ts(30))
    assert [t["id"] for t in top["trains"]] == ["C", "A", "B"]
    assert [s["label"] for s in top["stations"]] == ["Tres", "Uno", "Dos"]


def test_persistencia_y_recorte_de_dias(tmp_path):
    p = str(tmp_path / "s.json")
    D = stats.Daily(p, every=0)
    for i in range(35):
        D.add([("X", 1, "AVE", "1", "Uno")], ts(1) + i * 86400)
    assert len(D.days) == stats.KEEP_DAYS
    assert D.save(force=True)
    assert len(stats.Daily(p).days) == stats.KEEP_DAYS and stats.Daily(p).names["1"] == "Uno"


def test_trainbook_estados():
    B = stats.TrainBook()
    t = lambda n, fin: {"n": n, "from": "A", "to": "B", "dest": "B" if fin else "C", "ret": 3, "finishing": fin}
    B.update([t("1", True), t("2", False)], 1000)
    assert B.status("1", 1000)["status"] == "live"
    B.update([], 1300)
    s1, s2 = B.status("1", 1600), B.status("2", 1600)
    assert s1["status"] == "finished" and s1["gone_min"] == 5 and s2["status"] == "lost"
    assert B.status("9", 1300)["status"] == "not_found"
    B.update([t("1", True)], 1400)              # vuelve a aparecer: ya no está «gone»
    assert B.status("1", 1400)["status"] == "live"
    B.update([], 1400 + stats.GONE_KEEP_S + 1)
    assert B.status("2", 1400 + stats.GONE_KEEP_S + 1)["status"] == "not_found"
