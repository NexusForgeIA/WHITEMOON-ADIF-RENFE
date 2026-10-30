"""Catálogo vivo de sistemas de seguridad: qué hace cada uno, cómo funciona, estado real y quién responde si falla.

Todo lo dinámico (estado, disparos, parámetros) sale del motor en ejecución; el texto descriptivo es fijo.
Los parámetros numéricos son los configurados en RailGuard, NO valores oficiales de Adif.
"""

# id -> definición estática
DEFS = [
    dict(id="B0", group="Tren", name="ATP de a bordo (LZB / ETCS / ASFA)", ext=True,
         does="Frena el tren automáticamente si supera la velocidad supervisada o no respeta una señal. Es la defensa propia del tren, independiente de tierra.",
         how=["RailGuard no sustituye al ATP: lo contrasta con la telemetría que reciba (sistema, modo, protegido, intervención, velocidad supervisada).",
              "Alerta si el ATP está aislado en una línea que lo exige, o si el tren supera su velocidad supervisada sin que el ATP intervenga.",
              "Sin telemetría no se asume que el tren esté protegido."],
         params=[], fail_text="Sin telemetría o con ATP aislado, B1–B4 vigilan desde tierra y B5 impone restricción de velocidad; se avisa a la cabina por GSM-R.",
         behind=["B2", "B3", "B4", "B5"]),
    dict(id="B1", group="Tierra", name="Integridad de datos",
         does="Comprueba que lo que ven las demás barreras es creíble antes de fiarse de ello.",
         how=["Posición caducada (sin actualizar), salto imposible entre dos lecturas, o dos trenes con la misma posición.",
              "Un dato dudoso se trata como peligro: el tren se restringe en lugar de suponer que está bien."],
         params=[("stale_s", "Caducidad de posición", "s"), ("jump_factor", "Factor de salto imposible", "×"), ("feed_dead_s", "Feed muerto tras", "s")],
         fail_text="Si B1 falla, el supervisor pasa a modo degradado: restricción preventiva (precaución) a todos los trenes y aviso crítico al operador.",
         behind=["SYS", "B5"]),
    dict(id="B2", group="Tierra", name="Velocidad y frenado",
         does="Evita excesos de velocidad respecto al máximo de la línea y al producto, y comprueba la curva de frenado hacia la siguiente parada.",
         how=["Envolvente de velocidad por producto y por línea (con limitaciones temporales si existen).",
              "Distancia de frenado con deceleración conservadora."],
         params=[("decel_service", "Deceleración de servicio", "m/s²"), ("unknown_product_max_speed", "Máx. producto sin clasificar", "km/h")],
         fail_text="Si B2 falla, B0 (ATP) sigue frenando a bordo, B3/B4 cubren la separación y el modo degradado restringe a toda la red.",
         behind=["B0", "B3", "B4", "SYS"]),
    dict(id="B3", group="Tierra", name="Separación de bloques",
         does="Evita alcances: mantiene entre trenes una distancia mayor que la de frenado más un margen, y vigila la vía única.",
         how=["Distancia de frenado del tren de atrás + margen frente a la distancia real al de delante, en el mismo tramo y sentido.",
              "En vía única, dos trenes en sentidos opuestos son siempre un peligro."],
         params=[("spacing_margin_km", "Margen de separación", "km"), ("decel_service", "Deceleración de servicio", "m/s²")],
         fail_text="Si B3 falla, B4 (predicción) y la regla de proximidad de 3 km siguen detectando el alcance; B5 restringe a todos por degradado.",
         behind=["B4", "PROX", "SYS", "B5"]),
    dict(id="B4", group="Tierra", name="Predicción de conflicto (TTC)",
         does="Se adelanta al alcance: calcula en cuántos segundos se tocarían dos trenes si nada cambia.",
         how=["Tiempo hasta alcance (TTC) con las velocidades y rumbos actuales.", "Detecta convergencia en una misma estación o tramo."],
         params=[("ttc_stop_s", "STOP si TTC <", "s"), ("ttc_restrict_s", "Restricción si TTC <", "s"), ("converge_eta_s", "Convergencia en", "s")],
         fail_text="Si B4 falla, B3 sigue garantizando la separación mínima y la regla de 3 km avisa a las cabinas.",
         behind=["B3", "PROX", "SYS"]),
    dict(id="PROX", group="Cabina", name="Alerta de 3 km a cabinas (canal privado)",
         does="Si dos trenes están a menos de 3 km en riesgo real de conflicto, las tablets de ambos maquinistas se ponen en rojo a pantalla completa con sirena.",
         how=["Usa el GPS de la tablet de cabina: es un canal independiente del feed de Renfe.",
              "Rojo solo si hay conflicto de vía (mismo tramo y sentido, vía única, convergencia); ámbar si no. Por debajo de 1,5 km la sirena no se puede silenciar.",
              "Histéresis para que no parpadee: entra a 3 km y sale a 3,3 km, con retención de unos segundos."],
         params=[("proximity_km", "Radio de aviso", "km"), ("proximity_hold_s", "Retención del rojo", "s"), ("tablet_fresh_s", "GPS tablet válido", "s")],
         fail_text="Si no hay tablets conectadas, la alerta de cabina no llega, pero B3/B4/B5 siguen actuando desde tierra y el operador lo ve como «sin cabinas».",
         behind=["B3", "B4", "B5"]),
    dict(id="B5", group="Ejecución", name="Enclavamiento",
         does="Ejecuta la orden restrictiva y la mantiene hasta que se demuestre que es seguro soltarla.",
         how=["Cualquiera de las barreras puede restringir (basta una); para soltar hacen falta todas (todas deben estar limpias).",
              "Una restricción solo se libera tras varios ciclos limpios consecutivos. Un STOP nunca se libera solo: exige a una persona, validada por B7.",
              "Un tren detenido enclava su bloque y restringe a los trenes cercanos."],
         params=[("rearm_clear_cycles", "Ciclos limpios para liberar", "")],
         fail_text="B5 es el último ejecutor automático: si falla, la orden de frenado ya enviada permanece y el operador recibe un aviso crítico.",
         behind=["B6"]),
    dict(id="SYS", group="Tierra", name="Vigilante del feed y modo degradado",
         does="Detecta que el supervisor se ha quedado ciego (feed caído o barrera averiada) y degrada hacia el lado seguro.",
         how=["Si no llegan posiciones nuevas o una barrera lanza un error, restringe a todos los trenes (precaución) en vez de asumir que todo va bien.",
              "Avisa al operador con un banner permanente."],
         params=[("feed_dead_s", "Feed muerto tras", "s")],
         fail_text="Si el propio supervisor cae, el ATP de a bordo (B0) y el enclavamiento del tren siguen protegiendo; los centros pierden visión y lo ven como «sin conexión».",
         behind=["B0", "B6"]),
    dict(id="B6", group="Personas", name="Centros de control (Madrid · Barcelona · Sevilla · Nacional)",
         does="Reconocen, deciden la recuperación y autorizan el rearme. Nunca son la última defensa: cuando actúan, las barreras automáticas ya han contenido la situación.",
         how=["Cada centro ve su zona; si un aviso crítico no se reconoce a tiempo, pasa a todos los centros.",
              "Si un centro cae, su zona se escala automáticamente."],
         params=[], fail_text="Si un centro no responde o se desconecta, la situación se escala al resto de centros y al nacional; las barreras automáticas siguen restringiendo.",
         behind=["B5"]),
    dict(id="B7", group="Personas", name="Guardia de órdenes humanas",
         does="Impide que un error o una mala intención de una persona provoque una catástrofe: ninguna orden humana puede dejar a un tren sin protección.",
         how=["Añadir restricciones siempre se permite, también sobre trenes de otra zona. Quitarlas nunca depende solo de una persona.",
              "Rearmar un STOP exige: prueba de vía libre de las barreras, supervisor sano, sin conflicto real de proximidad en curso y límite de rearmes por centro.",
              "Doble autorización: dos centros u operadores distintos; la primera caduca. Un mismo centro no puede aprobarse a sí mismo.",
              "No existe ninguna orden para desactivar barreras. Todas las órdenes, aceptadas o rechazadas, quedan en el registro de auditoría."],
         params=[("rearm_pending_s", "Caducidad de la 1ª autorización", "s"), ("rearm_max_5min", "Máx. rearmes por centro en 5 min", "")],
         fail_text="Si B7 se desactivara, el rearme seguiría exigiendo la prueba de vía libre de B5; por eso B7 solo añade cerrojos y nunca quita ninguno.",
         behind=["B5"]),
]


def build(engine, extra=None):
    """Devuelve la lista de sistemas con estado vivo + resumen. `extra`: tablets_online, centres_online/total, mode."""
    extra = extra or {}
    snap = {b["id"]: b for b in engine.snapshot()["barriers"]}
    g = engine.guard
    out = []
    for d in DEFS:
        sid = d["id"]
        st, detail, fired, active, last = "OK", None, None, None, None
        if sid in snap and sid != "B5":
            b = snap[sid]
            st, fired, active = b["status"], b["total"], b["active"]
            last = engine.last_fire.get(sid)
            if st == "FAULT":
                detail = engine.faults.get(sid, "")[:160]
            elif st == "NODATA":
                detail = "Sin telemetría ATP de ningún tren: no se asume protección."
        elif sid == "B5":
            st = "ALERT" if engine.state else "OK"
            active, fired = len(engine.state), len(engine.locked)
            detail = f"{len(engine.locked)} bloque(s) enclavado(s)" if engine.locked else None
        elif sid == "SYS":
            st = "ALERT" if (engine.degraded or engine.faults) else "OK"
            detail = engine.degraded or (("Barrera(s) en fallo: " + ", ".join(sorted(engine.faults)) +
                                          ": restricción preventiva a todos los trenes") if engine.faults else None)
        elif sid == "PROX":
            n = extra.get("tablets_online", 0)
            red = sum(1 for p in engine.prox if p.get("level") == "RED")
            st = "ALERT" if red else ("OK" if n else "NODATA")
            detail = f"{red} par(es) en rojo" if red else (f"{n} tablet(s) en línea" if n else "Ninguna tablet conectada")
            active = red
        elif sid == "B6":
            on, tot = extra.get("centres_online", 0), extra.get("centres_total", 0)
            st = "ALERT" if engine.operator_queue() else ("OK" if on else "NODATA")
            detail = f"{on}/{tot} centros en línea · {len(engine.operator_queue())} en cola"
            active = len(engine.operator_queue())
        elif sid == "B7":
            pend = len(engine.pending_rearm)
            st = "ALERT" if pend else "OK"
            detail = (f"{pend} rearme(s) esperando segunda autorización · " if pend else "") + \
                f"{g['completed']} aceptados · {g['refused']} rechazados · {g['dual_pending']} 1ª autorizaciones · {g['rate_blocked']} por límite"
            fired = g["refused"] + g["rate_blocked"]
            last = (g["last"] or {}).get("t")
        params = [{"label": lbl, "value": engine.cfg.get(k), "unit": u} for k, lbl, u in d["params"] if k in engine.cfg]
        out.append({"id": sid, "group": d["group"], "name": d["name"], "external": d.get("ext", False), "does": d["does"], "how": d["how"],
                    "params": params, "status": st, "detail": detail, "fired": fired, "active": active, "last_fire": last,
                    "on_failure": d["fail_text"], "behind": d["behind"]})
    by = {s["id"]: s for s in out}
    for s in out:   # quién responde ahora mismo si este sistema cayera: los de detrás que están sanos
        s["covering"] = [{"id": b, "name": by[b]["name"], "healthy": by[b]["status"] in ("OK", "ALERT")} for b in s["behind"] if b in by]
    healthy = sum(1 for s in out if s["status"] in ("OK", "ALERT"))
    return {"outages": outages(engine, extra, by), "systems": out, "healthy": healthy, "total": len(out),
            "guard": {k: v for k, v in g.items()}, "pending": [{"train": t, **(engine._pending_view(t) or {})} for t in engine.pending_rearm if engine._pending_view(t)],
            "mode": extra.get("mode")}


_ATP_TXT = {"ATP_ISOLATED": ("CRIT", "sin protección automática (aislado o en modo no protegido)"),
            "ATP_DISCREPANCY": ("CRIT", "no interviene aunque el tren supera su velocidad supervisada"),
            "ATP_STALE": ("WARN", "telemetría caducada: no se sabe si protege")}
_ORD = {"CRIT": 0, "WARN": 1, "INFO": 2}


def _cover(by, ids):
    return [{"id": b, "name": by[b]["name"], "healthy": by[b]["status"] in ("OK", "ALERT")} for b in ids if b in by]


def outages(engine, extra, by):
    """Lista SIEMPRE visible de sistemas caídos o degradados y de qué sistemas los están cubriendo ahora mismo.
    CRIT = el sistema no protege y otros han asumido su función · WARN = degradado · INFO = cobertura no disponible (no es una avería)."""
    extra = extra or {}
    out = []
    if engine.degraded:
        out.append({"id": "FEED", "sev": "CRIT", "system": "Feed de posiciones / supervisor", "title": "Supervisor ciego: sin datos fiables de posición",
                    "detail": engine.degraded, "trains": [],
                    "applying": "Modo degradado: restricción preventiva (precaución) a TODOS los trenes. Los trenes siguen protegidos por su ATP de a bordo.",
                    "covering": _cover(by, ["B0", "B6"])})
    for bid in sorted(engine.faults):
        d = next((x for x in DEFS if x["id"] == bid), None)
        out.append({"id": "FAULT-" + bid, "sev": "CRIT", "system": f"{bid} · {d['name'] if d else bid}", "title": f"Barrera {bid} en fallo",
                    "detail": (engine.faults.get(bid) or "")[:160], "trains": [],
                    "applying": "Modo degradado: restricción preventiva a todos los trenes. " + (d["fail_text"] if d else ""),
                    "covering": _cover(by, d["behind"] if d else [])})
    atp = {}   # (sistema, tipo) -> trenes
    for h in engine.hazards:
        if h.barrier == "B0" and h.code in _ATP_TXT:
            atp.setdefault(((h.data or {}).get("system") or "ATP", h.code), []).extend(h.trains)
    for (sysname, code), tr in sorted(atp.items()):
        sev, txt = _ATP_TXT[code]
        out.append({"id": f"ATP-{sysname}-{code}", "sev": sev, "system": f"{sysname} (ATP de a bordo)", "title": f"{sysname}: {txt}",
                    "detail": f"{len(tr)} tren(es) afectado(s)", "trains": sorted(set(tr)),
                    "applying": "Desde tierra: B2 velocidad, B3 separación y B4 predicción vigilan estos trenes; B5 impone restricción de velocidad; aviso a cabina por GSM-R.",
                    "covering": _cover(by, ["B2", "B3", "B4", "B5"])})
    if by.get("B0", {}).get("status") == "NODATA":
        out.append({"id": "ATP-NODATA", "sev": "INFO", "system": "ATP de a bordo (LZB / ETCS / ASFA)", "title": "Sin telemetría ATP: no se asume protección a bordo",
                    "detail": "Ningún tren envía su estado de ATP a RailGuard.", "trains": [],
                    "applying": "B1–B4 vigilan desde tierra todos los trenes; B5 ejecuta restricciones.", "covering": _cover(by, ["B2", "B3", "B4", "B5"])})
    if by.get("PROX", {}).get("status") == "NODATA":
        out.append({"id": "PROX-NODATA", "sev": "INFO", "system": "Alerta de 3 km a cabinas", "title": "Sin tablets de cabina conectadas",
                    "detail": "La alerta roja con sirena no puede llegar a ningún maquinista.", "trains": [],
                    "applying": "B3 y B4 detectan y B5 frena desde tierra; el operador lo ve como «sin cabinas».", "covering": _cover(by, ["B3", "B4", "B5"])})
    on, tot = extra.get("centres_online", 0), extra.get("centres_total", 0)
    if tot and on < tot:
        out.append({"id": "B6-CENTRES", "sev": "WARN" if on else "INFO", "system": "Centros de control",
                    "title": f"{tot - on} de {tot} centros sin conexión", "detail": "Las situaciones de un centro caído se escalan al resto y al nacional.",
                    "trains": [], "applying": "Escalado automático a los centros en línea; las barreras automáticas siguen restringiendo.",
                    "covering": _cover(by, ["B5"])})
    out.sort(key=lambda o: _ORD[o["sev"]])
    return out
