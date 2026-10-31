import json
import extras as ex

REE = {"included": [{"type": "Real", "attributes": {"values": [{"datetime": "2026-10-31T10:00:00.000+01:00", "value": 15000}, {"datetime": "2026-10-31T10:05:00.000+01:00", "value": 14000}]}},
                    {"type": "Prevista", "attributes": {"values": [{"datetime": "2026-10-31T10:05:00.000+01:00", "value": 20000}]}}]}

IGN = """<rss xmlns:geo="http://www.w3.org/2003/01/geo/wgs84_pos#"><channel><item><title>x</title><link>http://ign/1</link><guid>http://ign/?evid=es2026abc</guid>
<description>Se ha producido un terremoto de magnitud 3.8 en GOLFO DE CADIZ en la fecha 31/10/2026 10:00:00 en la siguiente localización: 36.1,-6.9</description>
<geo:lat>36.1</geo:lat><geo:long>-6.9</geo:long></item></channel></rss>"""

CAP = """<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2"><identifier>ID1</identifier><msgType>Alert</msgType>
<info><language>es-ES</language><event>Aviso de lluvias de nivel naranja</event><onset>2026-10-31T10:00:00+01:00</onset><expires>2026-10-31T23:00:00+01:00</expires>
<description>Lluvia fuerte</description><parameter><valueName>AEMET-Meteoalerta nivel</valueName><value>naranja</value></parameter>
<area><areaDesc>Madrid</areaDesc><polygon>39,-4 39,-2 41,-2 41,-4 39,-4</polygon></area></info></alert>"""

FIRMS = "latitude,longitude,frp,confidence,acq_date,acq_time\n40.1,-3.2,35.0,n,2026-10-31,1030\n36.0,2.0,90,h,2026-10-31,1030\n41,-3,5,l,2026-10-31,1030\n"


def test_ree():
    m = ex.parse_ree(REE)
    assert m["demandMW"] == 14000 and abs(m["deviation"] + 0.3) < 1e-9 and len(m["history"]) == 2
    assert ex.parse_ree({"included": []}) is None


def test_ign():
    e = ex.parse_ign(IGN)
    assert len(e) == 1 and e[0]["mag"] == 3.8 and e[0]["id"] == "ign:es2026abc" and e[0]["sev"] == "media"
    assert e[0]["t"] == 1793440800000   # 31/10/2026 10:00 UTC
    assert ex.parse_ign("no es xml") == []


def test_cap_con_poligono_y_nivel():
    a = ex.parse_cap(CAP)
    assert len(a) == 1 and a[0]["level"] == "naranja" and a[0]["type"] == "lluvias" and a[0]["rings"][0][0] == (-4.0, 39.0)
    assert a[0]["start"] < a[0]["end"]
    assert ex.parse_cap(CAP.replace("naranja</value>", "verde</value>").replace("nivel naranja", "nivel verde")) == []
    assert ex.parse_cap(CAP.replace("Alert", "Cancel")) == []


def test_firms_filtra_españa_y_confianza_baja():
    f = ex.parse_firms(FIRMS)
    assert len(f) == 1 and f[0]["lat"] == 40.1 and f[0]["sev"] == "media"   # Argelia fuera, confianza baja fuera


def test_extras_con_red_simulada_y_fallos_aislados():
    calls = {}

    def get(url, timeout=25):
        calls[url] = 1
        if "apidatos" in url:
            return json.dumps(REE)
        if "sismologia" in url:
            raise OSError("caído")
        raise AssertionError(url)
    e = ex.Extras(get=get)
    e.refresh_ree()
    e.refresh_ign()
    s = e.snapshot()
    assert s["ree"]["demandMW"] == 14000 and s["status"]["ree"]["ok"] is True
    assert s["status"]["ign"]["ok"] is False and "caído" in s["status"]["ign"]["err"]
