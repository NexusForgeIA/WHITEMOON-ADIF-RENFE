"""Vigilancia contextual (INFORMATIVA): reglas sobre trenes, fuentes y eventos externos que avisan de situaciones que merecen atención humana.

Aislada de las barreras B0–B5: no manda ningún comando ni toca el enclavamiento. Son heurísticas sobre datos públicos con decenas de segundos
de latencia, sin señalización ni estado de la vía: sirven para vigilar y dar contexto, no para decisiones de seguridad operativa.
Ideas de reglas inspiradas en el proyecto abierto Radar ES (FlorinTodor/radar-es).
"""
from collections import deque

from renfe_adapter import KM_LAT, KM_LON, LAT_N, LON_W, haversine_km

TH = {
    "stopped_min": 8, "stopped_radius_km": 0.15, "away_station_km": 1.0, "cluster_km": 10,
    "delay_jump_min": 15, "delay_jump_window_min": 15,
    "quake_min_mag": 3.5, "quake_window_h": 3,
    "grid_drop_high": -0.10, "grid_drop_crit": -0.25,
    "fleet_drop_ratio": 0.6, "fleet_min": 50,
    "fire_near_km": 3, "fire_cluster_km": 2, "fire_window_h": 12,
    "feed_max_age_s": 120,        # si el feed de Renfe está parado no se declara «detenido» a nadie: sería una posición congelada
    "track_window_min": 45,
}
ORDER = {"muy alta": 0, "alta": 1, "media": 2, "baja": 3}


def unproject(x, y):
    """Inversa de renfe_adapter.project: (x, y) del mapa → (lat, lon)."""
    return LAT_N - y / KM_LAT, x / KM_LON + LON_W


def point_in_ring(lon, lat, ring):
    """Punto en polígono (trazado de rayos). ring = [(lon, lat), ...]."""
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def _item(id_, type_, sev, title, detail, trains=(), lat=None, lon=None):
    return {"id": id_, "type": type_, "sev": sev, "title": title, "detail": detail, "trains": list(trains), "lat": lat, "lon": lon}


class Watch:
    def __init__(self, th=None):
        self.th = {**TH, **(th or {})}
        self.tracks = {}            # nº tren → deque[(t_ms, lat, lon, ret_min)]; solo se añade un punto si algo cambia
        self.kpis = deque(maxlen=400)

    def record(self, trains, now_ms):
        win = self.th["track_window_min"] * 60_000
        live = set()
        for t in trains:
            lat, lon = unproject(t["x"], t["y"])
            tr = self.tracks.setdefault(t["n"], deque())
            live.add(t["n"])
            ret = t.get("ret") or 0
            if not tr or (tr[-1][1], tr[-1][2]) != (lat, lon) or tr[-1][3] != ret:
                tr.append((now_ms, lat, lon, ret))
            while len(tr) > 1 and now_ms - tr[0][0] > win:
                tr.popleft()
        for n in set(self.tracks) - live:
            del self.tracks[n]
        self.kpis.append((now_ms, len(trains)))

    @staticmethod
    def _stationary_since(tr, radius):
        last = tr[-1]
        since = last[0]
        for p in reversed(tr):
            if haversine_km(p[1], p[2], last[1], last[2]) > radius:
                break
            since = p[0]
        return since

    @staticmethod
    def _nearest_station(lat, lon, stations):
        best = None
        for s in stations.values():
            d = haversine_km(lat, lon, *unproject(s["x"], s["y"]))
            if best is None or d < best[0]:
                best = (d, s["n"])
        return best

    def evaluate(self, trains, stations, now_ms, feed_age_s=0, health=None, extras=None):
        """trains: [{n, x, y, kmh, ret}] (x, y del mapa); stations: {código: {n, x, y}}; health: [{id, name, ok, err, age_s, max_age_s, critical}]."""
        th, out = self.th, []
        self.record(trains, now_ms)
        pos = {t["n"]: unproject(t["x"], t["y"]) for t in trains}
        by_n = {t["n"]: t for t in trains}
        feed_ok = feed_age_s is not None and feed_age_s <= th["feed_max_age_s"]

        stopped = []   # 1-2. Parado fuera de estación y bloqueos
        if feed_ok:
            for n, tr in self.tracks.items():
                if (by_n[n].get("kmh") or 0) > 5:
                    continue
                mins = (now_ms - self._stationary_since(tr, th["stopped_radius_km"])) / 60_000
                if mins < th["stopped_min"]:
                    continue
                near = self._nearest_station(*pos[n], stations) if stations else None
                if near and near[0] <= th["away_station_km"]:
                    continue
                stopped.append((n, mins, near))
                out.append(_item(f"detenido:{n}", "detenido", "alta" if mins >= 20 else "media", f"Tren {n} detenido fuera de estación",
                                 f"Sin moverse desde hace {round(mins)} min" + (f", a {near[0]:.1f} km de {near[1]}" if near else "")
                                 + ". El feed no publica la hora de cada GPS: también puede ser una posición congelada.", [n], *pos[n]))
        used = set()
        for a in stopped:
            if a[0] in used:
                continue
            grp = [b for b in stopped if b[0] not in used and haversine_km(*pos[a[0]], *pos[b[0]]) <= th["cluster_km"]]
            if len(grp) < 2:
                continue
            used.update(g[0] for g in grp)
            la = sum(pos[g[0]][0] for g in grp) / len(grp)
            lo = sum(pos[g[0]][1] for g in grp) / len(grp)
            near = self._nearest_station(la, lo, stations) if stations else None
            out.append(_item("bloqueo:" + "+".join(sorted(g[0] for g in grp)), "bloqueo", "muy alta",
                             f"{len(grp)} trenes detenidos cerca" + (f" de {near[1]}" if near else ""),
                             "Posible corte o incidencia en la vía: " + ", ".join(f"{g[0]} ({round(g[1])} min)" for g in grp) + ".", [g[0] for g in grp], la, lo))

        w0 = now_ms - th["delay_jump_window_min"] * 60_000   # 3. Salto brusco de retraso
        for n, tr in self.tracks.items():
            ref = next((p for p in tr if p[0] >= w0), None)
            now_ret = by_n[n].get("ret") or 0
            if ref and now_ret - ref[3] >= th["delay_jump_min"]:
                out.append(_item(f"salto-retraso:{n}", "salto-retraso", "alta", f"Tren {n}: el retraso sube {now_ret - ref[3]} min de golpe",
                                 f"De {ref[3]} a {now_ret} min en menos de {th['delay_jump_window_min']} min: suele indicar una incidencia en ruta.", [n], *pos[n]))

        ref = next((k for k in self.kpis if 8 * 60_000 <= now_ms - k[0] <= 12 * 60_000), None)   # 4. Caída de flota
        if ref and ref[1] > th["fleet_min"] and len(trains) < ref[1] * th["fleet_drop_ratio"]:
            out.append(_item("flota", "flota", "alta", f"Desaparecen trenes del mapa: {len(trains)} frente a {ref[1]} hace 10 min",
                             "Puede ser una caída de la fuente de datos o una interrupción generalizada del servicio."))

        for h in health or []:   # 5. Fuentes caídas o congeladas
            stale = h.get("age_s") is not None and h.get("max_age_s") and h["age_s"] > h["max_age_s"]
            if h.get("ok") is False or stale:
                out.append(_item(f"fuente:{h['id']}", "fuente", "media" if h.get("critical") else "baja",
                                 f"{h['name']}: " + ("sin respuesta" if h.get("ok") is False else "datos sin actualizar"),
                                 h.get("err") or (f"Sin actualizar desde hace {round(h['age_s'] / 60)} min." if stale else "Un mapa con datos viejos puede engañar.")))

        ex = extras or {}
        r = ex.get("ree")   # 6. Red eléctrica
        if r and r.get("deviation") is not None and r["deviation"] <= th["grid_drop_high"]:
            out.append(_item("red-electrica", "red-electrica", "muy alta" if r["deviation"] <= th["grid_drop_crit"] else "alta",
                             f"Demanda eléctrica {round(r['deviation'] * 100)} % por debajo de lo previsto",
                             f"Real {round(r['demandMW'])} MW frente a {round(r['forecastMW'])} MW previstos. Una caída brusca puede indicar un apagón o un corte grande (estimación de RailGuard con datos de Red Eléctrica)."))
        evs = ex.get("events") or {}
        for e in evs.get("ign", []):   # 7. Terremotos
            if e["mag"] < th["quake_min_mag"] or now_ms - e["t"] > th["quake_window_h"] * 3600_000:
                continue
            radius = 25 * (e["mag"] - 2)
            near = [n for n, p in pos.items() if haversine_km(e["lat"], e["lon"], *p) <= radius]
            out.append(_item("sismo:" + e["id"], "sismo", "muy alta" if e["mag"] >= 4.5 else "alta" if near else "media", e["title"],
                             f"{len(near)} trenes en un radio de {round(radius)} km." if near else f"Sin trenes en un radio de {round(radius)} km.", near, e["lat"], e["lon"]))
        for e in evs.get("aemet", []):   # 8. Avisos meteorológicos naranja/rojo
            if e["level"] not in ("naranja", "rojo") or (e.get("start") and e["start"] > now_ms) or (e.get("end") and e["end"] < now_ms):
                continue
            inside = [n for n, (la, lo) in pos.items() if any(point_in_ring(lo, la, rg) for rg in e["rings"])]
            ring = e["rings"][0]
            out.append(_item("meteo:" + e["id"], "meteo", e["sev"], e["title"] + (f" · {len(inside)} trenes dentro" if inside else ""),
                             (e.get("desc") or "")[:240] + (f" Trenes en la zona: {', '.join(inside[:8])}{'…' if len(inside) > 8 else ''}." if inside else ""), inside,
                             sum(p[1] for p in ring) / len(ring), sum(p[0] for p in ring) / len(ring)))
        fires = [f for f in evs.get("firms", []) if now_ms - f["t"] <= th["fire_window_h"] * 3600_000]   # 9. Focos de calor cerca de trenes
        used = set()
        for f in fires:
            if f["id"] in used:
                continue
            cl = [g for g in fires if g["id"] not in used and haversine_km(f["lat"], f["lon"], g["lat"], g["lon"]) <= th["fire_cluster_km"]]
            used.update(g["id"] for g in cl)
            near = [n for n, p in pos.items() if any(haversine_km(g["lat"], g["lon"], *p) <= th["fire_near_km"] for g in cl)]
            if not near:
                continue
            mx = max(g["frp"] for g in cl)
            out.append(_item("incendio:" + f["id"], "incendio", "alta" if len(cl) >= 3 or mx >= 30 else "media",
                             f"Posible incendio a menos de {th['fire_near_km']} km de {len(near)} {'tren' if len(near) == 1 else 'trenes'}",
                             f"{len(cl)} detecciones por satélite (potencia máx. {round(mx)} MW). Trenes: {', '.join(near[:6])}. Puede ser una fuente de calor industrial: confirmar con fuentes oficiales.",
                             near, f["lat"], f["lon"]))
        out.sort(key=lambda i: (ORDER.get(i["sev"], 9), i["id"]))
        return out
