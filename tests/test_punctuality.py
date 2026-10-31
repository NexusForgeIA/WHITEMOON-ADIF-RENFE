import time
import punctuality as pu


def test_categorias():
    assert pu.category("AVE") == "AVE" and pu.category("AVLO") == "AVLO" and pu.category("ALVIA") == "LD"
    assert pu.category("AVANT") == "AVANT" and pu.category("MD") == "MD" and pu.category("REGIONAL EXPRES") == "REG"
    assert pu.category("R.EXPRES") == "REG" and pu.category("") == "OTRO" and pu.category("XYZ") == "OTRO"


def test_kpis_y_umbrales_de_renfe():
    rows = [("1", 0, "AVE"), ("2", 61, "AVE"), ("3", 20, "AVANT"), ("4", 15, "MD"), ("5", 45, "REG"), ("6", 10, "OTRO")]
    k = pu.compute(rows)
    assert k["n"] == 6 and k["delayed"] == 5 and k["sum_min"] == 151 and k["max_min"] == 61
    # indemnizan: AVE 61 (≥60), Avant 20 (>15), Regional 45 (>30); MD 15 no (exige más de 15); OTRO sin umbral
    assert k["indem"] == 3 and k["pct_indem"] == 50.0
    assert sum(b["n"] for b in k["buckets"]) == 6


def test_un_registro_por_vehiculo_y_vacio():
    assert pu.compute([("1", 30, "AVE"), ("1", 30, "AVE")])["n"] == 2   # un registro por vehículo, como el contador de trenes
    k = pu.compute([])
    assert k["n"] == 0 and k["pct_delayed"] == 0.0 and k["mean_min"] == 0.0


def test_historia_una_muestra_por_minuto(tmp_path):
    h = pu.History(str(tmp_path / "h.json"), every=60)
    k = pu.compute([("1", 10, "AVE")])
    t0 = time.time()
    assert h.add(k, t0) and not h.add(k, t0 + 30) and h.add(k, t0 + 70)
    assert len(h.series()["pts"]) == 2
    assert len(pu.History(str(tmp_path / "h.json")).series()["pts"]) == 2   # persiste dentro del mismo día


def test_peores_trenes_mediana_y_a_tiempo():
    import punctuality as pu
    k = pu.compute([("A", 0, "AVE"), ("B", 90, "AVE"), ("C", 20, "MD"), ("D", 3, "MD"), ("E", 61, "LD")])
    assert [w["n"] for w in k["worst"]] == ["B", "E", "C"]      # solo retrasos >= 5 min, de mayor a menor
    assert k["median_min"] == 20 and k["on_time"] == 2 and k["pct_on_time"] == 40.0
    assert pu.compute([])["worst"] == [] and pu.compute([])["median_min"] == 0


def test_segmentos_alta_velocidad_y_convencional():
    rows = [("1", 0, "AVE"), ("2", 61, "AVLO"), ("3", 20, "AVANT"), ("4", 15, "MD"), ("5", 45, "REG"), ("6", 70, "LD")]
    av = pu.compute(rows, "av")
    assert av["n"] == 3 and av["delayed"] == 2 and av["seg"] == "av" and av["seg_label"] == "Alta velocidad"
    cv = pu.compute(rows, "conv")
    assert cv["n"] == 3 and cv["delayed"] == 3 and cv["max_min"] == 70
    todo = pu.compute(rows, "all")
    assert todo["n"] == av["n"] + cv["n"] == 6


def test_segmento_vacio_no_divide_por_cero():
    k = pu.compute([("1", 5, "MD")], "av")
    assert k["n"] == 0 and k["pct_delayed"] == 0.0 and k["worst"] == []
