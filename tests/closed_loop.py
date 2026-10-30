"""Prueba de lazo cerrado: los trenes simulados obedecen a B5. Ejecutar: python3 tests/closed_loop.py"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server

def run(app, secs, step=2.0):
    for _ in range(int(secs / step)):
        app.last -= step            # avanza el reloj simulado 'step' s por ciclo
        app.tick()

def sev(app, n):
    return app.engine.snapshot()["trains"] and {t["n"]: t["cmd"] for t in app.engine.snapshot()["trains"]}.get(n)

for sc, who in [("seguimiento", "T-9004"), ("exceso_velocidad", "T-9002"), ("via_unica", "T-9005")]:
    app = server.App(); app.engine.log_path = None
    run(app, 10)
    base = {h.code for h in app.hazards} if hasattr(app, "hazards") else set()
    app.set_scenario(sc, True)
    run(app, 6)
    hz = sorted({(h.barrier, h.code) for h in app.engine.hazards})
    print(f"\n== {sc}: {who} -> {sev(app, who)}  detectado por {hz}")
    print("   operador:", [(i['level'], i['title'], i['barriers'], i['action']) for i in app.engine.operator_queue()][:2])
    run(app, 40)
    k = next(t["kmh"] for t in app.engine.snapshot()["trains"] if t["n"] == who)
    print(f"   tras 40 s: {who} a {k} km/h, cmd={sev(app, who)}; operador espera: {[i['action'] for i in app.engine.operator_queue()][:1]}")
    app.set_scenario(sc, False)
    run(app, 4)
    left = [(t, s['sev']) for t, s in app.engine.state.items()]
    print("   al retirar el fallo, restricciones residuales:", left)
    # rearme humano de un STOP real (si queda alguno)
    stops = [t for t, s in app.engine.state.items() if s["sev"] == 3]
    print("   STOP residuales:", stops)

# rearme tras resolver: seguimiento -> retirar solo el tren delantero y rearmar el trasero
app = server.App(); app.engine.log_path = None
run(app, 4); app.set_scenario("seguimiento", True); run(app, 6)
base_front = app.base.pop("T-9003"); app.sim.pop("T-9003"); app.engine.forget("T-9003")  # el delantero despeja la vía
print("\n== rearme: STOP T-9004 antes de prueba:", app.engine.rearm("T-9004", "op")[1])
run(app, 8)
print("   tras 8 s limpios:", app.engine.rearm("T-9004", "op"))
run(app, 40)
print("   T-9004 reanuda:", [t['kmh'] for t in app.engine.snapshot()['trains'] if t['n']=='T-9004'], "km/h")

# escenarios de datos
for sc in ("datos_congelados", "salto_gps", "fallo_barrera", "supervisor_ciego"):
    app = server.App(); app.engine.log_path = None
    run(app, 6); app.set_scenario(sc, True); run(app, 6)
    s = app.engine.snapshot()
    print(f"\n== {sc}: degradado={s['degraded']} faults={list(app.engine.faults)} hazards={sorted({(h.barrier,h.code) for h in app.engine.hazards})[:4]} kpi={s['kpi']}")
    print("   operador:", [(i['level'], i['title']) for i in s['operator']][:3])
