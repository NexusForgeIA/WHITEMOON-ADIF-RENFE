"""Explicación estructurada de cada peligro («por qué te lo muestro y qué sugiero»). Texto fijo por código de peligro + los datos
medidos que lo disparan. Es una ayuda para la persona operadora, no una orden: la decisión es siempre humana.
`kind` distingue lo MEDIDO (dato directo del feed) de lo INFERIDO (estimación o patrón estadístico)."""

CATALOG = {
    "STALE": ("directo", "La última posición recibida es demasiado antigua: no se sabe en qué vía está el tren.",
              "Una posición sin actualizar más allá del umbral deja la ocupación de vía desconocida.",
              "Confirmar la posición por GSM-R o en el CTC y mantener la restricción hasta recibir una posición nueva."),
    "JUMP": ("directo", "El tren «salta» una distancia físicamente imposible entre dos lecturas.",
             "Un salto mayor que el que permite la velocidad máxima indica un error de GPS o un cambio de identidad del tren.",
             "Tratar la posición como no fiable y verificar con el maquinista por GSM-R."),
    "DUP_POS": ("directo", "Dos servicios distintos comparten posición fuera de estación.",
                "Dos trenes no pueden ocupar el mismo punto de vía; uno de los dos datos es erróneo.",
                "Identificar en el CTC cuál de los dos ocupa realmente esa posición."),
    "SPEED_IMPLAUSIBLE": ("directo", "La velocidad del feed supera lo que puede alcanzar cualquier tren de la red.",
                          "Se trata como dato erróneo, no como exceso real: no se frena por esta lectura.",
                          "No actuar sobre la velocidad; revisar la fuente del dato."),
    "OVERSPEED": ("directo", "La velocidad medida supera el límite de la envolvente de línea.",
                  "Compara la velocidad del feed con el límite de la línea o tramo; solo avisa de forma persistente para evitar ruido del feed.",
                  "Avisar al maquinista por GSM-R y comprobar que reduce; si persiste, limitar la velocidad."),
    "HEADON": ("directo", "Dos trenes en sentidos opuestos en un tramo de vía única.",
               "En vía única la circulación en sentidos contrarios solo es segura si hay un cruce planificado.",
               "Detener ambos trenes y confirmar la ocupación con el CTC antes de autorizar ningún movimiento."),
    "SPACING": ("inferido", "Dos trenes en la misma vía están más cerca de lo necesario para frenar con seguridad.",
                "Distancia real entre trenes menor que la distancia de frenado necesaria a su velocidad.",
                "Reducir la velocidad del tren trasero hasta recuperar la distancia de seguridad."),
    "TTC": ("inferido", "El tren trasero alcanzaría al delantero en pocos segundos si ambos mantienen su marcha.",
            "Tiempo hasta el alcance = distancia / velocidad de cierre; se avisa por debajo del umbral.",
            "Ordenar al tren trasero que reduzca y vigilar la evolución de la distancia."),
    "CONVERGE": ("inferido", "Dos trenes llegarán casi a la vez a la misma estación.",
                 "Las horas estimadas de llegada difieren menos que el margen mínimo entre trenes.",
                 "Decidir la precedencia y retener o regular a uno de los dos antes de la estación."),
    "ATP_STALE": ("directo", "La telemetría del ATP de a bordo está caducada.",
                  "Sin datos recientes no se puede asegurar que el sistema de protección siga activo.",
                  "Solicitar al maquinista confirmación del estado del ATP."),
    "ATP_ISOLATED": ("directo", "El tren circula con el ATP aislado: sin protección automática.",
                     "Con el ATP aislado, la protección contra el exceso de velocidad depende solo del maquinista.",
                     "Informar al CTC, aplicar las condiciones de marcha para ATP aislado y vigilar la velocidad."),
    "ATP_BRAKING": ("directo", "El ATP ha intervenido con un freno automático.",
                    "Una intervención del ATP indica que se alcanzó un límite supervisado.",
                    "Confirmar con el maquinista el motivo de la intervención y el estado del tren."),
    "ATP_DISCREPANCY": ("inferido", "El tren supera la velocidad supervisada y el ATP no interviene.",
                        "Si el ATP estuviera sano, frenaría; que no lo haga sugiere un ATP degradado o un dato erróneo.",
                        "Contactar con el maquinista y tratar el ATP como degradado hasta confirmar lo contrario."),
    "FLEET_DEVIATION": ("inferido", "Este tren va más rápido que los anteriores en este tramo.",
                        "Los trenes previos pasaron a menor velocidad: puede haber una limitación temporal no publicada.",
                        "Consultar con Adif si existe una limitación temporal de velocidad en el tramo."),
    "FLEET_OVER_REF": ("inferido", "La flota circula habitualmente por encima del límite de referencia en este punto.",
                       "Patrón repetido por varios trenes: el límite de referencia puede estar desactualizado.",
                       "Revisar el límite de referencia del tramo; sin riesgo inmediato por sí solo."),
    "DEGRADED": ("directo", "El supervisor está en modo degradado.",
                 "Con menos información fiable se aplica una restricción preventiva.",
                 "Recuperar la fuente de datos y mantener la precaución mientras tanto."),
}

LABELS = {"age_s": ("Edad del dato", "s"), "km": ("Distancia del salto", "km"), "kmh": ("Velocidad medida", "km/h"),
          "limit": ("Límite aplicado", "km/h"), "gap_km": ("Distancia actual", "km"), "need_km": ("Distancia necesaria", "km"),
          "ttc_s": ("Tiempo hasta alcance", "s"), "median": ("Velocidad habitual de la flota", "km/h"), "ref": ("Límite de referencia", "km/h"),
          "n": ("Trenes de referencia", ""), "eta_a": ("Llegada del primero en", "s"), "eta_b": ("Llegada del segundo en", "s")}


def build(h):
    """h: engine.Hazard (o dict con code, data, msg). Devuelve {kind, detects, rule, data:[[etiqueta, valor]], recommend}."""
    code = getattr(h, "code", None) or h.get("code")
    data = getattr(h, "data", None) if not isinstance(h, dict) else h.get("data")
    entry = CATALOG.get(code)
    if not entry:
        return {"kind": "directo", "detects": "Condición detectada por una barrera de seguridad.", "rule": "Ver el mensaje de la alerta.",
                "data": [], "recommend": "Consultar con el CTC."}
    kind, detects, rule, rec = entry
    rows = []
    for k, v in (data or {}).items():
        if k in LABELS:
            lab, unit = LABELS[k]
            rows.append([lab, f"{v} {unit}".strip()])
        elif k in ("front", "system"):
            rows.append(["Tren delantero" if k == "front" else "Sistema ATP", str(v)])
    return {"kind": kind, "detects": detects, "rule": rule, "data": rows, "recommend": rec}
