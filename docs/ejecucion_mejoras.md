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

### Corrección propia previa a pieza 4

Revisión de `c38152b`: corregida la contaminación de memoria entre temas mediante `routing.py`.
Solo un seguimiento corto y sin entidad nueva recibe el último turno y las entidades; decisión registrada
en bitácora y observación visible únicamente al continuar. La precarga conserva el primer partido del equipo;
el seguimiento real usa `analyze_match(181043)`. Recuperación por intención original con una herramienta.
Evaluación real en orden: herramienta esperada 5/10 → 10/10, copias literales 2 → 0. Ver tabla y límites
semánticos detectados en `analisis/08_capa_agentica.md`. 392 pytest, cobertura 95,16 %, Ruff y ocho tests web verdes.
Se detiene tras el commit fix para revisión de Gustavo; no se inicia la pieza 4.

### Corrección de interpretación previa a pieza 4

`c8fceab` aprobado en vivo por Gustavo. Se añadieron textos canónicos a forma, límites y rendimiento,
y `check_claims` para topes cruzados, conteos de últimos partidos y polaridad de CLV. Se integra en la
reparación existente, sin ampliar eventos SSE ni tocar el motor. 420 pytest, cobertura 95,36 %, Ruff y
ocho pruebas web correctos. Batería real: 9/10 herramientas, sin copias; las tres confusiones corregidas.
La revisión manual en `analisis/08_capa_agentica.md` registra también un bloqueo, la pérdida de contexto
subsiguiente y límites pendientes de tiempo/cobertura y omisiones. No se declara corrección semántica general.
Se detiene tras este commit fix para revisión; pieza 4 pendiente.

### Respaldo determinista previo a pieza 4

`cb82190` aprobado. Se añade `fallback.py`: compone y verifica textos canónicos si la reparación falla,
con advertencias y calendario local disponible; sin datos útiles mantiene SAFE_TEXT. Guarda entidades
también tras error, sin recordar respuestas fallidas. Horas America/Santiago calculadas en tres tools.
Qwen real: dos secuencias de turnos 1/2/5, seis herramientas correctas, seis respuestas no vacías y dos
respaldos efectivos; seguimiento directo a analyze_match(181043). Permanece documentado un comentario
no sustentado sobre valor en un calendario. Evidencia en `analisis/08_capa_agentica.md`.
431 pytest, cobertura agéntica 95,64 %, Ruff y ocho pruebas web correctos. Motor y SSE intactos.
Se detiene tras este commit fix para revisión. Pieza 4 todavía sin iniciar.

## Pieza 4: acciones, vigía y actividad del asistente

`d2f6576` aprobado. Implementados objetivos create/list/cancel y favoritos tipados, en tablas agent_*
y preferencias propias. Identificación obligatoria, escrituras solo por intención solicitada, usuario
fijado por el request y confirmaciones con ids reales; objetivos activos iguales se reutilizan.
Vigía sin Ollama: snapshot, comparación, seis condiciones, reglas globales, prioridad, descartes con
motivo, alertas verificadas y deduplicadas, fulfilled y bitácora transaccional. Integrado al final de
daily/prekickoff con contención de fallos; salida vacía de prekickoff sigue sin dependencias pesadas.
Endpoints de alertas/lectura, vigilancias y bitácora con esquemas estrictos. UI mínima con badge, alertas
y registros del chat/vigía, usable a 390/1440 px y ambos temas; controles nuevos de 44 px y foco conservado.

Datos reales: 40 partidos, 2 con Pinnacle, 0 con valor elegible. Pinnacle validado con alertas reales;
value_appears permanece pendiente en producción, con su caso positivo probado en datos controlados.
Vigía real: 1 alerta y después 0; ciclos de 1,41–1,47 s, sin iniciar LLM. Caso del panel pasó por
analyze_match(181043) y dos create_watch; preparación final deja ids 1 y 7 activos, sin duplicar el 1.
Colombia aún está fuera de 24 h y sin Pinnacle: no se inventó una alerta. La alerta visible id 1 es de
Qatar U23–Singapore U23 y queda sin leer para revisión.

Batería Ollama final: 12/13 herramientas/turnos, acciones 3/3, cero copias; fallo de seguimiento del
turno 2 y límites de redacción registrados sin ocultarlos en `analisis/08_capa_agentica.md`.
478 pytest, cobertura agéntica 95,97 %, Ruff y ocho pruebas web correctos. Capturas en docs/img/agente.
CLAUDE.md §3 actualizado solo localmente. Motor y SSE intactos, sin dependencias nuevas.
Se detiene tras el único commit feat(agents) de esta pieza para revisión. Pieza 5 pendiente.

## Pieza 5: evaluación, demo y cierre

`6cb18aa` aprobado en vivo. Sin cambios en src/footy_agents, motor ni interfaz. Se añadieron el reset
de seis tablas con simulación y --yes, y pruebas de preservación/rollback; preferencias intactas.
Evaluador en modo cierre: diez preguntas, crear/listar/cancelar y dos seguimientos, con métricas de
herramienta, camino, argumentos, respaldo, reparaciones, recuperaciones y percentiles. Evidencia
versionada y revisión manual en docs/analisis/evaluacion_agente_final.json y 08_capa_agentica.md.

Qwen real: 14/15 herramientas/caminos y turnos completados, acciones 3/3, un respaldo, tres reparaciones,
tres recuperaciones, p50 10,897 s / p95 18,784 s. Revisión manual: 11 correctas, 3 parciales y 1 sin
respuesta; cero copias literales. Una consulta de UI se intercaló fuera del set y quedó documentada,
sin mezclar su registro ni afirmar exclusividad de carga. No se corrigieron los límites ya conocidos.

Guion de seis minutos, checklist, selección de partido real dentro de 24 h y plan B en docs/demo_agente.md;
diagramas Mermaid en docs/arquitectura_agente.md. Mapa CLAUDE.md §3 comprobado y actualizado sin versionarlo.
Flujo real capturado: Qatar U23–Singapore U23, vigilancia 3 de inicio cercano, alerta 1, una acción y
después cero. 14 capturas finales de chat/alerta/bitácora a 390/1440, ambos temas, sin fallos de contraste,
desbordamientos ni errores JS. Evidencia local en reports/pieza5/flujo.json.

488 pytest, cobertura agéntica 95,97 %, Ruff y ocho pruebas web verdes. Se detiene tras un único
test(agents) para revisión. No se integra a main ni se inicia trabajo adicional.
