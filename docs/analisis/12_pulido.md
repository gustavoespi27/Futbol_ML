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
