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

## 2026-10-07 — Límites verificados del plan gratuito de API-Football

IDs de liga confirmados: Chile 265 (2018–2026), Argentina 128 (2015–2026), Brasil 71 (2010–2026). Cobertura de la temporada actual: eventos, alineaciones, estadísticas de partido y jugador, cuotas; lesiones solo en Brasil.

Restricciones del plan Free (100 peticiones/día):

- Consultas por temporada (`/fixtures`, `/odds` con `season`): **solo 2022–2024**.
- Consultas por fecha: solo una ventana móvil de ~ayer a pasado mañana (`/fixtures?date=`, `/odds?date=` funcionan en esa ventana).

**Consecuencias:**

1. Histórico de Chile 2022–2024 (240 partidos por temporada) descargable una vez, con estadísticas de partido. 2025 no es accesible: hay un hueco que cubrir con otra fuente.
2. Un job diario puede recolectar partidos, cuotas pre-partido y alineaciones de ARG/BRA/CHL dentro de la ventana. Ese dataset propio es el único con marca de tiempo real ("qué se sabía antes del partido") y es la base para backtesting en Chile.
3. Presupuesto de peticiones: priorizar `/odds?fixture=` solo para partidos de las tres ligas, en vez de paginar `/odds?date=` completo.

## 2026-10-07 — Regla de apuesta por EV relativo

Se apuesta solo si `p_modelo × cuota − 1 > min_ev`, con la probabilidad del mercado sin margen como referencia. Un umbral en puntos porcentuales de edge no es comparable entre cuotas distintas.
