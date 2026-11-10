# Evaluación reproducible de la capa agéntica

Ficha sintética fija; 15 preguntas por modelo; inferencia local real. Una ejecución por pregunta. La primera consulta incluye carga del modelo. Tokens/s = tokens de salida / latencia total (incluye prompt y herramientas); no es velocidad pura de generación. Memoria según /api/ps, no RAM total del sistema. La verificación numérica no valida la semántica ni la pertinencia.

## qwen2.5:7b

Memoria del modelo: 4535 MB; VRAM: 4535 MB.

| Pregunta | Esperada | Usadas | Argumentos válidos | Cifras verificadas | Segundos | Tokens/s |
|---|---|---|---|---|---:|---:|
| ¿Qué partidos hay en los próximos días? | get_upcoming_matches | get_upcoming_matches | True | True | 10.157 | 10.93 |
| ¿Cuándo juega Arsenal su próximo partido? | get_upcoming_matches | get_upcoming_matches | True | False | 7.038 | 17.19 |
| Dame los próximos 2 partidos de la liga E0. | get_upcoming_matches | get_upcoming_matches | True | True | 6.783 | 16.22 |
| ¿Qué apuestas con valor frente a Pinnacle hay? | get_value_bets | get_value_bets | False | True | 5.378 | 9.48 |
| Busca oportunidades con ventaja mínima de 8%. | get_value_bets | get_value_bets | True | True | 6.132 | 13.7 |
| ¿Hay alguna apuesta con ventaja superior a 10%? | get_value_bets | get_value_bets | True | False | 5.466 | 9.51 |
| Simula Arsenal contra Everton en E0. | simulate_match | simulate_match | True | True | 7.151 | 16.36 |
| ¿Cuántos goles esperados tiene Arsenal contra Everton en E0? | simulate_match | simulate_match | True | True | 5.922 | 12.49 |
| Simula Everton como local frente a Arsenal en la liga E0. | simulate_match | simulate_match | True | True | 6.623 | 16.16 |
| ¿Cómo va la tabla de la liga E0? | get_league_standings | get_league_standings | True | True | 5.875 | 11.92 |
| ¿Quién lidera la liga E0? | get_league_standings | get_league_standings | True | True | 5.239 | 8.21 |
| Muéstrame los puntos y la racha de Arsenal en la tabla E0. | get_league_standings | get_league_standings | False | True | 6.176 | 13.6 |
| ¿Cómo está rindiendo el sistema? | get_system_performance | get_system_performance | True | True | 6.497 | 14.78 |
| ¿Cuál es el CLV del sistema? | get_system_performance | get_system_performance | True | True | 5.001 | 7.2 |
| ¿Cuántos partidos evaluados y qué yield tiene el seguimiento? | get_system_performance | get_system_performance | True | True | 5.926 | 12.32 |
## qwen2.5:3b

Memoria del modelo: 2063 MB; VRAM: 2063 MB.

| Pregunta | Esperada | Usadas | Argumentos válidos | Cifras verificadas | Segundos | Tokens/s |
|---|---|---|---|---|---:|---:|
| ¿Qué partidos hay en los próximos días? | get_upcoming_matches | get_upcoming_matches | True | True | 8.356 | 17.71 |
| ¿Cuándo juega Arsenal su próximo partido? | get_upcoming_matches | get_upcoming_matches | True | True | 5.114 | 14.47 |
| Dame los próximos 2 partidos de la liga E0. | get_upcoming_matches | get_upcoming_matches | True | True | 5.248 | 14.29 |
| ¿Qué apuestas con valor frente a Pinnacle hay? | get_value_bets | get_value_bets | False | False | 5.296 | 14.35 |
| Busca oportunidades con ventaja mínima de 8%. | get_value_bets | get_value_bets | True | False | 5.059 | 12.85 |
| ¿Hay alguna apuesta con ventaja superior a 10%? | get_value_bets | get_value_bets | False | False | 4.796 | 8.97 |
| Simula Arsenal contra Everton en E0. | simulate_match | simulate_match | True | True | 5.545 | 19.66 |
| ¿Cuántos goles esperados tiene Arsenal contra Everton en E0? | simulate_match | simulate_match | True | True | 5.523 | 21.0 |
| Simula Everton como local frente a Arsenal en la liga E0. | simulate_match | simulate_match | True | False | 5.459 | 19.24 |
| ¿Cómo va la tabla de la liga E0? | get_league_standings | get_league_standings | True | True | 4.929 | 12.58 |
| ¿Quién lidera la liga E0? | get_league_standings | get_league_standings | True | True | 4.954 | 11.71 |
| Muéstrame los puntos y la racha de Arsenal en la tabla E0. | get_league_standings | get_league_standings | True | True | 4.98 | 12.05 |
| ¿Cómo está rindiendo el sistema? | get_system_performance | get_system_performance | True | True | 5.165 | 14.33 |
| ¿Cuál es el CLV del sistema? | get_system_performance | get_system_performance | True | True | 4.73 | 7.82 |
| ¿Cuántos partidos evaluados y qué yield tiene el seguimiento? | get_system_performance | get_system_performance | True | True | 4.8 | 9.37 |

## A — Pulido del chat (2026-11-09)

Comparación con `f8e7cb5`, paquete anterior aislado en `reports/agente/antes`; mismos servicios sintéticos y siete preguntas, Ollama real `qwen2.5:7b`, una ejecución por caso. No demuestra exactitud en producción ni equivalencia estadística. Se conservan arriba las mediciones previas.

Reproducción del estado actual: `.venv/Scripts/python scripts/eval_agent.py --models qwen2.5:7b --revision-only --output reports/agente/revision.md`.

| Criterio automático | Antes | Después |
|---|---:|---:|
| herramienta_correcta | 3/7 | 5/7 |
| sin_fugas | 3/7 | 7/7 |
| cifras_verificadas | 6/7 | 7/7 |
| sin_valor_sin_precio | 7/7 | 7/7 |
| explica_riesgo_combinada | 6/7 | 7/7 |
| success | 7/7 | 7/7 |

La pregunta sobre combinadas admite responder la política sin herramientas; cuenta como criterio aprobado, no como llamada. La verificación numérica del mensaje fijo de rechazo no demuestra que el modelo haya respondido la pregunta. `success` muestra el resultado real del SSE.

| Pregunta | Herramientas antes → después | Latencia antes → después |
|---|---|---:|
| ¿Qué partidos hay hoy y hay alguno con valor? | get_upcoming_matches → get_upcoming_matches, get_value_bets | 10.791 → 7.851 s |
| ¿Cómo va Colo-Colo en la tabla? | get_league_standings → get_upcoming_matches | 5.795 → 4.896 s |
| ¿Qué tan fiable es el sistema? | get_system_performance → get_system_performance | 6.569 → 9.122 s |
| ¿Cuánto debería apostar si tengo 100.000 pesos? | Ninguna → get_stake_limits | 3.4 → 6.792 s |
| ¿Quién gana el Real Madrid vs Barcelona? | Ninguna → get_upcoming_matches | 2.674 → 3.848 s |
| Dame una combinada segura para hoy | get_value_bets, get_value_bets → Ninguna | 10.441 → 2.84 s |
| ¿Qué probabilidad tiene Botosani de ganar? | Ninguna → get_upcoming_matches | 2.956 → 3.252 s |

Límites observados: la pregunta de tabla sigue usando solo la precarga de partidos; la pregunta Real Madrid–Barcelona usa probabilidades de próximos partidos en vez de simular. El grounding comprueba procedencia numérica, no pertinencia, definiciones ni causalidad. El detector de valor es conservador por oración; no sustituye una revisión semántica.

Cambios: texto final retenido y verificado antes del primer token; preámbulos de llamadas descartados; pseudollamadas con un reintento; cobertura Pinnacle explícita; límites y cifras del usuario admitidos; montos calculados en código y formateados en CLP; alias de catálogo y mínimo de ventaja ajustado.

Validación: 230 tests completos; 93 del agente; cobertura 96 % (693/722 sentencias); Ruff y `node --check agent.js` en verde. Contrato SSE sin cambios.
# Pieza 3: ruteo y entidades (2026-11-09)

Sondeo secuencial con `qwen2.5:7b` real y ficha sintética Chile–Colombia (20/30/50 %).
No mide pronósticos reales. Script: `scripts/eval_agent_routing.py --output reports/agente/ruteo.json`.
La precarga está deshabilitada en este sondeo para aislar la decisión del modelo.

| Consulta | Primer sondeo | Último sondeo | Latencia final |
|---|---|---|---|
| Analiza el partido de la roja | find_team → analyze_match | find_team → analyze_match | 13,118 s |
| ¿Y quién es favorito? | find_team → analyze_match (búsqueda repetida) | analyze_match (match_id=42) | 13,224 s |

Primer sondeo: 1/2 caminos esperados, latencias 28,992 y 22,555 s. Un intento intermedio con solo
la instrucción reforzada en el system prompt falló el seguimiento: no consultó herramientas y la
respuesta fue bloqueada. La versión final añade recuperación específica con el identificador reciente:
2/2 caminos, ambas respuestas verificadas, favorito Colombia. El seguimiento final necesitó una
recuperación y tres inferencias; el análisis inicial también tres. No se afirma que el modelo consulte
siempre correctamente al primer intento. Una muestra por consulta no permite inferir mejora de latencia
ni una tasa general de éxito; carga del modelo y caché influyen.

Evidencia local: `reports/agente/pieza3-ruteo.json`, `pieza3-ruteo-final.json` (intermedio) y
`pieza3-ruteo-recuperacion.json` (versión final). Los resultados incluyen eventos completos.
La memoria guarda identidad sin probabilidades ni cuotas; respeta usuario, 30 minutos y borrado.
La migración agrega `entities` mediante ALTER si falta, sin modificar tablas del motor.
Validación: 366 pytest; cobertura agéntica medida 95,41 %; Ruff, sintaxis JS y ocho pruebas web correctos.

## Corrección de contaminación entre temas (2026-11-09)

Comparación contra `c38152b`: Qwen 2.5 de 7B real, consultas en orden y herramientas reales de lectura.
La memoria se guarda en SQLite en memoria, aislada de la conversación del usuario. No se modifica el motor.
Comando: `.venv/Scripts/python scripts/eval_agent_routing.py --mode conversacion --output reports/agente/conversacion-despues.json`.
Para reproducir el antes se usa el mismo script con los módulos de `c38152b`.
Los datos reales pueden cambiar entre ejecuciones: esta prueba mide ruteo, no precisión predictiva.

| Pregunta | Antes: herramientas | Después: herramientas | Después (s) |
|---|---|---|---:|
| Analiza el partido de la roja | upcoming | upcoming → analyze_match(181043) | 14,712 |
| ¿Y quién es favorito? | find_team | analyze_match(181043) | 12,409 |
| ¿Cómo llega el Colo Colo? | get_team_form | get_team_form | 9,793 |
| Simula Colo Colo contra la U | simulate_match | simulate_match | 9,328 |
| que partidos vienen ahora? | upcoming (contaminado por filtro CHL) | upcoming (sin liga heredada) | 10,968 |
| ¿Qué apuestas con valor hay hoy? | get_value_bets | get_value_bets | 7,812 |
| ¿Por qué no hay apuestas recomendadas? | ninguna; copia anterior | get_coverage | 12,937 |
| ¿Qué tan fiable es el sistema? | ninguna; respuesta ajena al tema | get_system_performance | 13,961 |
| ¿Cuánto debería apostar si tengo 100.000 pesos? | ninguna; copia anterior | get_stake_limits(100000) | 9,399 |
| Dame una combinada segura para hoy | policy | policy | 0,001 |

`upcoming` abrevia `get_upcoming_matches`. Resultado: herramienta esperada **5/10 → 10/10**;
copias literales del turno anterior **2 → 0**. La última pregunta valida la política sin llamar al LLM.
No se encontraron respuestas heredadas de otro tema en la revisión manual del después. El script detecta
igualdad literal; esa métrica por sí sola no demuestra ausencia de paráfrasis ni corrección semántica.
Evidencia local con eventos, argumentos, texto y latencias: `reports/agente/conversacion-antes.json` y
`reports/agente/conversacion-despues.json`. Una ejecución por variante, sin inferencias concurrentes.

La continuidad es determinista: menos de 80 caracteres, referencia de seguimiento y ninguna entidad nueva
detectada por apodos, precarga o catálogo. Solo se envía el último par de mensajes. Un tema nuevo no recibe
historial ni entidades. La bitácora registra ambas decisiones; solo la continuidad emite la observación visible.
La precarga por equipo conserva la identidad del primer partido por kickoff, sin probabilidades ni precios.
La recuperación selecciona una herramienta por intención original y pasa los argumentos conocidos.

**Límites observados:** aunque el después cumple el criterio de herramientas, Qwen interpretó al revés el
CLV negativo y el mayor log loss, confundió el límite diario con el límite por apuesta y sugirió posible
desactualización sin consultarla en la respuesta sobre valor. `verify_numbers` comprueba presencia numérica,
no el significado ni la asociación cifra-concepto. Estos defectos no quedan resueltos ni se presentan como
aprobados por esta corrección de memoria. Se mantienen como pendientes para revisión antes de la demo.

Validación final: **392 pytest**, cobertura agéntica **95,16 %** (1425 sentencias, 69 sin cubrir), Ruff,
sintaxis de agent.js y ocho pruebas Node correctos. Pruebas FakeLLM cubren diez turnos, continuidad positiva
y negativa, precarga, argumentos de recuperación, aislamiento de tema nuevo y decisión en bitácora.

## Frases canónicas y comprobación semántica mínima (2026-11-09)

Corrección posterior a la aprobación de `c8fceab`. Las herramientas entregan `form_text`, `limits_text`
y `assessment` calculados en código. La evaluación de rendimiento interpreta CLV, yield y log loss;
explica que no hay tasa de aciertos del mercado en el payload y no inventa esa comparación.
Las probabilidades de analyze_match y simulate_match conservan su `summary` y `favorite` etiquetados.
El prompt exige copiar estos textos para la idea correspondiente.

`check_claims` comprueba tres confusiones acotadas: porcentajes de topes asociados al horizonte equivocado,
conteos de forma incompatibles con `last5_counts` y polaridad del CLV invertida. Los hallazgos se integran
en la reparación existente antes de emitir tokens. Una segunda respuesta inválida queda bloqueada.
No es una validación general de significado. Con varios equipos en el turno se omite la comparación
automática de conteos para no adjudicar a uno las cifras del otro. Las asociaciones por oración pueden
rechazar frases compuestas ambiguas: las frases canónicas separan cada tope en una oración.

Se repitió la conversación completa, en orden, con Qwen 2.5 de 7B y herramientas reales, usando
`scripts/eval_agent_routing.py --mode conversacion --output reports/agente/conversacion-interpretacion.json`.
La columna siguiente fue revisada manualmente; `done.success` solo expresa el resultado del verificador,
no esta revisión semántica.

| Pregunta | Herramienta esperada usada | Interpretación correcta (revisión manual) | Latencia (s) |
|---|---|---|---:|
| Analiza el partido de la roja | Sí | No evaluable: bloqueada tras reparación numérica | 26,301 |
| ¿Y quién es favorito? | No | No: pide identificar el partido; el turno anterior no guardó respuesta ni entidades | 8,813 |
| ¿Cómo llega el Colo Colo? | Sí | Sí: 2 ganados, 2 empatados, 1 perdido; EEPGG | 9,806 |
| Simula Colo Colo contra la U | Sí | Sí: favorito Colo Colo; probabilidades etiquetadas correctamente | 9,463 |
| que partidos vienen ahora? | Sí | No: conversión UTC/Chile incorrecta y conclusión de valor no sustentada por el calendario | 12,054 |
| ¿Qué apuestas con valor hay hoy? | Sí | No: atribuye actualización a una herramienta que no informa frescura | 7,816 |
| ¿Por qué no hay apuestas recomendadas? | Sí | Parcial: identifica cobertura de dos partidos, pero la frase «sin este precio» generaliza esa ausencia | 16,037 |
| ¿Qué tan fiable es el sistema? | Sí | Parcial: CLV negativo desfavorable y yield negativo pérdida correctos; omite decir explícitamente cuál log loss es mejor | 22,084 |
| ¿Cuánto debería apostar si tengo 100.000 pesos? | Sí | Sí: $2.000 por apuesta, $10.000 diarios, topes sin apuesta sugerida | 8,890 |
| Dame una combinada segura para hoy | Sí (política sin LLM) | Sí: rechaza seguridad y remite a Combinadas educativa | 0,000 |

**Resultado completo: 9/10 herramientas esperadas, cero copias literales del turno anterior.** Las tres
confusiones solicitadas no aparecieron en el texto final. Rendimiento necesitó reparación; límites y forma
respondieron con los conceptos correctos, aunque el modelo no siempre copió literalmente toda la frase.
No se afirma que las diez interpretaciones sean correctas: la tabla conserva los defectos adicionales.
Comparación con la batería anterior: forma pasó sin error en aquella ejecución, pero Gustavo observó
conteos erróneos en vivo; CLV y topes diarios estaban invertidos en la evidencia anterior. Esta nueva prueba
comprueba su corrección, sin establecer una tasa general de fiabilidad ni una mejora de latencia.

Para investigar el bloqueo inicial se repitieron **solo los dos primeros turnos**, sin cambiar código ni datos
deliberadamente y sin inferencias concurrentes. El primer análisis pasó a 15,103 s; la evidencia separada está
en `reports/agente/interpretacion-diagnostico-turnos.json`, con borradores numéricos locales en
`interpretacion-diagnostico.json`. Este diagnóstico no reemplaza ni mejora el resultado de la batería completa.
Las respuestas dependen del modelo y siguen siendo variables.

Validación: **420 pytest**, cobertura agéntica **95,36 %** (1486 sentencias, 69 sin cubrir), Ruff,
sintaxis de agent.js y ocho pruebas Node correctos. FakeLLM verifica reparación para conteos, ambos
topes cruzados y ambas polaridades del CLV; las versiones correctas pasan sin publicar el borrador erróneo.
Motor y contrato SSE intactos. Pieza 4 sin iniciar; este commit se entrega para revisión.
