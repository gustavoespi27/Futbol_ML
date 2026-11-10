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
