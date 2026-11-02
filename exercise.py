"""Evaluación de tiempos de respuesta en simulación: por cada fallo inyectado mide detección (sistema), respuesta (primera acción
humana: reconocer, restringir o rearmar) y resolución (condición despejada). Solo se usa en modo simulación, como ejercicio de
entrenamiento; no interviene en las barreras. Cada ejercicio cerrado se anota en el registro de auditoría encadenado."""

GRADES = [(30, "Excelente"), (60, "Bien"), (120, "Aceptable")]
ACTIONS = ("ACK", "MANUAL", "REARM")


def grade(resp_s):
    if resp_s is None:
        return "Sin respuesta"
    for lim, name in GRADES:
        if resp_s < lim:
            return name
    return "Lento"


class Exercises:
    def __init__(self, log=None, keep=20):
        self.log, self.keep = log, keep       # log(kind, msg, **data): anota el resultado (auditoría)
        self.cur = {}                         # id escenario -> ejercicio abierto
        self.done = []

    def start(self, sid, t_ms):
        self.cur[sid] = {"id": sid, "start": t_ms, "detect": None, "resp": None, "resolve": None, "action": None}

    def stop(self, sid, t_ms):
        ex = self.cur.pop(sid, None)
        if ex:
            self._close(ex, t_ms, "retirado")

    def reset(self):
        self.cur.clear()

    def event(self, e):
        """Recibe cada evento del motor (dict con t, kind, msg)."""
        k, t = e.get("kind"), e.get("t", 0)
        if k == "EXERCISE" or not self.cur:
            return
        for ex in list(self.cur.values()):
            if k == "HAZARD" and ex["detect"] is None and t >= ex["start"]:
                ex["detect"] = t
            elif k in ACTIONS and ex["detect"] is not None and ex["resp"] is None and t >= ex["detect"]:
                ex["resp"], ex["action"] = t, k
            elif k == "CLEAR" and ex["detect"] is not None and ex["resolve"] is None and t >= ex["detect"]:
                ex["resolve"] = t
                self.cur.pop(ex["id"], None)
                self._close(ex, t, "resuelto")

    @staticmethod
    def _sec(a, b):
        return None if a is None or b is None else round((b - a) / 1000, 1)

    def _view(self, ex, end, why):
        resp = self._sec(ex["detect"], ex["resp"])
        return {"id": ex["id"], "result": why, "detect_s": self._sec(ex["start"], ex["detect"]), "response_s": resp,
                "resolve_s": self._sec(ex["detect"], ex["resolve"]), "action": ex["action"], "grade": grade(resp), "t": end}

    def _close(self, ex, end, why):
        v = self._view(ex, end, why)
        self.done.insert(0, v)
        del self.done[self.keep:]
        if self.log:
            self.log("EXERCISE", f"Ejercicio {v['id']} ({why}): detección {v['detect_s']} s, respuesta {v['response_s']} s, "
                                 f"resolución {v['resolve_s']} s → {v['grade']}", **{k: v[k] for k in ("id", "detect_s", "response_s", "resolve_s", "grade")})

    def view(self, now_ms):
        run = [{**self._view(ex, now_ms, "en curso"), "elapsed_s": self._sec(ex["start"], now_ms)} for ex in self.cur.values()]
        return {"running": run, "done": self.done}
