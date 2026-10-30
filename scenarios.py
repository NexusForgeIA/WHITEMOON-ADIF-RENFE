"""Fallos inyectables para demostrar cada barrera. La red real suele estar sana;
aquí se provocan situaciones peligrosas sobre la captura para ver actuar el sistema."""
import math

K = 1.2  # km por px

LIST = [
    ("seguimiento", "Alcance en misma vía", "Un tren a 250 km/h se aproxima a otro a 120 km/h con solo 1,4 km de separación (Zaragoza→Lleida)."),
    ("convoy_3km", "Dos trenes a 2,5 km (alerta a cabinas)", "Dos trenes a 160 km/h separados 2,5 km en el mismo tramo. B3/B4 los dan por seguros; la regla de 3 km dispara la alarma roja en ambas tablets."),
    ("exceso_velocidad", "Exceso en aproximación", "Un tren a 300 km/h a 2 km de su estación término (Sevilla)."),
    ("atp_aislado", "ATP aislado en línea LZB", "Un tren circula con el ATP aislado en Ciudad Real→Córdoba: sin frenado automático de a bordo."),
    ("atp_discrepancia", "ATP no interviene", "260 km/h con velocidad supervisada de 200 y sin intervención del ATP (¿ATP degradado o dato erróneo?)."),
    ("via_unica", "Sentidos opuestos, vía única", "Dos trenes enfrentados en el tramo Las Mellizas↔Álora, marcado como vía única."),
    ("datos_congelados", "Posiciones caducadas", "Dos servicios dejan de actualizar su posición (pérdida de GPS/telemetría)."),
    ("salto_gps", "Salto de posición", "El GPS de un tren salta 84 km en un ciclo."),
    ("fallo_barrera", "Fallo de la barrera B3", "La barrera de separación lanza una excepción: el sistema debe degradar hacia lo restrictivo."),
    ("supervisor_ciego", "Pérdida total del feed", "Se corta la recepción de posiciones: watchdog y degradado."),
]


def _along(est, a, b, frac=None, back_km=None):
    ax, ay, bx, by = est[a]["x"], est[a]["y"], est[b]["x"], est[b]["y"]
    L = math.hypot(bx - ax, by - ay)
    ux, uy = (bx - ax) / L, (by - ay) / L
    if frac is not None:
        return ax + ux * L * frac, ay + uy * L * frac, ux, uy, L
    return bx - ux * back_km / K, by - uy * back_km / K, ux, uy, L


def _tr(n, p, x, y, kmh, ux, uy, a, s, des, mat, op="demo-a"):
    v = kmh / 3600 / K
    return dict(n=n, p=p, x=x, y=y, kmh=kmh, vx=ux * v, vy=uy * v, ret=0, ant=a, sig=s,
                ori=a, des=des, mat=mat, ts=0, op=op)


def synthetic(sid, est):
    if sid == "seguimiento":
        a, b = "04040", "78400"
        fx, fy, ux, uy, L = _along(est, a, b, frac=0.5)
        rx, ry = fx - ux * 1.4 / K, fy - uy * 1.4 / K
        return [_tr("T-9003", 2, fx, fy, 120, ux, uy, a, b, b, "SIM-A", "demo-a"),
                _tr("T-9004", 2, rx, ry, 250, ux, uy, a, b, b, "SIM-B", "demo-b")]
    if sid == "convoy_3km":
        a, b = "04040", "78400"
        fx, fy, ux, uy, L = _along(est, a, b, frac=0.62)
        rx, ry = fx - ux * 2.5 / K, fy - uy * 2.5 / K
        return [_tr("T-9009", 2, fx, fy, 160, ux, uy, a, b, b, "SIM-F", "demo-a"),
                _tr("T-9010", 2, rx, ry, 160, ux, uy, a, b, b, "SIM-G", "demo-b")]
    if sid == "exceso_velocidad":
        x, y, ux, uy, _ = _along(est, "50600", "51003", back_km=2.0)
        return [_tr("T-9002", 2, x, y, 300, ux, uy, "50600", "51003", "51003", "SIM-C", "demo-a")]
    if sid == "atp_aislado":
        x, y, ux, uy, _ = _along(est, "37200", "50500", frac=0.5)
        return [_tr("T-9007", 2, x, y, 250, ux, uy, "37200", "50500", "51003", "SIM-H", "demo-a")]
    if sid == "atp_discrepancia":
        x, y, ux, uy, _ = _along(est, "50500", "51003", frac=0.4)
        return [_tr("T-9008", 2, x, y, 260, ux, uy, "50500", "51003", "51003", "SIM-I", "demo-b")]
    if sid == "via_unica":
        x1, y1, ux, uy, _ = _along(est, "54404", "54405", frac=0.45)
        x2, y2, vx, vy, _ = _along(est, "54405", "54404", frac=0.45)
        return [_tr("T-9005", 16, x1, y1, 70, ux, uy, "54404", "54405", "54405", "SIM-D", "demo-a"),
                _tr("T-9006", 16, x2, y2, 70, vx, vy, "54405", "54404", "54404", "SIM-E", "demo-b")]
    return []


def frozen(sid):
    return {"04515": 200, "04314": 200} if sid == "datos_congelados" else {}


def atp(sid):
    """Telemetría ATP de a bordo de los trenes sintéticos."""
    if sid == "atp_aislado":
        return {"T-9007": {"system": "LZB", "mode": "IS", "protected": False, "intervention": False, "supervised_kmh": None}}
    if sid == "atp_discrepancia":
        return {"T-9008": {"system": "LZB", "mode": "FS", "protected": True, "intervention": False, "supervised_kmh": 200}}
    return {}


def once(sid, sim):
    if sid == "salto_gps" and "12682" in sim:
        sim["12682"]["x"] += 70
