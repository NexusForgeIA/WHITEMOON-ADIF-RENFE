import emergency as em

EL = [
    {"type": "node", "id": 1, "lat": 40.4, "lon": -3.7, "tags": {"amenity": "police", "name": "Cuartel de la Guardia Civil", "addr:street": "Calle Mayor", "addr:housenumber": "5", "phone": "+34 91 000 00 00; 062"}},
    {"type": "way", "id": 2, "center": {"lat": 40.5, "lon": -3.6}, "tags": {"amenity": "police", "operator": "Guardia Civil", "name": "Puesto de X"}},
    {"type": "node", "id": 3, "lat": 40.41, "lon": -3.71, "tags": {"amenity": "social_facility", "operator": "Cruz Roja Española", "name": "Asamblea local"}},
    {"type": "node", "id": 4, "lat": 40.4, "lon": -3.7, "tags": {"amenity": "police", "name": "Policía Local"}},       # no es GC
    {"type": "node", "id": 5, "lat": 40.4, "lon": -3.7, "tags": {"amenity": "pharmacy", "name": "Cruz Roja Farmacia"}},  # farmacia: no es una sede de Cruz Roja
    {"type": "node", "id": 1, "lat": 40.4, "lon": -3.7, "tags": {"amenity": "police", "name": "Cuartel de la Guardia Civil"}},  # duplicado
    {"type": "node", "id": 6, "tags": {"amenity": "police", "operator": "Guardia Civil"}},                              # sin coordenadas
]


def test_parse_clasifica_y_descarta():
    r = em.parse(EL)
    ks = sorted((i["id"], i["k"]) for i in r)
    assert ks == [("n1", "gc"), ("n3", "cr"), ("w2", "gc")]
    a = next(i for i in r if i["id"] == "n1")
    assert a["a"] == "Calle Mayor 5" and a["t"] == "+34 91 000 00 00"


def test_cercanos_por_tipo():
    r = em.parse(EL)
    d, it = em.nearest(r, *em.project(40.41, -3.71), "cr")[0]
    assert it["id"] == "n3" and d < 0.5
    assert em.nearest(r, 0, 0, "gc", 2)[0][1]["k"] == "gc" and len(em.nearest(r, 0, 0, "gc", 5)) == 2


def test_refresh_con_opener_falso(tmp_path):
    e = em.Emergency(str(tmp_path / "c.json"), opener=lambda ep, q: {"elements": EL[:3]})
    e.refresh()
    s = e.api()
    assert s["ready"] and s["status"]["gc"] == 2 and s["status"]["cr"] == 1
    assert em.Emergency(str(tmp_path / "c.json")).items      # persiste en caché
