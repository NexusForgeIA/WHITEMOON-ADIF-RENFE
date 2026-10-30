"""Centros de control regionales (Madrid-Atocha, Barcelona, Sevilla) + centro nacional.

Cada trazado de zona, token y latido vive aquí; el ámbito de lo que ve y puede hacer cada centro lo aplica server.py.
Reglas: añadir restricciones = cualquier centro sobre cualquier tren; rearmar/liberar = solo el centro de la zona
(o el nacional). Un centro que deja de dar señales de vida, o una situación crítica sin confirmar, se escala a todos.
Solo se guarda el HASH de los tokens.
"""
import hashlib
import json
import math
import os
import secrets
import time
from collections import deque

LAT_N, LON_W, KM_LAT, KM_LON = 44.0, -10.0, 111.19, 111.32 * math.cos(math.radians(40.0))
NATIONAL = "nacional"
STICKY_KM = 5.0   # un tren solo cambia de zona si el nuevo centro le queda 5 km más cerca (evita parpadeo en la frontera)


def project(lat, lon):
    return (lon - LON_W) * KM_LON, (LAT_N - lat) * KM_LAT


def _h(t):
    return hashlib.sha256(t.encode()).hexdigest()


class Centres:
    def __init__(self, cfg_path, auth_path, offline_s=30):
        cfg = json.load(open(cfg_path, encoding="utf-8"))
        self.nat = cfg["national"]
        self.border_km = cfg.get("border_km", 40)
        self.c = {c["id"]: {**c, "xy": project(c["lat"], c["lon"])} for c in cfg["centres"]}
        self.auth_path = auth_path
        self.tokens = json.load(open(auth_path, encoding="utf-8")) if os.path.exists(auth_path) else {}
        self.demo = {}
        self.offline_s = offline_s
        self.seen = {}
        self.sticky = {}
        self.messages = deque(maxlen=200)

    # ---- identidad ----
    def name(self, cid):
        return self.nat["name"] if cid == NATIONAL else self.c.get(cid, {}).get("name", cid)

    def add_demo(self, token, cid):
        self.demo[_h(token)] = cid

    def issue(self, cid):
        if cid not in self.c and cid != NATIONAL:
            return None
        for h, c in list(self.tokens.items()):
            if c == cid:
                del self.tokens[h]
        tok = secrets.token_urlsafe(24)
        self.tokens[_h(tok)] = cid
        os.makedirs(os.path.dirname(self.auth_path), exist_ok=True)
        json.dump(self.tokens, open(self.auth_path, "w", encoding="utf-8"))
        return tok

    def auth(self, token):
        return (self.tokens.get(_h(token)) or self.demo.get(_h(token))) if token else None

    # ---- zonas ----
    def assign(self, n, x, y):
        """Devuelve (centro, centro_vecino_si_está_en_frontera|None, km_al_centro)."""
        d = sorted((math.hypot(x - c["xy"][0], y - c["xy"][1]), cid) for cid, c in self.c.items())
        best = d[0][1]
        cur = self.sticky.get(n)
        if cur in self.c:
            dc = next(dd for dd, cid in d if cid == cur)
            if dc - d[0][0] <= STICKY_KM:
                best = cur
        self.sticky[n] = best
        other = next(((dd, cid) for dd, cid in d if cid != best), None)
        dbest = next(dd for dd, cid in d if cid == best)
        near = other[1] if other and other[0] - dbest < self.border_km else None
        return best, near, dbest

    def nearest(self, x, y):
        return min(self.c, key=lambda cid: math.hypot(x - self.c[cid]["xy"][0], y - self.c[cid]["xy"][1]))

    # ---- latidos ----
    def touch(self, cid, now):
        self.seen[cid] = now

    def online(self, cid, now):
        return now - self.seen.get(cid, -10**12) < self.offline_s * 1000

    def dropped(self, now):
        """Centros que estuvieron conectados en esta sesión y han dejado de dar señales de vida."""
        return [cid for cid in self.c if cid in self.seen and not self.online(cid, now)]

    # ---- mensajería entre centros ----
    def send(self, frm, to, text, now):
        text = (text or "").strip()[:300]
        if not text or (to != "*" and to not in self.c and to != NATIONAL):
            return None
        m = {"t": now, "from": frm, "to": to, "text": text}
        self.messages.appendleft(m)
        return m

    def messages_for(self, cid):
        if cid == NATIONAL:
            return list(self.messages)[:30]
        return [m for m in self.messages if m["to"] in (cid, "*") or m["from"] == cid][:30]
