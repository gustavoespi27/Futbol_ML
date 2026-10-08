# Registro de decisiones

Cada decisión de diseño relevante queda anotada aquí con su fecha y motivo.

## 2026-10-07 — Alcance inicial: Sudamérica (ARG, BRA, CHL)

**Decisión:** el MVP se centra en Primera División de Chile, Liga Profesional Argentina y Brasileirão.

**Hipótesis a contrastar (no a asumir):** el mercado es menos eficiente en estas ligas que en las grandes ligas europeas. Esto se mide comparando nuestro modelo contra las cuotas de cierre sin margen (log loss / RPS) y con CLV; si el mercado gana, el sistema debe concluir que no hay ventaja.

**Datos disponibles (verificado):**

| Liga | Resultados | Cuotas históricas | Estadísticas (tiros, xG) |
|---|---|---|---|
| ARG | football-data.co.uk desde 2012/13 (~6.400 partidos) | Solo **cierre** 1X2: Pinnacle (hasta 2025), máx., promedio, Betfair Exchange, Bet365 | No |
| BRA | football-data.co.uk desde 2012 (~5.600 partidos) | Igual que ARG | No |
| CHL | API-Football (requiere key) | **Ninguna fuente gratuita verificada** | API-Football (cobertura por temporada a verificar) |

**Consecuencias:**

1. En ARG/BRA solo existen cuotas de cierre. El backtest apostará a cuota de cierre, que es el escenario más exigente (mercado más eficiente). Una ventaja ahí es una señal fuerte; la ausencia de ventaja ahí no descarta ventaja con cuotas tempranas, pero no podremos probarlo con datos históricos.
2. Chile: se puede modelar y predecir, pero no hacer backtest de apuestas hasta reunir cuotas. Se recolectarán snapshots diarios de cuotas (API-Football) desde ahora. Alternativa a evaluar: CSVs de FootyStats (posible pago).
3. Mientras no haya tiros/xG, los modelos se basan en goles, Elo y contexto (descanso, congestión, viajes/altura).

## 2026-10-07 — Regla de apuesta por EV relativo

Se apuesta solo si `p_modelo × cuota − 1 > min_ev`, con la probabilidad del mercado sin margen como referencia. Un umbral en puntos porcentuales de edge no es comparable entre cuotas distintas.
