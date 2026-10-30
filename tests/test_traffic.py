import traffic as tr

XML = """<?xml version="1.0" encoding="UTF-8"?>
<d2:payload xmlns:d2="http://datex2.eu/schema/3/d2Payload" xmlns:sit="http://datex2.eu/schema/3/situation" xmlns:loc="http://datex2.eu/schema/3/locationReferencing"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:type="sit:SituationPublication"><sit:situation id="S1">
<sit:situationRecord xsi:type="sit:RoadOrCarriagewayOrLaneManagement" id="1"><sit:validity><sit:validityStatus>active</sit:validityStatus>
 <sit:validityTimeSpecification><sit:overallStartTime>2025-12-12T08:05:19.000+01:00</sit:overallStartTime></sit:validityTimeSpecification></sit:validity>
 <sit:cause><sit:causeType>roadMaintenance</sit:causeType></sit:cause>
 <sit:locationReference xsi:type="loc:SingleRoadLinearLocation"><sit:roadInformation><sit:roadName>N-400</sit:roadName></sit:roadInformation>
 <loc:tpegLinearLocation><loc:to><loc:pointCoordinates><loc:latitude>39.994446</loc:latitude><loc:longitude>-3.6054852</loc:longitude></loc:pointCoordinates>
 <loc:extendedTpegNonJunctionPoint><loc:kilometerPoint>37.3</loc:kilometerPoint><loc:municipality>Ontígola</loc:municipality></loc:extendedTpegNonJunctionPoint></loc:to>
 <loc:from><loc:pointCoordinates><loc:latitude>39.993732</loc:latitude><loc:longitude>-3.6074991</loc:longitude></loc:pointCoordinates></loc:from></loc:tpegLinearLocation></sit:locationReference></sit:situationRecord>
<sit:situationRecord xsi:type="sit:AbnormalTraffic" id="2"><sit:validity><sit:validityStatus>active</sit:validityStatus></sit:validity>
 <sit:generalPublicComment><sit:comment><sit:values><sit:value lang="es">Retención de 3 km</sit:value></sit:values></sit:comment></sit:generalPublicComment>
 <sit:locationReference xsi:type="loc:PointLocation"><loc:tpegPointLocation><loc:point><loc:pointCoordinates><loc:latitude>40.4</loc:latitude><loc:longitude>-3.7</loc:longitude></loc:pointCoordinates></loc:point></loc:tpegPointLocation></sit:locationReference></sit:situationRecord>
<sit:situationRecord xsi:type="sit:Accident" id="3"><sit:validity><sit:validityStatus>suspended</sit:validityStatus></sit:validity>
 <sit:locationReference><loc:pointCoordinates><loc:latitude>40.5</loc:latitude><loc:longitude>-3.7</loc:longitude></loc:pointCoordinates></sit:locationReference></sit:situationRecord>
<sit:situationRecord xsi:type="sit:Accident" id="4"><sit:validity><sit:validityStatus>active</sit:validityStatus>
 <sit:validityTimeSpecification><sit:overallEndTime>2020-01-01T00:00:00+01:00</sit:overallEndTime></sit:validityTimeSpecification></sit:validity>
 <sit:locationReference><loc:pointCoordinates><loc:latitude>40.5</loc:latitude><loc:longitude>-3.7</loc:longitude></loc:pointCoordinates></sit:locationReference></sit:situationRecord>
<sit:situationRecord xsi:type="sit:Accident" id="5"><sit:validity><sit:validityStatus>active</sit:validityStatus></sit:validity></sit:situationRecord>
</sit:situation></d2:payload>""".encode("utf-8")


def test_parse_tipos_ubicacion_y_vigencia():
    r = {i["id"]: i for i in tr.parse(XML, now=1.8e9)}
    assert sorted(r) == ["1", "2"]                       # 3 suspendida, 4 caducada, 5 sin coordenadas
    a, b = r["1"], r["2"]
    assert a["k"] == "obr" and a["road"] == "N-400" and a["pk"] == "37.3" and a["mun"] == "Ontígola" and "x1" in a
    assert b["k"] == "ret" and b["c"] == "Retención de 3 km" and "x1" not in b


def test_kind_of():
    assert tr.kind_of("Accident") == "acc" and tr.kind_of("AbnormalTraffic") == "ret"
    assert tr.kind_of("RoadOrCarriagewayOrLaneManagement") == "cor" and tr.kind_of("RoadOrCarriagewayOrLaneManagement", "roadmaintenance") == "obr"
    assert tr.kind_of("SpeedManagement") == "vel" and tr.kind_of("GenericSituationRecord") == "otr"


def test_cercanas_ordenadas():
    items = tr.parse(XML, now=1.8e9)
    x, y = tr.project(40.4, -3.7)
    d = tr.near(items, x, y, 5)
    assert [i["id"] for _, i in d] == ["2"] and d[0][0] < 0.01
    assert [i["id"] for _, i in tr.near(items, x, y, 100, kinds={"obr"})] == ["1"]


def test_refresh_con_opener_falso(tmp_path):
    t = tr.Traffic(str(tmp_path / "t.json"), opener=lambda: XML)
    t.refresh()
    a = t.api()
    assert a["ready"] and a["status"]["n"] == 2 and tr.Traffic(str(tmp_path / "t.json")).items
