# Web de demostración (estática)

Demo sin servidor: reproduce **ejecuciones grabadas del motor real** (mismas barreras B1–B6, mismos paneles y tablet).
**No son datos en vivo.** Los escenarios son sintéticos sobre una captura real del feed de Renfe.

```
python3 web/record.py     # graba web/rec/*.json ejecutando el motor (reloj simulado)
python3 web/build.py      # genera web/site/ (≈9 MB) a partir de dashboard/ + rec/
python3 -m http.server -d web/site 8000
```

`web/site/` se puede alojar en cualquier hosting estático (GitHub Pages, Netlify, Vercel, S3).
`shim.js` intercepta `/api/*` y responde desde la grabación; vistas: `?v=madrid|barcelona|sevilla`, `?s=<escenario>`.
Acciones que escriben en el sistema (restringir, rearmar) solo muestran un aviso en la demo.
