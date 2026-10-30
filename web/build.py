#!/usr/bin/env python3
"""Construye web/site/: la web estática de demostración (se puede alojar en cualquier hosting estático).
Reutiliza dashboard/index.html y dashboard/tablet.html con retoques mínimos y comprobados (cada reemplazo debe existir una vez)."""
import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W, D, OUT = os.path.join(ROOT, "web"), os.path.join(ROOT, "dashboard"), os.path.join(ROOT, "web", "site")


def patch(src, reps):
    for a, b in reps:
        assert src.count(a) == 1, f"patrón no único/inexistente: {a[:70]!r}"
        src = src.replace(a, b)
    return src


def main():
    if not os.path.isdir(os.path.join(W, "rec")):
        raise SystemExit("falta web/rec: ejecute python3 web/record.py")
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT)
    shutil.copytree(os.path.join(W, "rec"), os.path.join(OUT, "rec"))
    shutil.copy(os.path.join(W, "shim.js"), OUT)
    for _f in ("icon.svg", "logo.png", "og-image.png", "favicon.png", "basemap.json"):
        shutil.copy(os.path.join(D, _f), OUT)

    idx = open(os.path.join(D, "index.html"), encoding="utf-8").read()
    idx = patch(idx, [
        ('href="/logo.png"', 'href="logo.png"'), ('href="/favicon.png"', 'href="favicon.png"'),
        ("fetch('/basemap.json')", "fetch('basemap.json')"), ('src="/logo.png"', 'src="logo.png"'), ('<a href="/" class="brand"', '<a href="./" class="brand"'),
        ("<title>RailGuard</title>", "<title>RailGuard Demo</title>\n<script src=\"shim.js\"></script>\n"
         "<style>#adm,#pmrow,#issue{display:none!important}#dv{background:#0a1017;color:var(--tx);border:1px solid var(--line);border-radius:6px;padding:3px 6px;font:inherit}"
         "#dtab{color:var(--acc);border-color:var(--acc);cursor:pointer}</style>"),
        ("let who='operador';try{who=localStorage.getItem('rg_who')||prompt('Nombre del operador')||'operador';localStorage.setItem('rg_who',who)}catch(e){}",
         "let who='Demo';"),
        ("const CENTRE=location.pathname.startsWith('/centro');", "const CENTRE=!!RG_DEMO.centre;"),
        ("if(CENTRE&&!tok()&&!askedTok){", "if(false){"),
        ("$('simctl').style.display=S.mode==='sim'&&!CENTRE?'block':'none';", "$('simctl').style.display='block';"),
        ("$('mode').textContent=S.mode==='sim'?'SIMULACIÓN sobre captura real':'EN VIVO';",
         "$('mode').textContent='DEMO · ejecución real grabada';$('mode').title='Reproducción de una ejecución real del motor sobre una captura de trenes reales (30-oct-2026). No son datos en vivo.';"),
        ('<span id="clock" class="pill">—</span>',
         '<span id="clock" class="pill">—</span><select id="dv" title="Vista"><option value="nacional">Centro Nacional</option>'
         '<option value="madrid">Madrid · Atocha</option><option value="barcelona">Barcelona · Sants</option><option value="sevilla">Sevilla · Santa Justa</option></select>'
         '<a id="dtab" class="pill" href="tablet.html" style="text-decoration:none">📱 App de cabina</a>'
         '<span id="dprog" class="pill"></span><button id="drs" title="Reiniciar la reproducción">↻</button>'),
    ])
    open(os.path.join(OUT, "index.html"), "w", encoding="utf-8").write(idx)

    tab = open(os.path.join(D, "tablet.html"), encoding="utf-8").read()
    tab = patch(tab, [
        ('<link rel="manifest" href="/manifest.webmanifest">\n<link rel="icon" href="/icon.svg">',
         '<link rel="icon" href="icon.svg">\n<script src="shim.js"></script>'),
        ("if('serviceWorker' in navigator)navigator.serviceWorker.register('/sw.js').catch(()=>{});", ""),
        ('<div class="wrap" id="login">\n  <h1>RailGuard · Cabina</h1>',
         '<div class="wrap" id="login">\n  <div class="card" style="border-color:#7a5710"><b style="color:#ffb020">DEMO grabada</b> · reproducción de una ejecución real del motor.<br>'
         '<span class="mut">Escenario</span> <select id="dsc"><option value="convoy_3km">Dos trenes a 2,5 km</option><option value="seguimiento">Alcance en misma vía</option>'
         '<option value="via_unica">Vía única, sentidos opuestos</option><option value="base">Red en calma</option></select> '
         '<span class="mut">Tren</span> <select id="dtr"></select> · <a id="dback" href="index.html" style="color:#6ea8ff">Panel de control</a><br>'
         '<span class="mut">Pulse «INICIAR SERVICIO» (activa el sonido). «Enterado» silencia la sirena roja; la crítica no se silencia.</span></div>\n  <h1>RailGuard · Cabina</h1>'),
    ])
    open(os.path.join(OUT, "tablet.html"), "w", encoding="utf-8").write(tab)
    size = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(OUT) for f in fs)
    print(f"web/site listo: {size/1024/1024:.1f} MB")


if __name__ == "__main__":
    main()
