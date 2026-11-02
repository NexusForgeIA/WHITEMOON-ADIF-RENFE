# API REData (Red Eléctrica) — referencia usada por RailGuard

Fuente: https://www.ree.es/es/datos/apidatos · gratuita, sin clave, solo GET · `https://apidatos.ree.es/{lang}/datos/{categoría}/{widget}`

Parámetros: `start_date`, `end_date` (`YYYY-MM-DDTHH:MM`), `time_trunc` (hour|day|month|year). Para una región: `geo_trunc=electric_system`
+ `geo_limit` (peninsular|canarias|baleares|ceuta|melilla|ccaa) + `geo_ids` (peninsular 8741, canarias 8742, baleares 8743, ceuta 8744, melilla 8745;
ccaa 1–… según comunidad). Sin parámetros geo: nacional o peninsular según el widget.

Categorías y widgets: ver `redata.CATALOG` (balance, demanda, generacion, intercambios, transporte, mercados).

## Verificado el 2 nov 2026
- `demanda/evolucion` con `geo_limit=canarias&geo_ids=8742`: 200 con `time_trunc=day` (dato con retraso: última actualización 30 oct); 502 con `hour`.
- `demanda/demanda-tiempo-real` con `canarias`: 400. La demanda en tiempo real solo existe para la península.
- No hay desglose por isla (La Palma, La Gomera…): un apagón insular no se ve en REData a tiempo. Se cubre con titulares de medios (`energia.py`).

## Uso en RailGuard
`redata.RedData` consulta cada 30 min la demanda diaria de los 5 sistemas, la muestra en «Vigilancia contextual» y avisa si el último día cae ≥25 % frente a la media previa.
Endpoint propio: `/api/redata`. Atribución: Red Eléctrica de España (REData).
