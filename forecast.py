"""Previsión en directo de posibles conflictos de marcha (INFORMATIVA).

NO ordena nada y NO forma parte de la cadena de seguridad: las barreras B1–B5 siguen decidiendo con sus propios umbrales.
Esta capa solo adelanta lo que ocurrirá «si nada cambia», para que el operador se anticipe antes de que una barrera tenga que actuar.

Método (deliberadamente simple y explicable): extrapolación a velocidad y rumbo constantes con las posiciones del feed.
Limitaciones: no conoce señales, bloques, estaciones de adelantamiento ni la marcha real; la velocidad de Renfe se deriva
de posiciones GPS y es ruidosa. Por eso solo se emiten previsiones con margen suficiente y con trenes de datos frescos.
"""
import math
from collections import defaultdict

HORIZON_S = 1200        # ventana de previsión: 20 min
MIN_CLOSING_KMH = 25    # cierre mínimo para considerar un alcance (por debajo es ruido de velocidad)
MAX_SANE_KMH = 340
NOTE = ("Extrapolación a velocidad constante con las posiciones del feed. Informativa: no ordena nada y no conoce señales ni "
        "estaciones de adelantamiento. Las barreras B1–B5 actúan con sus propios umbrales.")


def _level(in_s):
    return "PRÓXIMO" if in_s <= 600 else "A VIGILAR"


def predict(engine, horizon_s=HORIZON_S, limit=14):
    cfg, est = engine.cfg, engine.est
    k = cfg["km_per_px"]
    st = {c: (s["x"] * k, s["y"] * k) for c, s in est.items()}
    name = lambda c: est.get(c, {}).get("n", c or "?")
    now = engine.now_ms
    ok = [t for t in engine.trains
          if t.kmh <= MAX_SANE_KMH and (now - t.ts) / 1000 <= cfg["stale_s"]]
    out, pair_seen = [], set()

    def near_station(t, r=None):
        r = r or cfg["station_radius_km"]
        return any(math.hypot(t.x - sx, t.y - sy) < r for sx, sy in st.values())

    groups = defaultdict(list)
    for t in ok:
        d = t.directed()
        if d and d[0] in st and d[1] in st:
            groups[d].append(t)

    # 1) ALCANCE en el mismo tramo y sentido
    for d, ts in groups.items():
        if len(ts) < 2:
            continue
        a, b = st[d[0]], st[d[1]]
        L = math.hypot(b[0] - a[0], b[1] - a[1]) or 1e-9
        ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
        pos = lambda t: (t.x - a[0]) * ux + (t.y - a[1]) * uy
        ts = sorted(ts, key=pos)
        for rear, front in zip(ts, ts[1:]):
            if rear.mat and rear.mat == front.mat:
                continue
            closing = rear.kmh - front.kmh
            gap = pos(front) - pos(rear)
            if closing < MIN_CLOSING_KMH or gap <= 0 or not rear.moving:
                continue
            if not front.moving and near_station(front):
                continue   # parado en estación: servicio normal, no un obstáculo
            t_close = gap / (closing / 3600)
            eta_end = math.hypot(rear.x - b[0], rear.y - b[1]) / max(rear.kmh / 3600, 1e-6)
            if t_close > horizon_s or t_close > eta_end * 1.1:
                continue   # no llegaría a alcanzarlo antes de la estación: lo cubre «llegada simultánea»
            b4 = t_close - cfg["ttc_restrict_s"]
            stp = t_close - cfg["ttc_stop_s"]
            then = ("B4 restringirá en ≈%d min y ordenaría STOP en ≈%d min" % (max(0, round(b4 / 60)), max(0, round(stp / 60)))
                    if b4 > 0 else "ya está dentro de la ventana de actuación de B4")
            pair_seen.add(frozenset((rear.n, front.n)))
            out.append({"id": f"CATCH|{rear.n}|{front.n}", "kind": "ALCANCE", "in_s": round(t_close), "level": _level(t_close),
                        "trains": [rear.n, front.n], "seg": f"{name(d[0])} → {name(d[1])}",
                        "msg": f"{rear.n} ({rear.kmh:.0f} km/h) alcanzaría a {front.n} ({front.kmh:.0f} km/h) en ≈{t_close/60:.0f} min; hoy {gap:.1f} km de separación",
                        "then": "Si nada cambia: " + then})

    # 2) LLEGADA SIMULTÁNEA a la misma estación desde tramos distintos
    by_dest = defaultdict(list)
    for t in ok:
        if t.sig in st and t.moving and t.kmh > 20:
            eta = math.hypot(t.x - st[t.sig][0], t.y - st[t.sig][1]) / (t.kmh / 3600)
            if eta < horizon_s:
                by_dest[t.sig].append((eta, t))
    for sig, lst in by_dest.items():
        lst.sort(key=lambda p: p[0])
        for (ea, ta), (eb, tb) in zip(lst, lst[1:]):
            if frozenset((ta.n, tb.n)) in pair_seen or (ta.mat and ta.mat == tb.mat):
                continue
            if ta.directed() == tb.directed():
                continue   # mismo tramo y sentido: ya lo trata el alcance
            diff = abs(eb - ea)
            if diff < 150:
                out.append({"id": f"CONV|{ta.n}|{tb.n}", "kind": "LLEGADA SIMULTÁNEA", "in_s": round(max(ea, eb)), "level": _level(max(ea, eb)),
                            "trains": [ta.n, tb.n], "seg": name(sig),
                            "msg": f"{ta.n} y {tb.n} llegarían a {name(sig)} con {diff:.0f} s de diferencia (≈{max(ea, eb)/60:.0f} min)",
                            "then": "Si nada cambia: posible conflicto de vía o de andén; B4 lo tratará como CONVERGE cuando falten ≈45 s"})

    # 3) SENTIDOS OPUESTOS en vía única
    single = {tuple(sorted(p)) for p in cfg.get("single_track", [])}
    for seg in single:
        fw = [t for t in ok if t.directed() == (seg[0], seg[1])]
        bw = [t for t in ok if t.directed() == (seg[1], seg[0])]
        for x in fw:
            for y in bw:
                v = (x.kmh + y.kmh) / 3600
                if v <= 0:
                    continue
                t_meet = math.hypot(x.x - y.x, x.y - y.y) / v
                if t_meet < horizon_s:
                    out.append({"id": f"HEAD|{x.n}|{y.n}", "kind": "VÍA ÚNICA", "in_s": round(t_meet), "level": _level(t_meet),
                                "trains": [x.n, y.n], "seg": f"{name(seg[0])} ↔ {name(seg[1])}",
                                "msg": f"{x.n} y {y.n} circulan en sentidos opuestos por vía única: se cruzarían en ≈{t_meet/60:.0f} min",
                                "then": "Si nada cambia: B3 ordenaría STOP por sentidos opuestos en vía única"})

    out.sort(key=lambda o: o["in_s"])
    return {"items": out[:limit], "total": len(out), "horizon_s": horizon_s, "note": NOTE}
