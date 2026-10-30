# RailGuard · Seguridad y marco normativo (resumen)

**Estado:** prototipo de supervisión. No evaluado, certificado ni autorizado. No cumple hoy ninguna norma de seguridad ferroviaria de la UE ni de España.

El análisis completo (norma por norma, matriz de brechas y ruta de cierre) está en el documento «RailGuard · Marco normativo y análisis de brechas». Resumen:

- **Marco leído en fuente oficial:** método común de seguridad (Reglamento 402/2013 modificado por 2015/1136), guía de la ERA sobre el SGS, ETI CCS (Reglamento 2023/1695) y Real Decreto 929/2020.
- **No leído (de pago):** EN 50126, 50128, 50129, 50159. Se citan como camino habitual de demostración, no como requisitos verificados.
- **Cambio significativo:** si RailGuard ordena restricciones o frenos (B5), sí. Exige gestión del riesgo, registro de peligros y evaluación independiente (art. 4 a 6 del método común). En modo asesor (sin órdenes) el esfuerzo baja mucho.
- **Brechas principales:** análisis de peligros y registro de peligros inexistentes; sin demostración de la tasa de peligro de 10⁻⁹/h; sin nivel de integridad asignado; sin evaluación independiente; B1–B4 comparten el mismo feed de posiciones (causa común); registros de eventos en disco efímero (RD 929/2020 art. 7 pide conservarlos 10 años); acceso al panel sin contraseña por defecto.
- **Ruta:** piloto en modo asesor → caracterización del sistema con Adif → taller de peligros → cerrar brechas técnicas → ciclo de vida CENELEC → evaluación independiente → pruebas en vía con AESF.

Los umbrales, la valoración de significancia y los estados de la matriz son de WhiteMoon y no los ha revisado Adif ni ningún experto externo.

## ERTMS/ETCS: qué exige y cómo se relaciona con RailGuard

Fuentes leídas: página ERTMS de la Comisión Europea y SUBSET-091 v4.0.0 (requisitos de seguridad ETCS). Los niveles L1/L2/L3 se citan como conocimiento general, no leídos de fuente.

| ETCS (SUBSET-091 / CE) | RailGuard | Brecha |
|---|---|---|
| Peligro central: «superación de la velocidad o distancia seguras» | Capas B2/B3 (sobrevelocidad, frenada) | RailGuard usa posición GPS pública: sin autorización de movimiento (MA/EOA), sin curvas de frenado por tren, deceleración constante |
| THR 1,0·10⁻⁹/h a bordo y en vía (0,67·10⁻⁹/h por bloque) | No demostrable | Sin proceso SIL4 ni evaluación independiente → solo asesor (advisory) |
| Integridad de transmisión (corrupción ≤ 1,0·10⁻¹¹, EN 50159) | JSON público sin autenticar | No apto para actuar; solo observar |
| Supervisión: velocidad permitida → aviso → intervención → freno de emergencia | Escalones +3 % / +8 % / +15 % (CAUTION/RESTRICT/STOP) | Analogía de presentación; umbrales propios, no los de ETCS |
| Clase B nacional (ASFA / LZB) | No modelada | Datos de Adif pendientes |
| Órdenes vía GSM-R/FRMCS y CTC | RailGuard no emite órdenes | Cualquier actuación debe ir por los canales de Adif |
| Confianza/intervalo de posición | No expuesto | Pendiente |

Conclusión: RailGuard es una capa de supervisión independiente y asesora; no sustituye ni imita ETCS, y no puede reclamar nivel SIL.

### Borrador AESF ETC ERTMS/ETCS (FN), v1.0 junio 2019 (leídas pp. 1–12)

- ETCS convive en España con ASFA (clase B). La función nacional FN-27 regula las transiciones ETCS N1/N2 ↔ Nivel 0 con ASFA Digital, con señales CON/AKT y 500 ms de espera (2.1.1.7).
- En Nivel 0 + ASFA, la velocidad de supervisión es el mínimo entre el valor nacional de la línea (V_NVUNFIT / V_NVSHUNT) y la velocidad máxima del vehículo (2.1.1.2).
- Los valores nacionales los propone el administrador de infraestructuras, con consulta a empresas ferroviarias y gestión de riesgo según Reg. 402/2013 (cap. 3).
- Implicación: RailGuard no conoce el sistema activo por tramo, ni las transiciones, ni el valor nacional de cada línea. Sus umbrales no son oficiales y su función es solo asesora. Datos pendientes de Adif.
- Anexos C (escenarios transitorios) y D (valores nacionales) no leídos.

#### Lectura completa del borrador AESF ETC ERTMS/ETCS (FN) (pp. 1–42) y aplicación

Aplicado:
- Deceleración de RailGuard (0,6 m/s²) comparada con los valores nacionales ETCS (Anexo D, paquete 203): A_NVMAXREDADH1 = 1,0 y A_NVMAXREDADH2/3 = 0,7 m/s². RailGuard es más conservador. Queda fijado con un test (`tests/test_etcs_reference.py`).
- El ETCS usa además factores de corrección (Kr_int 0,9; Kv_int 0,7; Kt_int 1,1) y un nivel de confianza del freno de emergencia de 99,9999999 % (M_NVEBCL). RailGuard no los modela: su curva de frenado es determinista y asesora.

Referencia (valores por defecto / usados históricamente en España):
| Variable | Defecto | Uso previo en España |
|---|---|---|
| V_NVUNFIT (modo UN, sin ETCS en vía) | 100 km/h | AV 200 / CONV 140 km/h |
| V_NVSTFF (Staff Responsible) | 40 km/h | 100 km/h |
| V_NVONSIGHT / V_NVSHUNT | 30 km/h | = defecto |
| V_NVREL (liberación) | 40 km/h | 15 km/h |
| D_NVOVTRP / T_NVOVTRP (rebase EOA) | 200 m / 60 s | 80 m / 40 s |
| T_NVCONTACT (pérdida de contacto RBC) | ilimitado | 20 s |
| D_NVPOTRP (marcha atrás Post Trip) | 200 m | 50 m |

Hallazgos del Anexo C:
- Las funciones nacionales se están eliminando salvo FN-27; coexisten trenes con y sin ellas (inventario a 25/07/2018, por serie de tren). La compatibilidad tren/vía depende de la ingeniería de cada línea.
- Hay combinaciones con riesgo teórico señalado por la propia AESF (escenario E1, función solo a bordo: FN-20, FN-24, FN-77, FN-124), sobre todo por limitaciones temporales de velocidad (LTV) revocables en zonas N1+N2.
- Las líneas AV con ERTMS se inventarían por línea y función; la mayoría no implementa funciones nacionales en vía.

Implicaciones para RailGuard (límites honestos):
- No sabemos qué modo ETCS (FS/OS/SR/UN/SH/TR/PT) ni qué nivel lleva cada tren, ni sus valores nacionales; por tanto no podemos reproducir la supervisión real.
- Las LTV (limitaciones temporales de velocidad) no están en nuestros datos: un tren legítimamente lento o rápido por una LTV puede parecer anómalo o pasar desapercibido.
- Un rebase de la autorización (modo TR, freno de emergencia) no es observable desde GPS público.
- Nuestros umbrales siguen siendo propios, no oficiales; los valores de la tabla son solo contexto.

### Capa BP: perfil de velocidad aprendido de la flota (asesora)
- `fleet_profile.py` + barrera `BP`: agrupa velocidades por tramo, punto kilométrico (≈1 km) y clase de tren, con los trenes de las últimas 6 h (mínimo 4 trenes distintos).
- Avisa (solo CAUTION) si un tren supera >125 % la mediana del grupo (y +20 km/h), y si el patrón de la flota supera el límite de referencia (para no normalizar un exceso sistemático).
- Publica «limitaciones probables» (mediana < 70 % del límite de referencia) con el nº de trenes que las sostienen. No son datos oficiales.
- Nunca restringe por sí sola ni relaja B2/B3/B4. Una limitación nueva tarda en aprenderse. Balizas y señales laterales no están en ningún feed público.
- No asume modo SR al pasar de alta velocidad a convencional: según la FN-27 la transición es a Nivel 0 + ASFA, y el modo real de cada tren es desconocido.

### Notificaciones
- Botón «🔔 Avisos» (cabecera): toast en pantalla, sonido y notificación del navegador ante peligros nuevos (STOP/RESTRICT con sonido; CAUTION solo toast), degradado del supervisor y fallo de barrera. El título de la pestaña muestra el nº de peligros graves.
- Son locales al navegador. No se envían correos ni mensajes a nadie; un canal externo (correo, Slack, SMS) requiere decidir destinatarios y autorización.

### Instalaciones de seguridad por línea (Anejo 10, Estudio Informativo Almodóvar del Río)
Datos en `data/safety_systems.json` y botón «📋 Líneas» del panel. Es un estudio informativo, no un inventario vigente: confirmar con Adif.
- LAV Madrid–Sevilla: LZB L72 principal, ASFA 200 de respaldo, **sin ETCS** (corrige la hipótesis anterior «LZB → ETCS»). 300 km/h, 220–250 en el entorno de Almodóvar. Detectores DCO y DCC. CTC en el CRC de Madrid-Puerta de Atocha.
- LAV Córdoba–Málaga: ETCS N1 y N2 instalados (el material circula en N1), LZB L72E y ASFA de respaldo; detectores DCO, DCC, DVL, DOA, DCDP; LTV gestionadas por eurobalizas. Transición LZB→ASFA: reconocimiento del maquinista en ~8 s o freno de emergencia.
- Línea 400 (convencional): ASFA; CTC Alcatel en Córdoba.
- Datos que Adif tiene y RailGuard no recibe: alarmas de detectores, estado de enclavamientos y circuitos de vía, LTV activas, datos LZB por tren, SAM.

### Datos de línea de FCMAF (Castilla-La Mancha, fuente divulgativa)
Fuente: fcmaf.es (Federación Castellano Manchega de Amigos del Ferrocarril), consultada el 30/10/2026. **No es fuente oficial de Adif**; cotejar con la Declaración sobre la Red antes de usarla como límite. Datos en `data/fcmaf_lineas.json`.
- Línea 010 (Madrid–Sevilla, tramo CLM de 228,351 km): bloqueo BCA-LZB, mando en CRC Madrid-Atocha, GSM-R, doble vía 25 kV, rampa máx. 12,5 ‰. Vmax por PK: 270 km/h en general, 290–300 entre PK 99,3 y 115,1 (pico 300), 190 en Ciudad Real, 240 PK 173–178, 200 PK 207–209, 70–200 en Puertollano, 250 hasta Córdoba.
- 5 PAET (La Sagra, Mora, Urda, Calatrava, Venta de la Inés) y 8 PIB (Yeles, Ablates, Los Yébenes, El Emperador, Malagón, Brazatortas...) con su PK; 6 subestaciones telemandadas desde Atocha; bases de mantenimiento en Mora y Calatrava.
- Línea 020 (La Sagra–Toledo, 20,995 km): bloqueo BCA, GSM-R; 220 km/h hasta PK 15,3, luego 165, 140 y 80 en Toledo.
- No consta ASFA, ETCS ni distancias de frenado. No se pudieron leer las líneas 040, 042, 050 ni 400 (acceso de la herramienta limitado).
- Uso posible: un perfil de velocidad máxima por PK para B2 en Madrid–Sevilla; requiere convertir PK a posición con las estaciones. Pendiente, no aplicado: B2 sigue usando sus límites actuales.

### B2 con perfil de velocidad por PK (Madrid–Sevilla, solo zonas lentas)
- `speed_profile.py`: convierte la posición del tren a PK interpolando entre estaciones ancla (Atocha 0, Ciudad Real 170,7, Puertollano 209,8, Córdoba 343, Sevilla 471,8) y aplica las zonas ≤ 200 km/h de FCMAF (PK 170,2–173,1 a 190; 206,8–208,8 a 200; Puertollano hasta 200).
- Salvaguardas: fuente no oficial; zonas estrechadas 1 km por extremo; tren a más de 3 km del eje se ignora; **B2 nunca pasa de CAUTION con este límite**; se desactiva con `speed_profile: false`.
- No se usan las zonas de 270–300 km/h: pueden estar desactualizadas y dar falsos avisos a trenes que circulan a 300.

### Texto sin fuente sobre PAET y transiciones LZB (aportado por el usuario) — NO incorporado como dato
- Coincide con FCMAF en la mayoría de PK (La Sagra, Mora, Los Yébenes, Urda, El Emperador, Malagón, Ciudad Real, Puertollano, Venta de la Inés), con diferencias en Yeles (34,3 vs 35,307), Calatrava (198,9 vs 196,481) y Brazatortas (224,9 vs 225,425).
- Contradice FCMAF y el Anejo 10: sitúa el desvío a Toledo en «Bifurcación Parla PK 13» (FCMAF: la línea 020 sale de La Sagra, PK 53,7); habla de transición a ERTMS N2 en Córdoba–Málaga (el Anejo 10 indica que el material circula en N1); atribuye a la C-5 de Cercanías «bucles LZB y cantones virtuales» en toda su longitud (sin respaldo en ningún documento de Adif que tengamos).
- Los PK que no aparecen en otra fuente (Conquista, Villanueva de Córdoba, Adamuz, Marachón, Guadajoz, Hornachuelos, Peñaflor, PK 343,9 y 470,2) quedan sin verificar. Solo se usan los PK de Córdoba (343) y Sevilla (471,8) como anclas del eje, con ese aviso.
- Acción pendiente: confirmar con Adif (Declaración sobre la Red / cuadro de velocidades máximas) antes de ampliar el perfil.

### Declaración sobre la Red 2026 de Adif (Network Statement 2026, ed. 13/06/2025) — fuente oficial
Datos en `data/safety_systems.json` (clave `declaracion_red_2026`). Libro de 464 páginas, en inglés.
- **Red y sistemas (a 1/1/2025):** 11.672,7 km propios; ASFA 10.594,2 km; bloqueos automáticos 9.536,7 km; CTC 9.055 km; ERTMS 384,9 km. ASFA está en todas las líneas principales; ASFA Digital con bajas de versiones antiguas en 2029 (RT 3/2024 de la AESF).
- **Bloqueos y detección:** BCA, BSL (señales laterales, propio de alta velocidad), BLA y BA; detección por circuitos de vía o contadores de ejes. Mando por CTC → PRO → PLO; DaVinci para alta velocidad; GSM-R en toda la alta velocidad.
- **Perturbaciones:** Plan de Contingencia con criterios de prioridad (no discriminación, jerarquía, publicidad, objetividad, regulación, proporcionalidad). Adif puede cancelar, desviar o cambiar surcos sin aviso en emergencia.
- **Lo que NO trae:** velocidades por línea ni por PK (la tabla oficial es otro documento; en el libro solo hay mapas resumen que están aparte en la web de Adif), ni distancias de frenado, ni LTV, ni datos de señales. Esa información está en la ICL (mensual y anual) y el Manual de Capacidad, que se distribuyen por RGD a empresas ferroviarias con licencia y certificado de seguridad.
- **Consecuencia:** el perfil de velocidad por PK de B2 sigue basado en FCMAF (no oficial) y limitado a zonas lentas. Para sustituirlo por datos oficiales hay que obtener la tabla de velocidades máximas o la ICL a través de Adif.


## LTV (limitaciones temporales de velocidad) de Adif
- Fuente: FeatureServer público del visor «Límites temporales de velocidad» de Adif (ArcGIS). Informativo; no es un feed de seguridad ni está certificado.
- `ltv.py` lo descarga cada 30 min, cachea en `data/ltv_cache.json` y lo sirve en `/api/ltv`. Si Adif/ArcGIS no responde se mantiene la última caché; sin caché la capa queda vacía (no se inventan datos).
- Mapa: capa «LTV» (punto naranja con km/h). En B2 genera un aviso **solo CAUTION** si un tren en marcha está a ≤1 km del punto de una LTV y supera su velocidad ×1,25 (el punto es aproximado, no un tramo exacto, y el tren puede estar frenando). Nunca restringe ni frena. La LTV trae los códigos de estación de Adif de su tramo (`CODPSINI`/`CODPSFIN`): si ambas están en RailGuard, el tren debe estar sobre ese tramo (≤1,5 km del eje entre ellas), lo que descarta líneas paralelas; si no, se usa solo el punto. Campos reales de la capa pública: `MOTIVO`, `TIPOTREN`, `FECHAFINPREV` y `FECHAVIGORLTV` existen pero vienen vacíos en las 1.024 LTV (30/10/2026); `OBSERVACIONES` solo en 229. Por eso no hay motivo, vigencia ni tipo de tren, y el aviso sigue en CAUTION.
- Instantánea del visor al 30/10/2026: 1024 restricciones activas (actualización del visor: 26/10/2026).

### Geometría oficial de la LTV (capa de tramos de Adif)
- Fuente: capa pública «Tramos en servicio Adif público» (misma organización ArcGIS; es la que usa el portal PISERVI): 1.174 tramos con geometría, `COD_LINEA`, `PKI`/`PKD`, tipo de red y electrificación. Sin velocidades (`V_DESDE`/`V_HASTA` no son velocidades).
- `ltv.py` interpola cada LTV (línea + PK inicial/final) sobre esa geometría por fracción de longitud entre PKI y PKD del tramo, y obtiene el trazado real afectado. Con él B2 exige que el tren esté sobre el tramo (≤0,7 km) y no usa el radio del punto. Sin geometría (línea/PK no encontrados) cae al método anterior.
- Aproximación: la interpolación asume PK lineal a lo largo de la polilínea simplificada; el error es de decenas de metros a pocos cientos. Sigue en CAUTION.
