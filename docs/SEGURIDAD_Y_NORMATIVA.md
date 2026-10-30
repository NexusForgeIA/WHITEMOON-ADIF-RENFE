# RailGuard · Seguridad y marco normativo (resumen)

**Estado:** prototipo de supervisión. No evaluado, certificado ni autorizado. No cumple hoy ninguna norma de seguridad ferroviaria de la UE ni de España.

El análisis completo (norma por norma, matriz de brechas y ruta de cierre) está en el documento «RailGuard · Marco normativo y análisis de brechas». Resumen:

- **Marco leído en fuente oficial:** método común de seguridad (Reglamento 402/2013 modificado por 2015/1136), guía de la ERA sobre el SGS, ETI CCS (Reglamento 2023/1695) y Real Decreto 929/2020.
- **No leído (de pago):** EN 50126, 50128, 50129, 50159. Se citan como camino habitual de demostración, no como requisitos verificados.
- **Cambio significativo:** si RailGuard ordena restricciones o frenos (B5), sí. Exige gestión del riesgo, registro de peligros y evaluación independiente (art. 4 a 6 del método común). En modo asesor (sin órdenes) el esfuerzo baja mucho.
- **Brechas principales:** análisis de peligros y registro de peligros inexistentes; sin demostración de la tasa de peligro de 10⁻⁹/h; sin nivel de integridad asignado; sin evaluación independiente; B1–B4 comparten el mismo feed de posiciones (causa común); registros de eventos en disco efímero (RD 929/2020 art. 7 pide conservarlos 10 años); acceso al panel sin contraseña por defecto.
- **Ruta:** piloto en modo asesor → caracterización del sistema con Adif → taller de peligros → cerrar brechas técnicas → ciclo de vida CENELEC → evaluación independiente → pruebas en vía con AESF.

Los umbrales, la valoración de significancia y los estados de la matriz son de WhiteMoon y no los ha revisado Adif ni ningún experto externo.
