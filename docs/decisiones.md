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

## 2026-10-08 — Análisis 02: Elo y Dixon-Coles no superan al mercado en ARG/BRA

Walk-forward semanal; hiperparámetros, pesos y umbral elegidos en validación 2016-21, test 2022-25.
Los modelos quedan 0,010-0,025 de log loss por detrás del cierre de Pinnacle. El ensamble con el
mercado asigna peso ~0 a los modelos (no aportan información nueva). Apostar con el modelo solo
pierde (BRA -13% a cuota Pinnacle, IC95% excluye 0); con ¼ Kelly el bankroll cae >75%.
Detalle: [analisis/02_modelos.md](analisis/02_modelos.md).

## 2026-10-08 — Pre-registro: criterio para elegir ligas (antes de ver resultados)

Se evalúan ~38 ligas de football-data.co.uk con el mismo pipeline. Con tantas ligas, alguna
"ganará" por azar, así que el criterio se fija ANTES de mirar resultados:

1. **Candidata (solo con datos de VALIDACIÓN 2016-21):** el ensamble Elo+DC+Mercado mejora el
   log loss del mercado en validación (Δ < -0,001) **y** la estrategia de ese ensamble tiene yield > 0
   a cuota Pinnacle en validación.
2. **Confirmada (TEST 2022-25, mirado una sola vez):** en test se mantiene Δ log loss < 0 **y**
   yield > 0 a cuota Pinnacle. Un IC95% individual no basta con ~38 comparaciones: se reporta
   también el IC con corrección de Bonferroni (99,9%).
3. Si ninguna liga cumple 1 y 2, la conclusión es que **con estos modelos y datos no hay ventaja
   demostrable** en ninguna liga, y el siguiente paso es mejorar el modelo (xG, tiros, alineaciones),
   no buscar más ligas.

## 2026-10-08 — Resultado del análisis 03 (38 ligas)

Detalle: [analisis/03_ligas.md](analisis/03_ligas.md).

- El modelo solo (Elo+DC) **no supera al mercado en ninguna de las 38 ligas** (Δ log loss test > 0 en todas).
- Criterio pre-registrado: 15 candidatas en validación, 4 "confirmadas" en test (SWE, I1, P1, T1).
- **Lectura honesta: 4 de 15 es lo que se espera por azar.** Bajo la hipótesis de que no hay ventaja,
  cada candidata pasa el test con probabilidad ~25% (Δ<0 ≈ 50% × yield>0 ≈ 45-50%), es decir
  ~3,7 esperadas. Ninguna es significativa con corrección de Bonferroni. El criterio pre-registrado
  resultó demasiado laxo: debió exigir significancia, no solo signo.
- La más interesante es **T1 (Süper Lig)**: 852 apuestas en test, yield +6,6% (IC95% [+0,4%; +12,8%]),
  y el ensamble mejora el log loss del mercado en 0,005. Aun así no supera Bonferroni.
- Las ligas "menores" (ascenso inglés, escocés, Segunda, Serie B) no muestran más ventaja que las grandes:
  la hipótesis "ligas menos líquidas = mercado peor" no se sostiene con este modelo.

**Decisión:** no hay ventaja demostrada en ninguna liga. T1, I1, P1 y SWE pasan a **seguimiento
prospectivo** (predicciones registradas antes de cada partido, sin dinero real) como prueba
independiente. El trabajo principal vuelve a mejorar el modelo (tiros, xG, contexto), porque un
modelo 0,01-0,05 de log loss peor que el mercado no puede encontrar valor de forma fiable.

## 2026-10-08 — Análisis 04: Dixon-Coles con tiros

Detalle: [analisis/04_tiros.md](analisis/04_tiros.md). 22 ligas europeas, 30.033 partidos de test.

- Entrenar con una mezcla de goles y goles esperados por tiros (proporción elegida en validación)
  **mejora el log loss de forma significativa**: −0,81 milésimas (IC95% [−1,37; −0,25]); mejora en 17/22 ligas.
- La mejora es ~20-40 veces menor que la distancia al mercado (11-31 milésimas): el modelo sigue sin
  superar al cierre en ninguna liga, y el ensamble con el mercado no cambia (+0,09, IC incluye 0).
- Se adopta la variante con tiros en los parámetros por liga (`config/league_models.json`).

**Implicancia:** con estadísticas agregadas por partido no alcanza. Para acercarse al mercado harían falta
datos que el mercado usa y el modelo no: alineaciones y bajas (pre-partido), xG de calidad, y cuotas
tempranas para medir CLV. Mientras tanto, el seguimiento prospectivo (`docs/seguimiento.md`) registra
predicciones antes de cada partido en todas las ligas y mide CLV contra el cierre.
