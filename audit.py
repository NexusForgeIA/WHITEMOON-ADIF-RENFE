"""Registro de auditoría encadenado: cada evento lleva el hash del anterior (SHA-256), de modo que alterar, borrar o reordenar
cualquier registro rompe la cadena y se detecta con verify(). Es evidencia de integridad, no de autoría: no hay firma de personas.

Formato (una línea JSON por registro): {"seq": n, "prev": "<hash anterior>", "hash": "<hash>", "e": {evento}}
hash = SHA-256( prev + "|" + seq + "|" + JSON canónico del evento ). El primero parte de GENESIS.
Si el fichero supera MAX_BYTES se descartan los registros más antiguos; el primero conservado guarda su «prev» como ancla.
"""
import hashlib
import json
import os
import threading

GENESIS = "0" * 64
MAX_BYTES = 6_000_000


def _canon(e):
    return json.dumps(e, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(prev, seq, e):
    return hashlib.sha256(f"{prev}|{seq}|{_canon(e)}".encode("utf-8")).hexdigest()


class Audit:
    def __init__(self, path, max_bytes=MAX_BYTES):
        self.path, self.max_bytes = path, max_bytes
        self.lock = threading.Lock()
        self.seq, self.head = 0, GENESIS
        self._load_tail()

    def _load_tail(self):
        try:
            last = None
            with open(self.path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        last = line
            if last:
                r = json.loads(last)
                self.seq, self.head = int(r["seq"]), r["hash"]
        except (OSError, ValueError, KeyError):
            pass

    def append(self, e):
        with self.lock:
            self.seq += 1
            h = _hash(self.head, self.seq, e)
            rec = {"seq": self.seq, "prev": self.head, "hash": h, "e": e}
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
            self.head = h
            try:
                if os.path.getsize(self.path) > self.max_bytes:
                    self._rotate()
            except OSError:
                pass
            return rec

    def _rotate(self):
        with open(self.path, "r", encoding="utf-8") as f:
            lines = [l for l in f if l.strip()]
        keep = lines[len(lines) // 2:]
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.writelines(keep)
        os.replace(tmp, self.path)

    def records(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        yield json.loads(line)
        except OSError:
            return

    def verify(self):
        """Recorre toda la cadena. ok=False indica el primer registro que no encaja (seq) y por qué."""
        n, prev, first = 0, None, None
        with self.lock:
            try:
                for r in self.records():
                    if first is None:
                        first, prev = r["seq"], r["prev"]          # ancla: el primero conservado fija su «prev»
                    if r["prev"] != prev:
                        return {"ok": False, "n": n, "bad_seq": r["seq"], "why": "enlace roto (falta o sobra un registro)"}
                    if r["hash"] != _hash(r["prev"], r["seq"], r["e"]):
                        return {"ok": False, "n": n, "bad_seq": r["seq"], "why": "contenido alterado"}
                    prev, n = r["hash"], n + 1
            except (ValueError, KeyError):
                return {"ok": False, "n": n, "bad_seq": None, "why": "línea ilegible"}
            if n and prev != self.head:
                return {"ok": False, "n": n, "bad_seq": None, "why": "el último registro no coincide con la cabeza de la cadena"}
        return {"ok": True, "n": n, "first_seq": first, "last_seq": self.seq, "head": self.head}

    def export(self, t_from=None, t_to=None, limit=5000):
        out = []
        for r in self.records():
            t = r["e"].get("t", 0)
            if (t_from is None or t >= t_from) and (t_to is None or t <= t_to):
                out.append(r)
        return out[-limit:]
