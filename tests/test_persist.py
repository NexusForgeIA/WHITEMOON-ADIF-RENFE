import gzip, json, os
import persist as ps


class Fake(ps.Remote):
    """Sustituye a Supabase con un diccionario: misma lógica de trozos y de metadatos."""
    def __init__(self):
        super().__init__("http://x", "anon", "s")
        self.db = {}

    def rpc(self, fn, b):
        n = b["p_name"]
        if fn == "rg_put":
            d = self.db.setdefault(n, {})
            d[b["p_part"]] = (b["p_total"], b["p_data"])
            for k in [k for k in d if k >= b["p_total"]]:
                del d[k]
            return None
        d = self.db.get(n, {})
        if fn == "rg_meta":
            return {"parts": max(v[0] for v in d.values()), "have": len(d)} if d else {"parts": None, "have": 0}
        return d[b["p_part"]][1] if b["p_part"] in d else None


def test_ida_y_vuelta_con_varios_trozos(monkeypatch):
    monkeypatch.setattr(ps, "CHUNK", 50)
    r, raw = Fake(), os.urandom(900)
    assert r.put("infra", raw) > 3
    assert r.get("infra") == raw


def test_regrabar_con_menos_trozos_no_deja_restos(monkeypatch):
    monkeypatch.setattr(ps, "CHUNK", 50)
    r = Fake()
    r.put("a", os.urandom(900))
    r.put("a", b"corto")
    assert r.get("a") == b"corto" and len(r.db["a"]) == 1


def test_restaura_solo_lo_que_falta_y_sube_solo_lo_cambiado(tmp_path):
    r = Fake()
    f1, f2 = str(tmp_path / "a.json"), str(tmp_path / "b.json")
    r.put("a", b'{"x":1}')
    open(f2, "w").write('{"local":true}')
    s = ps.Sync(r, {f1: "a", f2: "b"}, log=lambda *a: None)
    assert s.restore() == 1 and json.load(open(f1)) == {"x": 1} and json.load(open(f2)) == {"local": True}
    assert s.backup() == 1 and r.get("b") == b'{"local":true}'      # a ya coincide con lo restaurado
    assert s.backup() == 0
    open(f1, "w").write('{"x":2}')
    assert s.backup() == 1 and r.get("a") == b'{"x":2}'


def test_fallo_remoto_no_rompe(tmp_path):
    class Roto(Fake):
        def rpc(self, *a):
            raise OSError("sin red")
    s = ps.Sync(Roto(), {str(tmp_path / "z.json"): "z"}, log=lambda *a: None)
    assert s.restore() == 0
    open(tmp_path / "z.json", "w").write("{}")
    assert s.backup() == 0


def test_sin_variables_no_hay_remoto():
    assert ps.from_env({}) is None and ps.from_env({"RG_SUPABASE_URL": "u"}) is None
