"""Copia de seguridad de las cachés en Supabase, para que sobrevivan a los reinicios de Render (disco efímero).

Solo guarda datos públicos (infraestructura, LTV, emergencias, puntualidad). Habla con funciones rg_* (SECURITY DEFINER) que
exigen un secreto propio de RailGuard: NO se usa la clave service_role del proyecto. Sin variables de entorno no hace nada.
Variables: RG_SUPABASE_URL, RG_SUPABASE_ANON (clave pública), RG_SUPABASE_SECRET.
"""
import base64, gzip, json, os, threading, time, urllib.request

CHUNK = 900_000          # caracteres base64 por trozo (la función admite hasta 2 000 000)


class Remote:
    def __init__(self, url, anon, secret, timeout=40):
        self.url, self.anon, self.secret, self.timeout = url.rstrip("/"), anon, secret, timeout

    def rpc(self, fn, body):
        req = urllib.request.Request(f"{self.url}/rest/v1/rpc/{fn}", data=json.dumps({"p_secret": self.secret, **body}).encode(),
                                     headers={"apikey": self.anon, "Authorization": f"Bearer {self.anon}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            txt = r.read().decode()
        return json.loads(txt) if txt else None

    def put(self, name, raw):
        b64 = base64.b64encode(gzip.compress(raw, 6)).decode()
        parts = [b64[i:i + CHUNK] for i in range(0, len(b64), CHUNK)] or [""]
        for i, c in enumerate(parts):
            self.rpc("rg_put", {"p_name": name, "p_part": i, "p_total": len(parts), "p_data": c})
        return len(parts)

    def get(self, name):
        m = self.rpc("rg_meta", {"p_name": name})
        if not m or not m.get("parts") or m.get("have") != m.get("parts"):
            return None
        b64 = "".join(self.rpc("rg_get_part", {"p_name": name, "p_part": i}) or "" for i in range(m["parts"]))
        return gzip.decompress(base64.b64decode(b64))


def from_env(env=None):
    e = env or os.environ
    if e.get("RG_SUPABASE_URL") and e.get("RG_SUPABASE_ANON") and e.get("RG_SUPABASE_SECRET"):
        return Remote(e["RG_SUPABASE_URL"], e["RG_SUPABASE_ANON"], e["RG_SUPABASE_SECRET"])
    return None


class Sync:
    """files: {ruta_local: nombre_remoto}. restore() baja lo que falte; start() sube en segundo plano lo que cambie."""
    def __init__(self, remote, files, period=300, log=print):
        self.r, self.files, self.period, self.log = remote, files, period, log
        self.sent = {}

    def restore(self):
        n = 0
        for path, name in self.files.items():
            if os.path.exists(path):
                continue
            try:
                raw = self.r.get(name)
                if raw:
                    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
                    open(path, "wb").write(raw)
                    self.sent[path] = self._sig(path)
                    n += 1
                    self.log(f"[persist] restaurado {name} ({len(raw) // 1024} KB)")
            except Exception as ex:
                self.log(f"[persist] no se pudo restaurar {name}: {ex!r}"[:200])
        return n

    @staticmethod
    def _sig(path):
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)

    def backup(self):
        n = 0
        for path, name in self.files.items():
            try:
                if not os.path.exists(path) or self.sent.get(path) == self._sig(path):
                    continue
                sig = self._sig(path)
                parts = self.r.put(name, open(path, "rb").read())
                self.sent[path] = sig
                n += 1
                self.log(f"[persist] guardado {name} ({parts} trozos)")
            except Exception as ex:
                self.log(f"[persist] no se pudo guardar {name}: {ex!r}"[:200])
        return n

    def start(self):
        def loop():
            while True:
                time.sleep(self.period)
                self.backup()
        threading.Thread(target=loop, daemon=True, name="persist").start()
