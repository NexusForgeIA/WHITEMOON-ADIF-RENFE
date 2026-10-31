"""Contador de visitas sin IP y sin cookies.

Guarda solo totales por día (visitas y visitantes únicos). La IP y el navegador se usan únicamente para calcular, en memoria,
un hash con sal aleatoria que cambia cada día y no se guarda nunca: sirve para no contar dos veces al mismo visitante en un día
y no permite identificar a nadie. Al reiniciar el servidor se pierde esa lista de huellas (el total de visitas no)."""
import hashlib, json, os, re, secrets, threading, time

BOT = re.compile(r"bot|crawl|spider|slurp|headless|lighthouse|preview|monitor|uptime|curl|python|wget", re.I)


class Visits:
    def __init__(self, path, keep_days=400):
        self.path, self.keep, self.lock = path, keep_days, threading.Lock()
        self.days = {}
        self.salt, self.seen, self.day = secrets.token_hex(8), set(), None
        try:
            self.days = json.load(open(path)).get("days", {})
        except Exception:
            pass

    def hit(self, ip, ua, now=None):
        """Cuenta una visita. Devuelve False si es un robot."""
        if not ua or BOT.search(ua):
            return False
        d = time.strftime("%Y-%m-%d", time.localtime(now or time.time()))
        with self.lock:
            if d != self.day:
                self.day, self.salt, self.seen = d, secrets.token_hex(8), set()
            h = hashlib.sha256(f"{self.salt}|{ip}|{ua}".encode()).hexdigest()[:16]
            rec = self.days.setdefault(d, {"v": 0, "u": 0})
            rec["v"] += 1
            if h not in self.seen:
                self.seen.add(h)
                rec["u"] += 1
            for old in sorted(self.days)[:-self.keep]:
                del self.days[old]
        return True

    def save(self):
        with self.lock:
            data = json.dumps({"days": self.days})
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        open(self.path + ".tmp", "w").write(data)
        os.replace(self.path + ".tmp", self.path)

    def api(self, today=None):
        d = today or time.strftime("%Y-%m-%d")
        ks = sorted(self.days)[-30:]
        tot = lambda f: sum(self.days[k][f] for k in ks)
        t = self.days.get(d, {"v": 0, "u": 0})
        return {"hoy": {"visitas": t["v"], "visitantes": t["u"]},
                "30_dias": {"visitas": tot("v"), "visitantes_dia_sumados": tot("u")},
                "total": {"visitas": sum(r["v"] for r in self.days.values())},
                "por_dia": [{"dia": k, "visitas": self.days[k]["v"], "visitantes": self.days[k]["u"]} for k in ks],
                "nota": "Sin IP ni cookies. «Visitantes» = huellas distintas por día (se reinicia si el servidor se reinicia)."}
