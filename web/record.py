#!/usr/bin/env python3
"""Graba ejecuciones REALES del motor (engine.py + server.App) para la web estática de demostración.

Reloj simulado (determinista): 1 fotograma = 2 s de simulación. Por cada escenario se guardan las cuatro vistas
(nacional + los tres centros) y el estado de las tablets demo. Lo estático (estaciones, vías, operadores) va aparte.
Uso:  python3 web/record.py            -> web/rec/*.json
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import server  # noqa: E402
import scenarios  # noqa: E402

STEP, FRAMES, T0 = 2, 50, 1_793_366_000.0
VIEWS = ("nacional", "madrid", "barcelona", "sevilla")
TABLET_SETS = {"convoy_3km": ("T-9009", "T-9010"), "seguimiento": ("T-9003", "T-9004"), "via_unica": ("T-9005", "T-9006")}
clock = [T0]
server.time.time = lambda: clock[0]          # el módulo time es compartido: todo el motor usa este reloj
STATIC_KEYS = ("stations", "corridors", "operators", "scenarios", "drivers")


def rnd(o, nd=3):
    if isinstance(o, float):
        return round(o, nd)
    if isinstance(o, dict):
        return {k: rnd(v, nd) for k, v in o.items()}
    if isinstance(o, list):
        return [rnd(v, nd) for v in o]
    return o


def record(sid):
    clock[0] = T0
    a = server.App()
    a.engine.log_path = None                     # no ensuciar data/events.jsonl
    for _ in range(4):                           # la red ya está en marcha cuando se inyecta el fallo (como en vivo)
        clock[0] += 1
        a.tick()
        a.prox_tick()
    if sid:
        a.set_scenario(sid, True)
    frames, static, ev_table, ev_ix = [], {}, [], {}

    def ev_ids(events):                          # tabla única de eventos; cada vista guarda solo índices
        out = []
        for e in events:
            k = (e["t"], e["kind"], e["msg"])
            if k not in ev_ix:
                ev_ix[k] = len(ev_table)
                ev_table.append(e)
            out.append(ev_ix[k])
        return out

    TABLETS = TABLET_SETS.get(sid, ())
    use_tablets = bool(TABLETS)
    recs = {t: a.auth_tablet(f"demo-{t}", "rec")[0] for t in TABLETS}
    for i in range(FRAMES):
        for _ in range(STEP):                    # 1 ciclo por segundo simulado (feed + proximidad)
            clock[0] += 1
            a.tick()
            if use_tablets:
                for t in TABLETS:
                    a.tablet_pos(recs[t], {"demo": True})
            a.prox_tick()
        views = {v: a.centre_snapshot(v) for v in VIEWS[1:]}   # primero los centros: así constan conectados
        views["nacional"] = a.snapshot()
        fr = {"t": int(clock[0] * 1000)}
        for v, s in views.items():
            if i == 0:
                static[v] = {k: s.get(k) for k in STATIC_KEYS}
            d = {k: val for k, val in s.items() if k not in STATIC_KEYS and k != "events"}
            d["ev"] = ev_ids(s["events"])
            d["op_counts"] = {o["id"]: o["trains"] for o in s["operators"] if o["trains"]}
            if v != "nacional":                  # lo común se toma del nacional al reproducir
                d["tr"] = [t["n"] for t in s["trains"]]
                d["inc"] = [t["n"] for t in s["trains"] if t.get("incoming")]
                for k in ("trains", "barriers", "centres", "segments"):
                    d.pop(k, None)
            fr[v] = d
        if use_tablets:
            fr["tablets"] = {t: a.tablet_pos(recs[t], {"demo": True})[1] for t in TABLETS}
        frames.append(fr)
    return {"sid": sid, "step_s": STEP, "static": static, "events": ev_table, "frames": frames}


if __name__ == "__main__":
    out = os.path.join(ROOT, "web", "rec")
    os.makedirs(out, exist_ok=True)
    total = 0
    for sid in [None] + [s[0] for s in scenarios.LIST]:
        r = rnd(record(sid))
        name = sid or "base"
        raw = json.dumps(r, ensure_ascii=False, separators=(",", ":"))
        open(os.path.join(out, f"{name}.json"), "w", encoding="utf-8").write(raw)
        total += len(raw)
        print(f"{name:18s} {len(raw)/1024:7.0f} KB")
    print(f"TOTAL {total/1024/1024:.1f} MB")
