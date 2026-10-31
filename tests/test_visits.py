import os, tempfile
from visits import Visits

UA = "Mozilla/5.0 (X11; Linux) Chrome/120"

def test_cuenta_visitas_y_unicos():
    v = Visits(os.path.join(tempfile.mkdtemp(), "v.json"))
    assert v.hit("1.1.1.1", UA, 1000) and v.hit("1.1.1.1", UA, 1001) and v.hit("2.2.2.2", UA, 1002)
    d = v.days[next(iter(v.days))]
    assert d == {"v": 3, "u": 2}

def test_ignora_robots_y_no_guarda_ip():
    p = os.path.join(tempfile.mkdtemp(), "v.json")
    v = Visits(p)
    assert not v.hit("1.1.1.1", "Googlebot/2.1") and not v.hit("1.1.1.1", "")
    v.hit("9.9.9.9", UA); v.save()
    assert "9.9.9.9" not in open(p).read()
    assert Visits(p).api()["total"]["visitas"] == 1
