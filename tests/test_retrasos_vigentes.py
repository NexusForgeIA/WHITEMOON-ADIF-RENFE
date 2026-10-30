import time
from datetime import datetime
from zoneinfo import ZoneInfo
import renfe_adapter as ra

TZ = ZoneInfo("Europe/Madrid")


def at(h, m=0):
    return datetime(2026, 10, 30, h, m, tzinfo=TZ).timestamp()


INFO = {"stops": ["A", "B"], "times": [(9 * 3600, 9 * 3600), (11 * 3600, 11 * 3600)]}   # sale 09:00, llega 11:00


def test_eta_es_hora_programada_mas_retraso():
    assert ra.eta_epoch(INFO, 30 * 60, at(10)) == at(11, 30)


def test_viaje_terminado_por_hora_no_cuenta_como_retraso():
    # +3 h 34: llegada estimada 14:34; a las 21:43 el viaje terminó hace horas
    assert ra.finished(INFO, "A", "IN_TRANSIT_TO", 214 * 60, at(21, 43))


def test_viaje_en_curso_con_retraso_sigue_contando():
    assert not ra.finished(INFO, "B", "IN_TRANSIT_TO", 120 * 60, at(12, 30))   # llega ~13:00


def test_parado_en_su_destino_ya_no_es_retraso():
    assert ra.finished(INFO, "B", "STOPPED_AT", 40 * 60, at(11, 30))


def test_sin_horas_no_se_decide():
    assert not ra.finished({"stops": ["A", "B"], "times": []}, "A", "IN_TRANSIT_TO", 600, at(23))


def test_viaje_que_cruza_la_medianoche():
    info = {"stops": ["A", "B"], "times": [(23 * 3600, 23 * 3600), (25 * 3600, 25 * 3600)]}   # llega 01:00 del día siguiente
    assert not ra.finished(info, "A", "IN_TRANSIT_TO", 600, at(0, 30))
