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
