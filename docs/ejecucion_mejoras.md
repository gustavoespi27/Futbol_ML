# Orden de ejecución aprobado tras el paso 7

Solicitud de Gustavo recibida como texto adjunto. Un commit y push por tarea, sin dependencias nuevas. El paso 7 está aprobado; la cobertura única y la altura móvil de Actualizar (44 px) fueron verificadas en la app.

1. **Paso 8 del frontend**: vistas completas; fecha única en escritorio; probabilidades Local/Empate/Visita en las tarjetas de Hoy; subsecciones bajo el grupo lateral activo (Explorar: Simulador/Combinadas; Más: Fiabilidad/Cómo funciona).
2. **A. Pulido del chat**: procedencia explícita Pinnacle y `value_status`; salida final bufferizada y verificada antes del SSE; constantes de riesgo y cifras del usuario admitidas; `get_stake_limits`; alias de ligas y `min_edge` ajustado; precarga determinista por equipo/liga; detección de pseudollamadas con un reintento; sin apuestas seguras; evaluación de las siete preguntas de la revisión y pruebas FakeLLM. Evidencia en `08_capa_agentica.md`.
3. **B1. Ollama bajo demanda**: inicio perezoso configurable, proceso sin ventana y de prioridad baja, keep-alive 5 min, un modelo y una petición paralela. Health solo sondea; estado de reposo; parar solo el proceso propio; una redacción de resumen por usuario/día. Medir RAM/VRAM en `09_consumo.md`.
4. **B2. Automatización ligera**: tareas de prioridad 7; guardia pura de CPU/pantalla completa y reintentos; ingesta condicional y trabajo incremental por revisión; salida rápida de prekickoff sin partidos; pausa con expiración, estado y lock; registro idempotente y pruebas. Avisar antes de modificar `footy/ingest` si la descarga condicional lo requiere. Medir daily con y sin cambios.
5. **C. A3 selecciones**: excepción de solo lectura **aprobada expresamente por Gustavo**, sin `tracking.py` ni paper bets. Ingesta cacheada `martj42/international_results`, alias exhaustivos para selecciones absolutas, Elo por torneo/localía/neutralidad y Poisson; walk-forward 2000–2021 / 2022–2026 y referencia Pinnacle. Excluir juveniles, sub-23 y femenino. Integrar fuente «modelo selecciones» en contexto, herramienta y UI. Pruebas, cobertura ≥90 %, `11_selecciones.md`, decisión A3 y mapa de CLAUDE.md §3.
6. **Pasos 9–11**: asistente y arquitectura; rendimiento medido; documentación y capturas finales con internacionales cubiertos. Tabla profesional del README: espacios uniformes antes de %, 77 % de prueba en negrita y banca sin `,0`.

Las aprobaciones A1/A2 siguen vigentes. No se aprueban F3c, modificaciones de `tracking.py`, el atenuador de lesiones, eventos SSE nuevos ni nuevas dependencias. La fuente de valor sigue siendo Pinnacle sin margen; cuarto de Kelly, topes 2 %/10 %. Las cifras las calcula el código.

## Estado

- Paso 8: implementado y validado; evidencia en `validacion_frontend_paso8.md`.
- A: implementado y validado; comparación real antes/después y límites pendientes en `analisis/08_capa_agentica.md`.
- B1: implementado y medido; descarga natural tras cinco minutos en `analisis/09_consumo.md`.
- B2: implementado, medido y registrado en Windows; evidencia en `analisis/09_consumo.md`.
- C (A3 selecciones): implementado y validado; métricas, limitaciones y n=0 frente a Pinnacle en `analisis/11_selecciones.md`.
- Pasos 9–11: detenidos por instrucción de Gustavo; prioridad al agente para el 12 de noviembre.

## Agente: pieza 3 (2026-11-09)

Alcance vigente: construir sobre `9e14a7e`, sin reescribir observaciones, reparación, memoria ni bitácora.
Se revirtió exclusivamente el cambio pendiente de `docs/analisis/11_selecciones.md` antes de comenzar.
Descripciones breves con uso, exclusión y ejemplo; tabla de ruteo; columna `entities` migrada con ALTER
idempotente en `agent_chat_memory`. Se guardan identificadores, nombres y liga, sin cuotas ni probabilidades.
La memoria respeta usuario, ventana de 30 minutos y borrado; las cifras se consultan de nuevo.
Se mantiene el contrato SSE. Sin herramientas nuevas ni modificaciones al motor.

Pruebas: 366 pytest, cobertura agéntica 95,41 %, Ruff y ocho pruebas Node en verde; sintaxis de agent.js válida.
Sondeo reproducible: `scripts/eval_agent_routing.py --output reports/agente/pieza3-ruteo-final.json`.
El LLM es Qwen 2.5 de 7B real, las herramientas usan una ficha sintética estable: mide ruteo,
no calidad de pronósticos ni latencia sobre servicios reales. Evidencia y límites en `analisis/08_capa_agentica.md`.
Tras el commit de esta pieza se detiene la ejecución para revisión; piezas 4 y 5 pendientes.
