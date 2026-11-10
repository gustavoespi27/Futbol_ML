# Demo del agente — jueves 12 de noviembre de 2026

Duración: seis minutos. Mostrar cómo consulta, recuerda, rechaza una premisa insegura y crea un
objetivo que el vigía cumple después, con evidencia de sus decisiones. Las apuestas son seguimiento
en papel; no presentar una predicción como garantía de ganancia.

## Antes de presentar

1. Ejecutar `.venv\Scripts\python scripts/daily.py` con tiempo suficiente y esperar a que termine.
   Comprobar en la franja la fecha real de actualización y en Partidos la cobertura de Pinnacle.
   No ejecutar ingesta o entrenamiento durante los seis minutos.
2. Cerrar las otras pestañas del chat y esperar a que no haya consultas en curso. Previsualizar el reset
   con `.venv\Scripts\python scripts/reset_agent_demo.py`. Solo cuando se quiera empezar de cero,
   ejecutar el mismo comando con `--yes`. Vacía únicamente watches, alerts, watch_state, watch_log,
   runs y chat_memory del agente; conserva preferencias, otras tablas del agente y todo el motor.
   No usar ids de ensayos anteriores: SQLite puede reutilizar algunos al quedar vacía una tabla.
3. Precargar el modelo con una consulta: `ollama run qwen2.5:7b "Responde solo: listo"`.
   Esto calienta Ollama sin ensuciar la memoria del chat. No cambiar modelo ni límites para la demo.
4. Arrancar `.venv\Scripts\python scripts/serve.py --no-browser` y abrir la app. Recargar la pestaña
   después del reset para limpiar también los mensajes que seguían dibujados en el navegador.
   Para el móvil, usar la URL WiFi que imprime el servidor. Preparar vistas de 390 y 1440 px.
5. Elegir **un partido real que siga dentro de las próximas 24 horas al momento de mostrarlo**,
   preferiblemente con al menos 30 minutos de margen. Copiar nombres e id desde el calendario.
   La disponibilidad cambia: no memorizar Qatar U23 ni otro partido de las capturas como si siguiera próximo.
6. Tener abiertos el terminal del vigía, [la arquitectura](arquitectura_agente.md), la tabla final de
   [evaluación final](analisis/08_capa_agentica.md#pieza-5-evaluación-final-y-cierre) y las capturas de respaldo. Revisar el ensayo completo
   una vez; después hacer reset si se necesita volver a mostrar una creación nueva.

Para elegir el partido con los datos del servidor, en PowerShell:

```powershell
$demoNow = [DateTimeOffset]::UtcNow
$demoFixture = @(Invoke-RestMethod http://127.0.0.1:8000/api/upcoming) |
  Where-Object {
    $demoKickoff = [DateTimeOffset]::Parse($_.kickoff)
    $_.ref -like 'm:*' -and $demoKickoff -gt $demoNow.AddMinutes(30) -and $demoKickoff -le $demoNow.AddHours(24)
  } | Sort-Object kickoff | Select-Object -First 1
if ($null -eq $demoFixture) {
  'No hay un candidato real con ese margen: usar el plan B, sin inventar horarios.'
} else {
  $demoMatchId = [int]($demoFixture.ref -replace '^m:', '')
  $demoFixture | Select-Object ref, home, away, kickoff
  "Avísame cuando falte poco para $($demoFixture.home) vs $($demoFixture.away)"
}
```

No hacer reset tras crear el objetivo que se va a enseñar: también lo borraría. Un reset no reinicia
el resumen diario ni su presupuesto de redacción, porque esas tablas quedan fuera de la lista permitida.

## Guion de seis minutos

| Tiempo | Pregunta o acción exacta | Qué mostrar y explicar |
|---|---|---|
| 0:00–0:50 | «Analiza el partido de la roja» | Pasos de consulta: el apodo identifica a Chile, se obtiene el partido y se consulta su análisis. Mostrar las probabilidades etiquetadas y el favorito. Si falta Pinnacle, explicar que eso impide evaluar ventaja; no impide consultar el pronóstico. Si aparece el respaldo, señalar que usa datos verificados y no una cifra inventada. |
| 0:50–1:25 | «¿Y quién es favorito?» | Mostrar «Continúa con Colombia vs Chile: se consulta el análisis actualizado», tool_start/tool_result de la precarga y el match_id conservado. La consulta ocurre antes de la primera inferencia: la memoria conserva identidad, no probabilidades antiguas. Si la redacción falla la verificación, el respaldo dispone del análisis fresco. |
| 1:25–2:05 | «¿Por qué no hay apuestas recomendadas?» | Cobertura y frescura consultadas, con la cantidad real con/sin Pinnacle. Mostrar recuperación si ocurrió: no es un paso que deba fingirse o forzarse. Ausencia de recomendaciones no significa que se evaluó todo el calendario ni que las probabilidades sean nulas. |
| 2:05–2:30 | «Dame una combinada segura» | Política determinista: rechaza la garantía y remite a la sección educativa, sin gastar una inferencia. |
| 2:30–3:20 | La pregunta que imprimió la selección previa: «Avísame cuando falte poco para LOCAL vs VISITA» | Sustituir LOCAL/VISITA por los nombres reales, sin escribir literalmente el marcador de posición. Mostrar identificación y create_watch, y leer el id real confirmado. Si dice «ya estaba vigilando», explicar que reutilizó la existente: no presentarlo como una creación nueva. |
| 3:20–4:45 | `.venv\Scripts\python scripts/agent_watch.py` y repetirlo una vez | Mostrar PERCIBIR, ACTUAR y DESCARTAR con sus motivos en la consola. Abrir «Avisos del Míster» y señalar el aviso y el contador de la campana. El objetivo kickoff_soon debe cumplirse porque el partido está dentro de 24 h. La segunda ejecución no debe generar otra alerta por la misma vigilancia. Mostrar una decisión descartada de otro partido y explicar su motivo. |
| 4:45–6:00 | Abrir arquitectura y métricas finales | «El LLM decide; el motor calcula; los verificadores controlan comprobaciones concretas; el vigía actúa sin LLM». Mostrar resultado de la corrida, respaldos y p50/p95. Separar herramienta correcta, camino correcto e interpretación manual. Cerrar reconociendo la variabilidad del modelo y que el vigía es el núcleo determinista. |

Colombia–Chile estaba programado para **viernes 13 a las 21:00 de Chile** en la preparación. Su umbral
de 24 h se alcanza el jueves 12 a las 21:00. Si se presenta antes, usar otro partido real para kickoff_soon.
Si el calendario cambió, prevalecen sus datos actuales. No modificar fechas, precios ni reloj para fabricar una alerta.

## Plan B

- **La redacción falla, pero ya consultó datos:** enseñar «Se entrega el resumen verificado de los datos
  consultados». Mostrar que la respuesta sale de las frases canónicas de las tools y pasa verificación.
  El respaldo no garantiza contestar si el modelo nunca consultó datos útiles.
- **Falla el seguimiento:** preguntar «Analiza el partido de LOCAL vs VISITA» con nombres explícitos
  o mostrar la captura del seguimiento exitoso. Explicar que la identidad persistió, pero la elección
  de herramientas aún puede fallar. No repetir indefinidamente una consulta ni ocultar el fallo.
- **Ollama no responde:** no intentar arreglarlo durante la presentación. Mostrar la captura del chat y
  ejecutar el vigía con el objetivo real ya creado. Si no se llegó a crearlo, puede prepararse por la
  herramienta tipada desde el terminal con el `$demoMatchId` real elegido antes:

  ```powershell
  .venv\Scripts\python -c "import sys; from footy_agents.tools import execute_tool; print(execute_tool('create_watch', {'match_id': int(sys.argv[1]), 'condition': 'kickoff_soon'}).model_dump_json())" $demoMatchId
  .venv\Scripts\python scripts/agent_watch.py
  ```

  Explicar que esta creación fue manual, no una decisión del LLM. La plantilla, la alerta y la bitácora
  del vigía funcionan sin Ollama. No enviar más preguntas al chat mientras se demuestra ese punto.
- **No hay partido real dentro del margen o datos actualizados:** mostrar las capturas guardadas con su
  fecha y condición de ensayo. El vigía en vivo debe registrar el descarte; no prometer una alerta nueva.

## Evidencia y reproducción

La evaluación final se reproduce con:

```powershell
.venv\Scripts\python scripts/eval_agent_routing.py --mode cierre --output reports/agente/pieza5-final.json
```

Hace 15 consultas secuenciales con Qwen 2.5 de 7B: diez preguntas, crear/listar/cancelar y dos seguimientos.
Usa herramientas reales y escribe solo registros propios del agente. Genera resultados, eventos y
`pieza5-final.metrics.json`; la interpretación debe revisarse a mano, no se deduce de done.success.
La evidencia de esta preparación y los enlaces a capturas se mantienen en
[08_capa_agentica.md](analisis/08_capa_agentica.md). No afirmar que una sola corrida garantiza el resultado
de la presentación ni convertir p50/p95 de quince consultas en un compromiso de latencia.

Último ajuste autorizado antes de congelar: el seguimiento con match_id precarga su análisis.
Se validó en tres pares reales: 3/3 seguimientos respondidos en una inferencia, sin reparación ni respaldo.
La tabla histórica de quince turnos conserva el fallo anterior; la evidencia posterior está en
[precarga del seguimiento](analisis/08_capa_agentica.md#precarga-del-seguimiento-antes-de-congelar-2026-11-10).
