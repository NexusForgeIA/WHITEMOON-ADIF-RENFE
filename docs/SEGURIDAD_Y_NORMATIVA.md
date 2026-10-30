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
