"""Registro de maquinistas/tablets. Solo se guarda el HASH del token (se muestra una única vez al emitirlo).
Identificador pseudónimo (no nombre real). Las posiciones de las tablets NO se persisten: viven en RAM."""
import hashlib
import json
import os
import secrets
import time


def _h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Drivers:
    def __init__(self, path):
        self.path = path
        self.d = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
        self.demo = {}  # solo en memoria (modo simulación)

    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        json.dump(self.d, open(self.path, "w", encoding="utf-8"), indent=1)

    def issue(self, driver_id, operator, train):
        for h, r in list(self.d.items()):
            if r["id"] == driver_id:
                del self.d[h]  # un token activo por maquinista
        token = secrets.token_urlsafe(24)
        self.d[_h(token)] = {"id": driver_id, "operator": operator, "train": str(train), "created": int(time.time())}
        self._save()
        return token

    def auth(self, token):
        if not token:
            return None
        return self.d.get(_h(token)) or self.demo.get(_h(token))

    def add_demo(self, token, rec):
        self.demo[_h(token)] = rec

    def listing(self):
        return [{"id": r["id"], "operator": r["operator"], "train": r["train"], "created": r["created"]} for r in self.d.values()]

    def revoke(self, driver_id):
        n = len(self.d)
        self.d = {h: r for h, r in self.d.items() if r["id"] != driver_id}
        self._save()
        return n - len(self.d)

    def for_train(self, train):
        return next((r for r in self.d.values() if r["train"] == str(train)), None)
