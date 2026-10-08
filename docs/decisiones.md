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

## 2026-10-08 — Conclusiones del análisis 01 (mercado de cierre ARG/BRA)

Detalle en [analisis/01_mercado_cierre.md](analisis/01_mercado_cierre.md). Exploratorio, sobre todo el histórico.

1. **Margen:** Pinnacle ~3,1%, promedio del mercado ~7% (y subiendo en 2025-26). Apostar en casas
   "blandas" exige superar ~7% de margen; el modelo debe compararse siempre contra el mejor precio
   realista, no contra el promedio.
2. **La vara a superar:** log loss del cierre de Pinnacle = 1,034 (ARG) y 0,998 (BRA), apenas
   3,8% / 5,0% mejor que las frecuencias históricas. Argentina es la liga menos predecible
   (más empates, ~30%). Un modelo útil debe acercarse a estos valores fuera de muestra.
3. **Calibración:** el mercado está bien calibrado en general (ECE 0,5-1,8%), pero
   **subestima al local ~1-1,6 pp y sobrestima a la visita ~1,1-1,4 pp** en ambas ligas.
   Apostar a la visita rinde -7,2% a cuota Pinnacle (IC95% [-10,5%; -3,8%]), con signo
   negativo en los 8 bloques liga × período. Apostar ciegamente al local rinde -0,5%:
   **el sesgo existe pero no alcanza para ganar sin modelo.**
4. **Favorito-longshot:** el tramo de cuota 4-6 (mayoría visitas y empates en partidos
   desiguales) rinde -14%. Las cuotas largas (>6) no son concluyentes (IC enormes).
5. **Comparación entre métodos de quitar el margen:** proporcional, power y Shin dan log loss
   prácticamente idéntico (diferencias < 0,0004). Se mantiene el proporcional por simplicidad.

**Hipótesis para la fase de modelado (a validar walk-forward, no asumir):** un modelo que estime
mejor la ventaja local en estas ligas podría encontrar valor en apuestas al local y evitar
visitas sobrevaloradas. Cuidado: este patrón se encontró mirando muchos cortes del mismo
histórico (comparaciones múltiples).
