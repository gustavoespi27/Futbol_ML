# Evaluación reproducible de la capa agéntica

> Cierre vigente: [pieza 5, evaluación final y demo](#pieza-5-evaluación-final-y-cierre).
> El resto del documento conserva las mediciones históricas; no son el resultado de cierre.

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

## Respaldo determinista y horas locales (2026-11-09)

Tras la aprobación de `cb82190`, se incorpora `fallback.py`. Si la reparación no consigue una respuesta
verificada, compone los textos del turno en orden: summary/favorite de análisis o simulación, form_text,
limits_text, assessment, freshness/rule y notas de observación. También puede entregar el calendario
consultado con los nombres y kickoff_local existentes. El resumen elimina textos duplicados y debe pasar
verify_numbers **y** check_claims antes de emitir el step «Se entrega el resumen verificado de los datos
consultados» y done.success=true. Sin textos útiles o si falla esa comprobación conserva SAFE_TEXT y
done.success=false. El mismo respaldo aprovecha datos útiles si el modelo devuelve texto vacío, insiste
en pseudollamadas o agota las iteraciones; no requiere otra inferencia.

El router guarda las entidades consultadas aun con done.success=false. En ese caso guarda una respuesta
vacía que history no reenvía al LLM; el seguimiento conserva identidad sin reutilizar el texto fallido.
Las respuestas de respaldo verificadas sí se recuerdan. No cambia el esquema de las tablas ni el SSE.

get_upcoming_matches, analyze_match y find_team.next_match incluyen kickoff_local calculado con la zona
America/Santiago. Ejemplo real: **vie 13-11, 21:00 hora de Chile**, correspondiente al kickoff UTC del 14
de noviembre a medianoche; el día de la semana se calcula, sin depender del idioma de Windows. El prompt
prohíbe conversiones manuales. El verificador admite la fecha/hora local de la herramienta y rechaza una
fecha/hora canónica diferente. Esto no equivale a verificar todas las paráfrasis posibles de fechas y horas.

Sondeo solicitado: dos secuencias independientes **turno 1 → turno 2 → turno 5**, cada una con memoria
aislada y Qwen 2.5 de 7B real, una consulta a la vez. Comando reproducible:

```powershell
.venv/Scripts/python scripts/eval_agent_routing.py --mode respaldo --output reports/agente/demo-respaldo.json
```

| Repetición | Turno | Herramientas | Respaldo | Respuesta / revisión manual | Latencia (s) |
|---|---|---|---|---|---:|
| 1 | 1: analiza la roja | upcoming → analyze_match(181043) | Sí | Colombia 67,5 %, empate 20 %, Chile 12,5 %; favorito Colombia; sin Pinnacle | 27,083 |
| 1 | 2: ¿y quién es favorito? | analyze_match(181043) | No | Colombia; conserva el partido y la hora local correctos | 12,125 |
| 1 | 5: qué partidos vienen | upcoming | No | Cinco horarios de Chile correctos; conclusión final de ausencia de valor no respaldada por esta herramienta | 11,816 |
| 2 | 1: analiza la roja | upcoming → analyze_match(181043) | Sí | Mismo resumen calculado y advertencia; ninguna cifra del borrador inválido | 27,037 |
| 2 | 2: ¿y quién es favorito? | analyze_match(181043) | No | Colombia; no pide de nuevo identificar el partido | 11,755 |
| 2 | 5: qué partidos vienen | upcoming | No | Horarios correctos; aclara falta de referencia Pinnacle para los últimos tres partidos | 11,880 |

`upcoming` abrevia get_upcoming_matches. **6/6 herramientas esperadas y 6/6 respuestas no vacías, todas
con done.success=true; dos respaldos efectivos.** Ningún SAFE_TEXT ni copia literal del turno previo en
estas secuencias. El respaldo resolvió precisamente el análisis inicial que en la batería anterior quedó
bloqueado y perdió las entidades. La cantidad de muestras es pequeña: no garantiza disponibilidad ni
corrección general. En particular, el comentario sobre valor del primer calendario sigue fuera de las
comprobaciones semánticas acotadas y no se considera aprobado.

Evidencia completa: `reports/agente/demo-respaldo.json`, `demo-respaldo-1.json` y `demo-respaldo-2.json`
(eventos, argumentos, respuestas y latencias). Los datos de producción pueden cambiar entre pruebas.

Validación final: **431 pytest**, cobertura agéntica **95,64 %** (1560 sentencias, 68 sin cubrir), Ruff,
sintaxis de agent.js y ocho pruebas Node correctos. El módulo de respaldo tiene cobertura del 100 %.
FakeLLM prueba doble fallo con datos, SAFE_TEXT sin datos, fallos terminales y seguimiento después de error
o respaldo; se comprueba el horario local en las tres tools, tanto en verano como en invierno.
Motor intacto; ejecución detenida tras el commit para revisión, antes de la pieza 4.

## Pieza 4: acciones y vigía autónomo (2026-11-09)

Se implementaron create_watch, list_watches, cancel_watch y add_favorite con argumentos Pydantic estrictos.
La identidad procede del request, nunca del LLM. El ruteo reconoce las intenciones de avisar, listar,
cancelar y agregar favoritos. Una pregunta de lectura no autoriza escrituras. Antes de crear, el chat
debe identificar el objetivo mediante find_team/analyze_match; una precarga sola no basta. El conjunto
de herramientas ofrecidas respeta esa etapa y el propósito solicitado. Se conserva el límite original
de rondas. Las confirmaciones se arman en código a partir de los ids realmente devueltos, sin otra
inferencia. Una vigilancia idéntica activa devuelve la existente con «ya estaba vigilando».

Persistencia propia: agent_watches, agent_watch_state, agent_alerts y agent_watch_log, además de las
preferencias existentes. DDL idempotente e índices únicos para objetivos activos y alertas. Estado,
alerta y fulfilled se escriben en la misma transacción BEGIN IMMEDIATE; dos vigías concurrentes no
duplican alertas. No se escribe en pro_bets, daily_picks ni en tablas del motor.

El vigía ejecuta percibir → comparar → decidir → actuar → registrar. Lee service.upcoming y conserva
Pinnacle, edge, elegibilidad real (`bet`), probabilidades oficiales, kickoff y fuente. Compara líneas
crudas de Pinnacle (movimiento relativo ≥5 %) y probabilidades (≥3 puntos porcentuales). Inicio cercano
significa próximas 24 horas; la regla global de pérdida de cobertura solo alerta en las últimas 12 horas.
La primera percepción establece línea base para transiciones globales. Los objetivos explícitos de
precio disponible o valor elegible pueden cumplirse con el estado ya disponible. Los objetivos son de
una sola ejecución: cumplidos pasan a fulfilled. La prioridad ordena por kickoff y edge; una vigilancia
explícita prevalece sobre la misma regla global, evitando dos avisos del mismo evento.

Cada decisión, también los descartes y su motivo, queda en la bitácora junto al snapshot percibido.
Los textos salen exclusivamente de plantillas con cifras en facts y pasan verify_numbers antes de
guardarse. **El vigía no crea clientes LLM, no inicia Ollama y no lo consulta.** La ausencia de LLM está
probada con funciones de arranque/inferencia prohibidas durante el test. daily y prekickoff lo llaman
al finalizar dentro de try/except; su fallo no rompe el pipeline. La salida de prekickoff sin partidos
conserva la prueba de no importar numpy/pandas/sklearn: el servicio y el verificador se importan de forma
perezosa cuando son necesarios. Las escrituras agent_* no invalidan la revisión de datos del motor.

Endpoints nuevos, con contratos extra=forbid:

| Método y ruta | Uso |
|---|---|
| GET /api/agent/alerts?user_id=default&unread=true | Alertas pendientes del usuario; sin disparar el vigía |
| POST /api/agent/alerts/{id}/read | JSON `{ "user_id": "default" }`; 404 si no pertenece al usuario |
| GET /api/agent/watches?user_id=default | Objetivos y estados |
| GET /api/agent/watch-log?user_id=default&limit=20 | Snapshot, decisiones, motivos, acciones y tiempo; límite 1–100 |

La UI vanilla muestra alertas arriba, badge del FAB y «Bitácora del agente» con ejecuciones del chat y
vigía. Los detalles se despliegan con teclado; conserva expansión, posición y foco al refrescar.
Sondea cada 30 segundos solo con la página visible, sin iniciar el vigía ni Ollama. Un refresco pedido
mientras otro está en curso se ejecuta después: marcar leída no deja el badge atrasado.

### Validación con los datos reales

`scripts/validate_agent_watch.py --output reports/agente/pieza4-datos-reales.json --publish` leyó el
snapshot real: **40 partidos, 2 con Pinnacle y 0 con una selección elegible de valor**. Validó ambos
objetivos para todos los partidos en tablas aisladas, copiando solo las identidades reales: dos
alertas pinnacle_available y ninguna value_appears; repetición inmediata, cero alertas nuevas.
No se alteraron cuotas para producir una oportunidad inexistente. Hay edges positivos de 10,24 % y
11,59 % en los dos partidos con precio, pero el motor marca bet=false: el vigía no los convierte en
recomendaciones. El caso positivo real de value_appears queda pendiente de que ocurra; el disparo
positivo y sus límites están cubiertos por tests controlados, no se presenta como ocurrido en producción.

Con --publish se crearon en tablas propias los objetivos 3 (Pinnacle) y 4 (valor) para Qatar U23–Singapore
U23, match_id=181054. En la app, `scripts/agent_watch.py` produjo la alerta **1**, cumpliendo el objetivo 3;
el 4 sigue pendiente sin valor elegible. Esa alerta real se ve en el panel y el badge. Se probó marcarla
leída desde la UI, actualización inmediata del badge y foco; se restauró sin leer para la revisión.

| Ejecución real | Percibidos | Alertas nuevas | Tiempo del ciclo, incluida lectura del snapshot |
|---|---:|---:|---:|
| agent_watch.py, primera | 40 | 1 | 1405,59 ms |
| agent_watch.py, segunda inmediata | 40 | 0 | 1412,86 ms |
| Después del caso de chat, primera | 40 | 0 | 1422,98 ms |
| Después del caso de chat, segunda | 40 | 0 | 1465,98 ms |

El objetivo de menos de dos segundos se cumplió en estas mediciones locales; no es una garantía para un
snapshot vencido que deba recalcularse. Con los datos ya entregados al ciclo, la validación aislada midió
3,912 y 1,319 ms. JSON y motivos completos en `reports/agente/pieza4-vigia-{1,2}.json`,
`pieza4-vigia-post-chat-{1,2}.json` y `pieza4-datos-reales.json`.

### Chat real y caso obligatorio

Pregunta exacta: «Avísame cuando falte poco para Colombia vs Chile y si aparece precio de Pinnacle».
Desde el panel real: precarga → analyze_match(181043) → create_watch(kickoff_soon) →
create_watch(pinnacle_available), con **ids 1 y 6**. Una ejecución posterior devolvió los mismos ids;
el test de cancelación dejó el 6 cancelado. Se repitió desde el panel para dejar la demo preparada:
**1 activo (inicio) y 7 activo (Pinnacle)**; el 1 se reutilizó sin duplicarlo. Confirmaciones deterministas
con esos ids, pasos visibles y registro en /runs: evidencia `reports/pieza4/chat.json`.

Colombia–Chile comienza **vie 13-11 a las 21:00 de Chile**. Hoy faltan más de 24 horas y no tiene Pinnacle:
los dos objetivos deben seguir pendientes. Una alerta de ese partido ahora sería ficticia. El vigía
registra los descartes por ambos motivos; la alerta visible corresponde al precio real de Qatar U23.
Para mostrar inicio cercano durante la presentación del jueves hay que comprobar antes la hora de
inicio: el umbral de Colombia se cumple el jueves 12 a las 21:00, no antes. El vigía puede demostrarse
con otro partido real que sí esté dentro del umbral, sin cambiar horas ni precios.

Batería de cierre con Qwen 2.5 de 7B, 13 consultas secuenciales y memoria: comando
`scripts/eval_agent_routing.py --mode acciones --output reports/agente/pieza4-cierre.json`.
Ese modo ejecuta escrituras reales propias del agente y registra /runs. Las métricas de acciones exigen
tool_result exitoso e ids confirmados; un intento bloqueado no cuenta como escritura conseguida.

| # | Consulta | Herramienta/camino observado | Resultado | Segundos |
|---|---|---|---|---:|
| 1 | Analiza el partido de la roja | upcoming → analyze_match | Respaldo verificado | 25,664 |
| 2 | ¿Y quién es favorito? | Ninguna | SAFE_TEXT; no completó la consulta | 13,042 |
| 3 | ¿Cómo llega el Colo Colo? | get_team_form | Conteos correctos, aunque filtró etiquetas técnicas en el texto | 18,283 |
| 4 | Simula Colo Colo contra la U | simulate_match | Consulta completada | 9,543 |
| 5 | que partidos vienen ahora? | get_upcoming_matches | Consulta completada | 14,467 |
| 6 | ¿Qué apuestas con valor hay hoy? | get_value_bets | Consulta completada | 8,245 |
| 7 | ¿Por qué no hay apuestas recomendadas? | get_coverage | Consulta completada; persisten límites de redacción de cobertura | 12,472 |
| 8 | ¿Qué tan fiable es el sistema? | get_system_performance | CLV/yield desfavorables; mercado con menor log loss | 15,658 |
| 9 | Banca 100.000 pesos | get_stake_limits | Topes correctos tras reparación | 14,929 |
| 10 | Combinada segura | Política determinista | Rechaza premisa sin LLM | 0,009 |
| 11 | Avisar inicio y Pinnacle de Colombia–Chile | upcoming → analyze_match → create_watch ×2 | Reutiliza ids 1 y 6, sin duplicados | 9,220 |
| 12 | ¿Qué vigilas? | list_watches | Lista ids reales y condiciones | 3,648 |
| 13 | Deja de vigilar la vigilancia 6 | cancel_watch(6) | Confirmación de cancelación real | 3,771 |

**12/13 herramientas esperadas y turnos completados; acciones 3/3; cero copias literales del turno previo.**
El fallo del turno 2 conserva la variabilidad ya documentada de Qwen: tener las entidades no garantiza
que consulte; el verificador bloqueó su respuesta. No se declara 13/13 ni corrección semántica general.
El vigía y las confirmaciones de escritura son deterministas; la elección conversacional de herramientas
sigue dependiendo del modelo. Las pruebas previas `pieza4-conversacion*.json` también se conservan: una
iteración intermedia intentó crear sin identificar y fue bloqueada; la oferta de herramientas por etapa
resolvió ese defecto. Un fallo intermedio desde el panel buscó el nombre compuesto «Colombia vs Chile»;
find_team ahora puede resolver su primer equipo y la precarga prioriza analizar el id conocido.

### Verificación y capturas

**478 pytest**, cobertura agéntica **95,97 %** (1937 sentencias, 78 sin cubrir), Ruff, sintaxis de agent.js
y ocho pruebas Node correctos. Incluye cada condición y umbral, inexistencia de targets, modelos extra=forbid,
identidad del request, aislamiento de usuario, escrituras no solicitadas bloqueadas, deduplicación,
concurrencia, migración, plantillas verificadas y pruebas HTTP. Un autorizador SQLite prohíbe escrituras
fuera de agent_* durante el test del ciclo. El mapa local de CLAUDE.md §3 fue actualizado sin versionarlo.

Auditoría real en Chrome: 390×844 y 1440×900, claro/oscuro, cero desbordamientos, cero fallos de contraste
y cero errores JS; botones nuevos ≥44 px. Lectura de alerta con badge y foco comprobados. Evidencia en
`reports/pieza4/ui.json`, `leida.json` y capturas:

- [Chat móvil con pasos y confirmaciones](../img/agente/pieza4-chat-390-dark.png).
- [Alerta real en móvil](../img/agente/pieza4-alertas-390-light.png).
- [Bitácora móvil](../img/agente/pieza4-bitacora-390-light.png).
- [Bitácora en escritorio](../img/agente/pieza4-bitacora-1440-dark.png).

Variantes restantes en `docs/img/agente/pieza4-*.png`. No cambió el motor ni el contrato SSE. La pieza 4
se entrega en un único feat(agents) y se detiene para revisión; pieza 5 pendiente.

## Pieza 5: evaluación final y cierre

Agente aprobado: `6cb18aa`. Esta pieza solo añade evaluación, reset, pruebas y documentación: **sin
cambios en src/footy_agents ni en el motor o la interfaz**. Guion de seis minutos en
[demo_agente.md](../demo_agente.md) y [diagrama de arquitectura](../arquitectura_agente.md).

### Método y evidencia

Qwen 2.5 de 7B real; 15 turnos en orden: conversación de diez preguntas, crear/listar/cancelar y dos
seguimientos adicionales. Herramientas reales, memoria de evaluación aislada y escrituras/bitácora
reales sobre tablas propias del agente. El script envía una consulta por vez; no modifica el prompt,
la selección de herramientas ni las respuestas. Comando:

```powershell
.venv\Scripts\python scripts/eval_agent_routing.py --mode cierre --output reports/agente/pieza5-final.json
```

Las salidas completas y los argumentos, ids y revisiones manuales se publican en
[evaluacion_agente_final.json](evaluacion_agente_final.json). El archivo local conserva además todos
los eventos SSE. La evidencia se vinculó por pregunta y orden con las ejecuciones reales de /runs.
Se detectó una consulta de UI ajena al set intercalada en ese intervalo (run 128): no se contó entre
los quince ni se borró. El historial del evaluador permaneció aislado, pero **no se afirma exclusividad
de carga**: las latencias pueden incluir contención con esa otra consulta.

«Herramienta correcta» mide selección; «camino correcto» exige éxito, orden y argumentos del objetivo,
sin herramientas de otro tema. Crear exige identificación previa y ambas condiciones para match 181043;
cancelar exige el id real confirmado; los seguimientos deben reconsultar el mismo match_id sin resolver
otra vez el nombre. Los prerrequisitos y desvíos permitidos están definidos en path_correct del script.
La interpretación de la tabla fue **revisada a mano**; no se deriva de done.success.

### Tabla final

| # | Pregunta | Herramienta correcta | Camino correcto | Interpretación manual | Respaldo | Reparaciones | Recuperaciones | Latencia (s) |
|---|---|---|---|---|---|---:|---:|---:|
| 1 | Analiza el partido de la roja | Sí | Sí | Correcta: favorito Colombia, cifras y falta de Pinnacle | Sí | 1 | 1 | 27,980 |
| 2 | ¿Y quién es favorito? | No | No | Sin respuesta: SAFE_TEXT, no consultó | No | 1 | 1 | 13,269 |
| 3 | ¿Cómo llega el Colo Colo? | Sí | Sí | Correcta: 2G, 2E, 1P; distingue promedios de temporada | No | 0 | 0 | 9,188 |
| 4 | Simula Colo Colo contra la U | Sí | Sí | Correcta: xG, probabilidades y favorito etiquetados | No | 0 | 0 | 10,897 |
| 5 | que partidos vienen ahora? | Sí | Sí | Parcial: lista correcta; generaliza ausencia de ventaja sin Pinnacle | No | 0 | 0 | 13,445 |
| 6 | ¿Qué apuestas con valor hay hoy? | Sí | Sí | Parcial: cero selecciones elegibles, sin aclarar cobertura y demás filtros | No | 0 | 0 | 8,651 |
| 7 | ¿Por qué no hay apuestas recomendadas? | Sí | Sí | Parcial: dos con Pinnacle; confunde elegibilidad con ventaja significativa | No | 0 | 0 | 12,762 |
| 8 | ¿Qué tan fiable es el sistema? | Sí | Sí | Correcta: yield/CLV desfavorables; mercado con menor log loss | No | 0 | 0 | 14,843 |
| 9 | Banca de 100.000 pesos | Sí | Sí | Correcta: $2.000 por apuesta y $10.000 diarios | No | 1 | 0 | 14,743 |
| 10 | Dame una combinada segura para hoy | Sí, política | Sí, sin LLM | Correcta: rechaza garantía, remite a uso educativo | No | 0 | 0 | 0,008 |
| 11 | Avisar inicio cercano y Pinnacle de Colombia–Chile | Sí, crear ×2 | Sí | Correcta: analyze_match(181043), ids reales 1 y 2 | No | 0 | 0 | 9,210 |
| 12 | ¿Qué vigilas? | Sí | Sí | Correcta: ids y condiciones activos | No | 0 | 0 | 3,636 |
| 13 | Deja de vigilar la vigilancia 2 | Sí | Sí | Correcta: cancelación del id real | No | 0 | 0 | 3,770 |
| 14 | ¿Y quién es favorito? (después de cancelar) | Sí | Sí | Correcta: reconsulta 181043, favorito Colombia | No | 0 | 0 | 9,730 |
| 15 | ¿Y ese partido tiene precio de Pinnacle? | Sí | Sí | Correcta: reconsulta el mismo partido y confirma que falta Pinnacle | No | 0 | 1 | 13,785 |

Resultado: **14/15 herramientas y caminos correctos; 14/15 turnos con done.success=true; acciones 3/3;
cero copias literales del turno previo**. Hubo 17 llamadas de herramientas con argumentos admitidos
por sus modelos; los dos turnos sin herramientas no demuestran nada sobre ejecución de argumentos.
La revisión estricta distingue **11 interpretaciones correctas, tres parciales y un turno sin respuesta**.
Por eso no se presenta el 14/15 como exactitud semántica general.

Un respaldo resolvió el turno 1. De tres intentos de reparación, uno terminó con redacción válida del
LLM (banca), otro con respaldo verificado y otro con SAFE_TEXT. Dos de las tres recuperaciones acabaron
en el camino correcto; la del turno 2 no logró una consulta. Reparaciones excluye el step que entrega
el respaldo, contabilizado aparte para evitar contar dos veces el mismo intento.

Latencia **p50 10,897 s; p95 18,784 s; máximo 27,980 s**. Percentiles por interpolación lineal inclusiva,
posición (n−1)×p, sobre los quince turnos, incluida la política sin inferencia. Una sola corrida y una
consulta de UI intercalada no permiten establecer un SLA ni atribuir diferencias a una optimización.
Los ficheros .metrics.json reproducidos dejan manual_review pendiente: nunca califican automáticamente
la interpretación. El JSON publicado incorpora la revisión humana explícita de esta corrida.

### Reset y ensayo completo de la demo

`scripts/reset_agent_demo.py` sin --yes mostró conteos sin borrar filas. Con --yes se vaciaron únicamente
agent_watches, agent_alerts, agent_watch_state, agent_watch_log, agent_runs y agent_chat_memory. No hay
comodines, DROP, VACUUM ni modificación de sqlite_sequence. Los ids que SQLite devuelva después no deben
suponerse: algunas tablas pueden reutilizarlos y otras conservan su secuencia.

Pruebas con base temporal: simulación intacta, borrado idempotente, preservación de preferencias/tablas
del motor/otras agent_*, base inexistente no creada y rollback completo si un trigger intenta borrar
preferencias. Un autorizador SQLite limita los DELETE a las seis tablas y rechaza INSERT/UPDATE/DROP.
La ejecución real comprobó preferencias y conteos del motor preservados: `reports/pieza5/reset.json`.
No se crean tablas del agente cuando faltan; solo se limpian las presentes en la lista cerrada.
El reset abre el archivo existente directamente con SQLite (ro para simulación, rw con --yes),
sin el inicializador de schema del motor: tampoco añade tablas del motor en una base parcial.

Después de la batería se capturó el flujo desde el panel real, sin simular respuestas ni cambiar el
agente: apodo → seguimiento → cobertura → política → vigilancia de un partido real dentro de 24 h.
Se eligió **Qatar U23–Singapore U23, match 181054, inicio 2026-11-10T08:00:00Z**. El chat pasó por análisis
y create_watch, confirmó la vigilancia **3** para kickoff_soon y el vigía produjo la alerta **1** con
**5,43 horas restantes**, dato calculado en facts. Una segunda ejecución produjo cero alertas nuevas.
El seguimiento de este ensayo sí consultó analyze_match: es evidencia adicional de variabilidad, no
reemplaza ni mejora retrospectivamente el fallo del turno 2 en la batería final.

Los datos de este ensayo son del momento de preparación: en la presentación debe elegirse otro partido
si ya pasó su inicio. No se alteraron horarios ni cuotas para conseguir la alerta. Las instrucciones
de elección y el plan B están en [el guion](../demo_agente.md). Registros completos en
`reports/pieza5/flujo.json` y `flow-vigia-{1,2}.json`.

Capturas finales reales a 390×844 y 1440×900: chat, alerta y bitácora en claro/oscuro, más apodo con pasos.
Son 14 imágenes en `docs/img/agente/final-*.png`. Auditoría de las 14 variantes: cero desbordamientos,
cero fallos de contraste y cero errores JavaScript. Selección para la exposición:

- [Apodo y pasos, móvil](../img/agente/final-apodo-390-dark.png) · [escritorio](../img/agente/final-apodo-1440-dark.png).
- [Creación desde el chat, móvil](../img/agente/final-chat-390-dark.png) · [escritorio](../img/agente/final-chat-1440-light.png).
- [Alerta real, móvil](../img/agente/final-alerta-390-light.png) · [escritorio](../img/agente/final-alerta-1440-dark.png).
- [Bitácora y descartes, móvil](../img/agente/final-bitacora-390-light.png) · [escritorio](../img/agente/final-bitacora-1440-dark.png).

### Límites conocidos

- Qwen puede omitir una consulta aun con entidades disponibles. Sin datos útiles del turno, el respaldo
  no puede fabricar una respuesta; el guion contempla pregunta explícita, capturas y vigía sin LLM.
- La verificación es acotada: no demuestra pertinencia, cobertura completa ni semántica general. Las
  tres respuestas parciales de valor/cobertura siguen pendientes; esta pieza no cambia ese comportamiento.
- El vigía depende del snapshot y de sus disparos (daily, prekickoff o CLI), no de un proceso continuo.
  Un objetivo solo alerta cuando la condición se observa; la falta de datos o un partido fuera de 24 h
  debe generar un descarte, no una alerta ficticia. No inicia Ollama ni realiza apuestas.
- Las métricas son una muestra pequeña con actividad de UI adicional observada. Fechas, cobertura y
  latencias deben comprobarse de nuevo antes de presentar, sin atribuirles garantías de rentabilidad.

Validación: **488 pytest**, Ruff, sintaxis de agent.js y ocho pruebas Node en verde; cobertura agéntica
**95,97 %** (1937 sentencias, 78 sin cubrir). CLAUDE.md §3 actualizado/comprobado solo en disco.
Se entrega un único test(agents) y se detiene para revisión. Sin cambios de comportamiento del agente.
