"""Alerta de proximidad entre trenes (regla de los 3 km) para las tablets de cabina.

Dos modos (cfg["proximity_mode"]):
  relevant (por defecto): ROJO solo si a <3 km hay conflicto real de vía: mismo tramo y sentido,
      vía única, convergencia en la misma estación, o alineación frontal/trasera con topología
      desconocida (fail-safe). Cruces en vía doble y zonas de estación -> ÁMBAR (aviso mudo).
  strict: ROJO para cualquier par a <3 km (salvo ambos parados o composición acoplada).
Motivo: en red real hay cientos de pares a <3 km sin riesgo (cruces en vía doble, andenes). Una alarma
que suena sin motivo se ignora; la fatiga de alarmas es en sí un riesgo.
"""
import math


def bearing(dx, dy):
    """Rumbo compás (0=N, 90=E) de un vector con x al este e y al sur."""
    return (math.degrees(math.atan2(dx, -dy)) + 360) % 360


def evaluate(trains, pos, cfg, single):
    R = cfg["proximity_km"] * 1.1          # banda de histéresis
    strict = cfg.get("proximity_mode") == "strict"
    out = []
    ts = sorted(trains, key=lambda t: pos[t.n][0])
    for i, a in enumerate(ts):
        ax, ay, src_a = pos[a.n]
        for b in ts[i + 1:]:
            bx, by, src_b = pos[b.n]
            if bx - ax > R:
                break
            d = math.hypot(bx - ax, by - ay)
            if d >= R or d == 0 and a.mat == b.mat:
                continue
            if (a.mat and a.mat == b.mat) or (a.kmh < 5 and b.kmh < 5):
                continue
            rx, ry = ((bx - ax) / d, (by - ay) / d) if d else (1.0, 0.0)
            closing = ((a.vx - b.vx) * rx + (a.vy - b.vy) * ry) * 3600
            ha, hb = a.heading(), b.heading()
            da, db = a.directed(), b.directed()
            sa, sb = a.undirected(), b.undirected()
            reason, red = "tren cercano / cruce en vía doble", False
            if da and da == db:
                red, reason = True, "mismo tramo y sentido"
            elif sa and sa == sb and tuple(sorted(sa)) in single:
                red, reason = True, "vía única"
            elif a.sig and a.sig == b.sig and a.moving and b.moving and da != db:
                red, reason = True, "convergen en la misma estación"
            elif (da is None or db is None) and ha and hb:
                dot = ha[0] * hb[0] + ha[1] * hb[1]
                lateral = abs(rx * ha[1] - ry * ha[0]) * d
                if lateral < 0.5 and (dot > 0.7 or (dot < -0.7 and closing > 0)):
                    red, reason = True, "misma alineación (topología desconocida)"
            if strict and not red:
                red, reason = True, "estricto: <3 km"
            out.append({"a": a.n, "b": b.n, "dist_km": round(d, 3), "level": "RED" if red else "AMBER",
                        "reason": reason, "closing_kmh": round(closing), "a_xy": (ax, ay), "b_xy": (bx, by),
                        "src_a": src_a, "src_b": src_b, "ha": ha, "hb": hb})
    return out
