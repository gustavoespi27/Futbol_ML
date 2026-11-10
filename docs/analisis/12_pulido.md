# Pulido final para la presentación

Rama `feature/pulido`, base `a3ace71`. Alcance de `docs/plan_pulido.md`; P2 queda excluido.

## P0-1 — Modo presentación

Activación con `?demo`, persistencia en sessionStorage y alternancia con Ctrl+Shift+D. Desactivado por defecto;
el chat normal no crea bloques de pasos. Los eventos SSE reales se agrupan sin alterar su orden: herramienta
pendiente → resultado con ✓/✕ y ms; observaciones, desvíos, recuperaciones, reparaciones y políticas.
Etiquetas en español, incluido «Consultó al Ojeador». Los textos se escapan antes de mostrarse.
El bloque «Cómo lo resolvió» conserva su estado y el foco del resumen mientras llegan eventos.
Los pasos pertenecen a los turnos de esta sesión del navegador; no se inventan trazas al abrir un historial
que solo conserva preguntas/respuestas. La bitácora completa sigue disponible en el backend.

Validación: **663 pytest**, Ruff, sintaxis JS y **11 pruebas Node**. Chrome real con un turno de cuotas de
Colombia–Chile: recuperación y desvío al Ojeador visibles, sin errores JS ni overflow a 390 px. Atajo y
persistencia al recargar comprobados. Evidencia local `reports/pulido/p0-1-ui.json`.
Capturas: `docs/img/pulido/p0-1-{demo,normal}-{390,1440}.png` y `p0-1-demo-en-vivo-390.png`.

## P0-2 — Precios ofrecidos frente a referencia Pinnacle

Helper único `FootyTrust.priceState` para lista, semáforo, Hoy y la nota ML del detalle: sin precios →
«sin cuotas aún»; con precios ofrecidos → «Precio [casa real] · sin referencia Pinnacle»; con referencia,
se conserva el comportamiento del profesional. DraftKings aparece «vía ESPN» en el comparador.

Se corrigieron además dos contradicciones detectadas al revisar el alcance: el contexto web conserva las
cuotas ofrecidas aunque no haya modelo válido (sin inventar probabilidades), y el comparador visual ya no
usa la probabilidad del modelo para pintar +EV ni «cuota justa». La fila de precio justo usa exclusivamente
los fair_odds calculados frente a Pinnacle en `pro`; sin ellos no se muestra ventaja. Pinnacle y agregados
no se tratan como casas apostables. No cambian predicciones, stake ni fórmulas del motor.

Textos restantes «sin cuotas»: solo se conservan para ausencia real de precios, cuotas de referencia,
entradas vacías del simulador o documentación interna. Se corrigieron las recomendaciones web que
antes negaban precios existentes en ramas sin referencia/modelo.

Validación: **665 pytest**, Ruff, sintaxis JS y **13 pruebas Node**. Argentina–Uruguay real muestra
«Precio DraftKings · sin referencia Pinnacle» y el detalle «DraftKings · vía ESPN», sin +EV ni precio justo
del modelo presentado como referencia. Chrome 390/1440, sin errores JS ni overflow.
Capturas `docs/img/pulido/p0-2-argentina-{lista-1440,detalle-390,detalle-1440}.png`;
evidencia local `reports/pulido/p0-2-ui.json`.

## P0-3 — Frescura y porcentajes

check_claims exige get_coverage exitoso en el turno para afirmar frescura; una consulta fallida no basta.
Detecta porcentajes presentados como cuotas, preservando cuota decimal y probabilidad/ventaja correctamente
identificadas. Pruebas positivas, negativas y reparación con FakeLLM que consulta cobertura.
Validación: **688 pytest** y Ruff. No cambia el motor ni los contratos SSE.

## P0-4 — Evaluación real del pulido

Modo reproducible `--mode pulido`: ocho turnos secuenciales con memoria SQLite aislada, Qwen 2.5 7B
local y herramientas reales. Cinco turnos son deliberadamente deterministas y no llaman al LLM;
por eso el percentil global no representa la velocidad de inferencia. No se modificó el agente para pasar.
Evidencia revisada: [evaluacion_pulido.json](evaluacion_pulido.json).

| Turno | Herramienta/política | Camino | Interpretación manual | Reparaciones / recuperaciones | Segundos |
|---|---|---|---|---|---|
| Recomendaciones | ✓ | ✓ | Correcta | 0 / 0 | 0,017 |
| Más fiables | ✓ | ✓ | Correcta, repite otras pestañas | 0 / 0 | 0,005 |
| Casi con valor | ✓ | ✓ | Correcta, repite otras pestañas | 0 / 0 | 0,003 |
| Cuánto paga Colombia–Chile | ✓ | ✓ | Ausencia actual de precios, sin inventar | 0 / 1 | 15,535 |
| Comparar con contexto | ✓ | ✓ | Mismo resultado sin precios; texto idéntico | 0 / 1 | 12,982 |
| Me llamo Gustavo | ✓ | ✓ | Correcta; no prueba persistencia HTTP | 0 / 0 | 0,000 |
| Apuesta segura | ✓ | ✓ | Rechaza garantía y distingue probabilidad/valor | 0 / 0 | 0,004 |
| Cuotas con valor hoy | ✓ | ✓ | Fallida: mensaje seguro tras reparación | 1 / 0 | 14,084 |

**8/8 herramientas y caminos; 7/8 respuestas verificadas; 1 reparación fallida; 2 recuperaciones;
0 respaldos canónicos; 1 salida segura sin datos útiles; p50 0,011 s y p95 15,027 s.**
Los tres turnos con inferencia tuvieron p50 14,084 s y p95 15,390 s.
La repetición entre turnos 4/5 es real: ambos consultan el mismo partido sin cuotas; no es evidencia de
contaminación, pero tampoco se presenta como ausencia de repeticiones. No se vio ninguna cifra inventada
en el texto finalmente entregado. La salida segura cuenta como fallo, no como interpretación correcta.

Comparación: la batería de cierre anterior (§Pieza 5 de `08_capa_agentica.md`) tuvo 14/15 herramientas,
14/15 respuestas y p50 10,897 s / p95 18,784 s. Son conjuntos y proporciones deterministas diferentes;
no permiten afirmar mejora global de exactitud o velocidad. El sondeo C7 de tres consultas de cuotas
(§C7 del mismo documento) tuvo 3/3, cero reparaciones y latencias 9,068–14,011 s; el pulido mantiene
dos delegaciones correctas, con datos actuales sin precios y 12,982–15,535 s.

Validación: **689 pytest** y Ruff. Límite conocido: una herramienta correcta no garantiza que el LLM
logre redactar una respuesta verificable; con lista de valor vacía puede terminar en salida segura.

## P1-1 — Selecciones en español

Mapa único `static/team-display.json`, compartido por Python y navegador. La web traduce nodos de texto,
incluidos historial, chat y contenido cargado después; no cambia atributos value/data, IDs, cachés ni peticiones.
Las herramientas conservan home/away/team canónicos, añaden *_display y presentan sus frases canónicas
en español. El prompt distingue etiquetas públicas y argumentos canónicos. No cambia la base ni el calce.
Ejemplos: Chequia, España y Taiwán; juveniles conservan el sufijo. Mapa explícito, sin traductor ni red.

Validación: **691 pytest**, Ruff, sintaxis JS y **14 Node**. Pruebas de cifras intactas, entradas sin mutación,
límites de palabra y find_team con «la roja»/Spain conservando el mismo match_id y nombre canónico.
