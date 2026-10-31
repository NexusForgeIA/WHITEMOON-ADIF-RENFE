import watch
from renfe_adapter import project

MIN = 60_000


def tr(n, lat, lon, kmh=0, ret=0):
    x, y = project(lat, lon)
    return {"n": n, "x": x, "y": y, "kmh": kmh, "ret": ret}


ST = {"A": {"n": "Estación A", "x": project(40.0, -3.0)[0], "y": project(40.0, -3.0)[1]}}


def run(w, trains, t0, minutes, **kw):
    out = []
    for m in range(minutes + 1):
        out = w.evaluate(trains, ST, t0 + m * MIN, **kw)
    return out


def ids(out, kind):
    return [i["id"] for i in out if i["type"] == kind]


def test_unproject_es_inversa_de_project():
    lat, lon = watch.unproject(*project(40.4, -3.7))
    assert abs(lat - 40.4) < 1e-9 and abs(lon + 3.7) < 1e-9


def test_detenido_en_plena_via_y_no_en_estacion():
    w = watch.Watch()
    out = run(w, [tr("1", 40.5, -3.5), tr("2", 40.0001, -3.0001)], 0, 10)    # el 2 está en una estación
    assert ids(out, "detenido") == ["detenido:1"]
    assert not ids(run(watch.Watch(), [tr("1", 40.5, -3.5)], 0, 5), "detenido")   # aún no pasa de 8 min


def test_tren_en_marcha_no_es_detenido():
    w = watch.Watch()
    out = []
    for m in range(12):
        out = w.evaluate([tr("1", 40.5 + m * 0.02, -3.5, kmh=200)], ST, m * MIN)
    assert not ids(out, "detenido")


def test_feed_congelado_no_declara_detenidos():
    out = run(watch.Watch(), [tr("1", 40.5, -3.5)], 0, 12, feed_age_s=900)
    assert not ids(out, "detenido")


def test_dos_trenes_parados_cerca_son_bloqueo():
    out = run(watch.Watch(), [tr("1", 40.5, -3.5), tr("2", 40.52, -3.5), tr("3", 38.0, -1.0)], 0, 10)
    b = [i for i in out if i["type"] == "bloqueo"]
    assert len(b) == 1 and b[0]["sev"] == "muy alta" and set(b[0]["trains"]) == {"1", "2"}


def test_salto_brusco_de_retraso():
    w = watch.Watch()
    w.evaluate([tr("1", 40.5, -3.5, 100, ret=2)], ST, 0)
    out = w.evaluate([tr("1", 40.6, -3.5, 100, ret=25)], ST, 5 * MIN)
    assert ids(out, "salto-retraso") == ["salto-retraso:1"]
    out2 = watch.Watch().evaluate([tr("1", 40.5, -3.5, 100, ret=30)], ST, 0)
    assert not ids(out2, "salto-retraso")


def test_caida_de_flota():
    w = watch.Watch()
    full = [tr(str(i), 40 + i * 0.01, -3.5, 100) for i in range(80)]
    w.evaluate(full, ST, 0)
    out = w.evaluate(full[:20], ST, 10 * MIN)
    assert ids(out, "flota") == ["flota"]


def test_fuentes_caidas_o_congeladas():
    h = [{"id": "renfe", "name": "Renfe", "ok": False, "err": "timeout", "critical": True},
         {"id": "noticias", "name": "Noticias", "ok": True, "age_s": 3000, "max_age_s": 900}]
    out = watch.Watch().evaluate([], ST, 0, health=h)
    assert ids(out, "fuente") == ["fuente:noticias", "fuente:renfe"] or set(ids(out, "fuente")) == {"fuente:renfe", "fuente:noticias"}


def test_red_electrica_desplome():
    r = {"deviation": -0.3, "demandMW": 14000, "forecastMW": 20000}
    out = watch.Watch().evaluate([], ST, 0, extras={"ree": r})
    assert out[0]["type"] == "red-electrica" and out[0]["sev"] == "muy alta"
    assert not watch.Watch().evaluate([], ST, 0, extras={"ree": {**r, "deviation": -0.05}})


def test_terremoto_cuenta_trenes_cercanos():
    q = {"id": "ign:1", "mag": 4.0, "lat": 40.0, "lon": -3.0, "t": 0, "title": "Terremoto M4.0 · X"}
    out = watch.Watch().evaluate([tr("1", 40.1, -3.0, 100), tr("2", 37.0, -5.0, 100)], ST, 10 * MIN, extras={"events": {"ign": [q]}})
    s = [i for i in out if i["type"] == "sismo"][0]
    assert s["trains"] == ["1"] and s["sev"] == "alta"
    old = watch.Watch().evaluate([], ST, 5 * 3600_000, extras={"events": {"ign": [q]}})
    assert not old


def test_aviso_meteo_con_poligono():
    ring = [(-4, 39), (-2, 39), (-2, 41), (-4, 41), (-4, 39)]
    ev = {"id": "aemet:x:0", "level": "naranja", "sev": "alta", "title": "Aviso naranja por lluvias · Madrid", "desc": "", "rings": [ring], "start": None, "end": None}
    amarillo = {**ev, "id": "y", "level": "amarillo"}
    out = watch.Watch().evaluate([tr("1", 40.0, -3.0, 100), tr("2", 37.0, -5.0, 100)], ST, 0, extras={"events": {"aemet": [ev, amarillo]}})
    m = [i for i in out if i["type"] == "meteo"]
    assert len(m) == 1 and m[0]["trains"] == ["1"]


def test_incendio_cerca_de_tren():
    f = {"id": "f1", "lat": 40.01, "lon": -3.0, "frp": 40, "t": 0}
    far = {"id": "f2", "lat": 38.0, "lon": -1.0, "frp": 80, "t": 0}
    out = watch.Watch().evaluate([tr("1", 40.0, -3.0, 100)], ST, MIN, extras={"events": {"firms": [f, far]}})
    inc = [i for i in out if i["type"] == "incendio"]
    assert len(inc) == 1 and inc[0]["trains"] == ["1"] and inc[0]["sev"] == "alta"
