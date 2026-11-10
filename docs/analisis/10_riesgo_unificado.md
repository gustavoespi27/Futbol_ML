# Revisión A2 — Riesgo unificado en 2%

Generado 2026-11-09T13:57:06Z.

Regenerado con `scripts/regenerate_stake_reports.py`, sin reentrenar ni seleccionar umbrales nuevos. La comparación usa los mismos datos y modelos, cambiando solo el tope de la regla original.

| Tope | Apuestas | Yield plano | Banca final (inicio 100) | Caída máxima Kelly |
|---|---:|---:|---:|---:|
| 2.5% | 154 | -5.00% | 93.32 | 19.50% |
| 2.0% | 154 | -5.00% | 91.44 | 18.91% |

El cambio de tope también puede cambiar el orden por crecimiento esperado y la selección por partido. Se regenera la curva completa en data/processed/combo_backtest.json, no se escalan cifras.

El profesional ya usaba 2% por apuesta y 10% diario: se recalcula su informe 06 con los CSV locales. Los informes 02/03 evalúan otra regla histórica mediante betting.backtest, con su propio tope 5% y apuestas planas: sus cifras no dependen de suggestions.MAX_STAKE. Se preserva su experimento, sin presentarlo como la política de producción.
