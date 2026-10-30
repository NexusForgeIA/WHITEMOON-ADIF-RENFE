# RailGuard · supervisión ferroviaria con defensa en profundidad

Capa de supervisión que **no depende de una persona para la seguridad final**: el tren lleva su propia barrera (ATP) y
cinco barreras automáticas independientes actúan antes de que llegue una persona. Incluye un panel de control, una
**app de cabina (PWA)** con alarma roja a pantalla completa y el aviso de proximidad de 3 km.

```
B0 ATP a bordo (LZB/ETCS/ASFA) ── lo ejecuta el TREN; aquí solo se contrasta su estado
datos → B1 Integridad → B2 Velocidad/frenado → B3 Separación de bloques → B4 Predicción (TTC)
      → B5 Enclavamiento (ejecuta, bloquea, exige prueba para liberar)
      → B6 Personas: a) maquinistas (tablet, proximidad < 3 km)   b) centros de control (Madrid-Atocha, Barcelona, Sevilla)
                     c) Centro Nacional (ve todo y recibe lo que ningún centro atiende)
```

## Principios de seguridad intrínseca
| Regla | Implementación |
|---|---|
| Restringir = basta **1** barrera (1ooN) | cualquier barrera puede ordenar CAUTION / RESTRICT / STOP |
| Liberar = **todas** limpias N ciclos (NooN) | `rearm_clear_cycles` (3 por defecto) |
| STOP enclavado (latch) | no se libera solo; exige prueba automática **y** autorización humana |
| Humano nunca anula una barrera activa | `rearm()` rechaza si no hay prueba de vía libre |
| Humano siempre puede restringir | `manual_restrict()` nunca se rechaza |
| Fallo de barrera / feed perdido → lado restrictivo | todos los trenes a CAUTION+, escalado a operador |
| La alarma de cabina no depende de que alguien la lea | se entrega, se registra y, si nadie confirma en 20 s, **escala** al operador |
| El enlace perdido se avisa | la tablet suena y muestra «ENLACE PERDIDO»; el operador ve «sin canal de cabina» |

## LZB → ETCS/ERTMS y frenado automático (B0)
RailGuard **no sustituye ni manda** al ATP: LZB, ETCS y ASFA frenan el tren con sus propias curvas, certificadas.
B0 recibe su telemetría (`engine.set_atp(tren, {system, mode, protected, intervention, supervised_kmh})`) y avisa de:
- **ATP aislado/degradado** (`ATP_ISOLATED`): el tren circula sin protección automática; si la línea exige ATP
  (`atp_required` en `data/infrastructure.json`) → RESTRICT y aviso crítico al operador.
- **Discrepancia** (`ATP_DISCREPANCY`): velocidad real muy por encima de la supervisada y el ATP no interviene.
- **Intervención** (`ATP_BRAKING`) y **telemetría caducada** (`ATP_STALE`).
- Sin telemetría, B0 muestra **«sin telemetría»** (no finge cobertura). Hoy no existe ningún feed público de ATP:
  hay que conectarlo a los datos de a bordo/CTC del operador. La migración LZB→ETCS se modela con el campo
  `signalling` por corredor; el catálogo de corredores es **ilustrativo** (todo `verified: false`).

## Aviso de proximidad < 3 km a las tablets de cabina
- **Canal privado**: cada maquinista tiene un token (se guarda solo su hash) ligado a su tren; la tablet envía su GPS
  cada segundo (`POST /api/tablet/pos`) y recibe en la misma respuesta sus alertas. La respuesta solo trae el *otro tren*
  (nº, operador, distancia, rumbo, velocidad), nunca la identidad del otro maquinista. Las posiciones de tablet viven
  en RAM, **no se persisten**. Tras 20 intentos fallidos por IP en un minuto se bloquea.
- **Posición**: se usa el GPS de la tablet si es reciente (<10 s) y preciso (<500 m); si no, el del feed. Si la tablet queda
  a >15 km del tren que dice conducir, se ignora y se registra.
- **Regla** (`proximity.py`): alarma ROJA solo si a <3 km hay **conflicto de vía** (mismo tramo y sentido, vía única,
  convergencia en estación, o misma alineación con topología desconocida → fail-safe). Los cruces en vía doble y las
  zonas de estación dan aviso ámbar sin sirena. Motivo: en red real hay centenares de pares a <3 km sin riesgo, y una
  alarma que suena sin motivo se ignora (fatiga de alarmas). El modo `strict` (cualquier par <3 km) está en el panel.
- **Histéresis**: se activa a <3 km, se libera a >3,3 km o 5 s después de dejar de cumplirse. A <1,5 km pasa a
  **CRITICAL** (sirena más rápida y no se puede silenciar).
- **La app** (`/tablet`): pantalla roja pulsante a todo tamaño, distancia gigante, radar con rumbo del otro tren,
  sirena WebAudio + vibración + pantalla siempre encendida, botón ENTERADO (silencia solo la sirena de una alerta ROJA;
  la pantalla sigue roja hasta que haya separación), botón de prueba de sonido, aviso propio si pierde el enlace.
- **Auditoría** (`data/events.jsonl`): alerta emitida, entregada, enterado y cerrada, con tiempos.

## Centros de control: Madrid-Atocha, Barcelona-Sants, Sevilla-Santa Justa + Centro Nacional
- **Un panel por centro** en `/centro` (con el token de su centro; en simulación: `ctc-madrid`, `ctc-barcelona`, `ctc-sevilla`,
  `ctc-nacional`). El Centro Nacional (`/`) ve toda la red. Cada centro ve **solo su zona**: trenes, estaciones, vías,
  peligros, cola, tablets y registro. Los trenes que se acercan a su frontera aparecen atenuados como «entrantes».
- **Zonas** (`data/centres.json`): cada tren pertenece al centro más cercano, con histéresis de 5 km para que no cambie de
  dueño en la frontera. **Son ilustrativas**, no las demarcaciones reales de los CTC de Adif: hay que sustituirlas.
- **Permisos**: cualquier centro puede **añadir restricciones** a cualquier tren (y se avisa al centro titular), pero
  **rearmar/liberar solo en su zona**. Ninguno puede anular una barrera activa (lo decide el motor, igual que en el panel nacional).
- **Traspasos**: al cruzar la frontera se registra `HANDOVER` y ambos centros reciben un mensaje automático.
- **Mensajería** entre centros y con el nacional (300 caracteres, auditada en `events.jsonl`).
- **Escalado, para que nada dependa de que alguien mire**: una situación CRÍTICA sin reconocer por su centro en 60 s sube a
  todos los centros; si un centro que estaba conectado deja de dar señales (30 s), se levanta una alerta crítica «sin
  conexión» y su zona entera se escala al resto. Las barreras B0–B5 siguen actuando solas en todo momento.
- **Tokens**: `POST /api/centre/issue` (requiere `RAILGUARD_TOKEN`); solo se guarda el hash y reemitir revoca el anterior.
- **Límite**: hoy los tres centros y el nacional hablan con **un único servidor**; si cae, todos pierden la vista (las
  barreras a bordo no). Para explotación: una instancia por centro + agregador nacional, o alta disponibilidad.

## Operadores de España
`data/operators.json` recoge **45 empresas** del listado oficial de la AESF
([seguridadferroviaria.es](https://www.seguridadferroviaria.es/agentes-sector-ferroviario/empresas-ferroviarias), la página
no indica fecha): Renfe Viajeros/Mercancías, Ouigo, Intermodalidad de Levante (ILSA, que opera **Iryo**), Alsa, Arriva,
Avanza Tren, Euskotren, FGC, Captrain, Medway, TRAMESA… más FGV, SFM y Adif (no figuran en ese listado: por confirmar).
- **Datos de posición**: solo **Renfe** tiene feed integrado (`--source renfe`). FGC publica actualizaciones de viaje
  GTFS-RT (adaptador pendiente). Para el resto **no hay feed público confirmado**: sus trenes entran al sistema **por la
  tablet del maquinista** (alta automática, también protegen y son protegidos).
- **Cobertura**: un tren sin feed y sin tablet encendida es **invisible** para la alarma de 3 km. El panel muestra por
  operador cuántos trenes se ven; la cobertura real es un indicador a vigilar.

## Uso
```bash
python3 server.py                 # http://127.0.0.1:8080 · simulación en lazo cerrado · cabina: /tablet
python3 server.py --source renfe --gtfs google_transit.zip   # FEED OFICIAL de Renfe
python3 renfe_adapter.py --gtfs google_transit.zip              # sonda: valida el feed en tu máquina
python3 -m pytest -q tests        # 57 tests
python3 tests/closed_loop.py      # verificación extremo a extremo de los escenarios
```
Demo de cabina: inyecta «Dos trenes a 2,5 km», abre `/tablet` con el token `demo-T-9009` y marca *modo demostración*.
Con `RAILGUARD_TOKEN` definido, los POST del panel exigen `X-Token` y se pueden emitir tokens reales
(`POST /api/driver/issue`, panel «Cabinas»). Sin él, emitir tokens está desactivado.

## App y despliegue
- **Tablets**: `/tablet` es una PWA instalable (manifest + service worker; la carcasa funciona sin red, las alertas nunca salen de caché).
- **Panel**: web, responsive. `deploy/` trae Dockerfile, compose y Caddy (HTTPS automático + usuario/clave para el panel;
  `/tablet` y `/api/tablet/*` quedan abiertos porque usan el token de maquinista). **Sin probar** (no había Docker aquí).
- **HTTPS es obligatorio** en tablets reales: sin él el navegador no da GPS ni permite el service worker.
- Por defecto escucha en `127.0.0.1` y `/api/snapshot` **no lleva autenticación**: no lo expongas sin el proxy.

## Archivos
`engine.py` barreras B0–B5 y cola B6 · `centres.py` zonas, tokens y mensajería de centros · `proximity.py` regla de 3 km · `drivers.py` tokens (hash) · `server.py` HTTP, canal de cabina,
simulador que **obedece** a B5 · `scenarios.py` fallos inyectables · `renfe_adapter.py` · `data/` (operadores, corredores, captura)
· `dashboard/` panel + app de cabina · `deploy/` · `tests/`

## Límites que hay que tener claros antes de usarlo en explotación
1. **No sustituye** al enclavamiento, ATP/ASFA/ETCS/LZB ni a los circuitos de vía. Las órdenes deben salir por un adaptador a
   sistemas certificados (EN 50126/50128/50129, SIL 4, evaluador independiente). La alerta de cabina es un **aviso
   complementario**: añade carga de atención al maquinista y exige análisis de riesgos (CSM-RA) y aceptación del operador y
   de la AESF antes de usarse en servicio.
2. **PWA en segundo plano**: con la tablet bloqueada o la app en segundo plano, el navegador puede cortar GPS y sonido
   (sobre todo iOS). Para explotación hace falta una app nativa (servicio en primer plano en Android) o modo kiosco.
   **El sonido y el GPS reales no se han podido probar** en este entorno (solo navegador sin audio ni sensores).
3. **B1–B4 comparten la misma fuente** (posición/velocidad): un fallo de causa común del feed los afecta a todos. La tablet
   aporta una segunda fuente de posición, pero también es la misma tecnología (GNSS). Independencia real: circuitos de
   vía/contadores de ejes, balizas, odometría, señalización.
4. **Latencia**: el feed oficial da lat/lon cada ~15 s y sin velocidad (se deriva, ±5 km/h). A 300 km/h son ~1,25 km por
   ciclo. La tablet (1 s) mejora la alerta de 3 km, pero el frenado de precisión es del ATP.
5. **Supuestos a calibrar con datos de Adif**: velocidad máxima por producto/línea, vía única, limitaciones temporales,
   deceleraciones, trazado real (hoy es una recta entre estaciones). Catálogos de corredores y vía única: ilustrativos.
6. Protección de datos: la posición de un maquinista es dato personal. Base legal, información al trabajador/representantes
   y minimización (aquí: seudónimo, sin persistir posiciones, hash de tokens) quedan en manos del operador.

## Conexión con los datos abiertos de Renfe (data.renfe.com · CC BY 4.0 · hay que citar la fuente)
| Dato | URL | Refresco |
|---|---|---|
| Posiciones AV/LD/MD | `https://gtfsrt.renfe.com/vehicle_positions_LD.json` | ~15 s |
| Retrasos (trip updates) | `https://gtfsrt.renfe.com/trip_updates_LD.json` | 20-30 s |
| GTFS estático (paradas, orden, tipo de servicio) | `https://ssl.renfe.com/gtransit/Fichero_AV_LD/google_transit.zip` | diario |
| Estaciones | `https://ssl.renfe.com/ftransit/Fichero_estaciones/estaciones.csv` | — |

El feed de posiciones **no incluye velocidad, rumbo ni hora por vehículo**; `renfe_adapter.py` los deriva de
posiciones sucesivas y marca como *congelado* un GPS que repite posición cuando iba a >60 km/h.
Sin `--gtfs` solo funcionan B1, B2 (envolvente) y B4 parcial: no hay geometría de tramos ni destino.
Estado de verificación: el adaptador está probado con entidades reales y GTFS sintético; **no se ha probado
contra el feed en vivo** (red del entorno de desarrollo bloqueada). Ejecuta la sonda primero.

## Web de demostración
Versión estática con grabaciones del motor real (no datos en vivo): ver [`web/README.md`](web/README.md).

Demo publicada con GitHub Pages: la raíz redirige a `web/site/` (grabación del motor real, no datos en vivo).
