# Análisis 04 — Dixon-Coles con tiros

*Generado por `scripts/evaluate_shots.py`.*

El objetivo del modelo pasa de "goles" a `mix × goles + (1 − mix) × goles esperados por tiros`,
con los coeficientes de tiros al arco / fuera estimados en cada ventana de entrenamiento (sin leakage).
`mix` se elige en validación 2016-21 entre [1.0, 0.75, 0.5, 0.25]; el resto de hiperparámetros es el del análisis 03.
Comparación en test 2022-25, **partido a partido** (Δ log loss × 1000; negativo = mejora).

**Resultado agregado (1225 partidos de test, 1 ligas):**

- Dixon-Coles con tiros vs solo goles: **+0.00 (IC95% [+0.00, +0.00])**
- Elo+DC con tiros vs sin tiros: **+0.00 (IC95% [+0.00, +0.00])**
- Ensamble con el mercado, con tiros vs sin tiros: **+0.00 (IC95% [+0.00, +0.00])**
- El modelo Elo+DC mejora en **0 de 1** ligas; supera al mercado en **0 de 1**.

![Comparación](figs/04_tiros.png)

| Liga               |   mix elegido |   Partidos test | Δ DC (tiros − goles)   |   Δ Elo+DC vs mercado antes |   Δ Elo+DC vs mercado ahora |   Δ ensamble vs mercado antes |   Δ ensamble vs mercado ahora | Yield test antes   | Yield test ahora   |   Apuestas ahora |
|:-------------------|--------------:|----------------:|:-----------------------|----------------------------:|----------------------------:|------------------------------:|------------------------------:|:-------------------|:-------------------|-----------------:|
| P1 · Primeira Liga |             1 |            1225 | +0.0 [+0.0, +0.0]      |                        18.4 |                        18.4 |                          -2.6 |                          -2.6 | +6.7%              | +6.7%              |               94 |
