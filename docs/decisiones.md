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

## 2026-10-09 — Revisión de predicciones y modelo v2 (`elo_dc_v2`)

**Seguimiento prospectivo (primeros resultados).** De las 8 predicciones v1 del 08-10, terminaron 3 (BRA):
1 acierto de 3 (Palmeiras 1-0 Bahia); Santos–Flamengo y Athletico–Atlético-MG terminaron 2-2.
Las 2 apuestas en papel (local a 4,50 y visita a 6,00) se perdieron. Muestra demasiado pequeña para concluir.

**Evaluación fuera de muestra 2026** (walk-forward, 8.608 partidos, 38 ligas; parámetros elegidos en 2016-21):

| | Acierto | Log loss |
|---|---:|---:|
| Modelo solo (Elo+DC) | 48,8% | 1,0237 |
| Mercado (cierre sin margen) | 50,6% | 1,0034 |
| Modelo + mercado | 50,7% | 1,0037 |

Las probabilidades combinadas están bien calibradas (dice 60-70% → ocurre 65%; dice ≥70% → ocurre 77%),
pero no mejoran al mercado. Apostar con el modelo solo pierde −15% por unidad (IC95% excluye 0);
las cuotas > 4 son las que más pierden (−16% a −22%).

**Errores corregidos:**
1. Tras renombrar la carpeta, el paquete instalado y la tarea programada apuntaban a `Footbol_ML`: nada corría.
   Reinstalado (`pip install -e .`) y tarea re-registrada.
2. El presupuesto de API-Football se pasaba de la reserva (terminaba en −2 / 3 con reserva 5): el header de
   peticiones restantes llega atrasado. Ahora se toma el mínimo entre header y cuenta local.
3. El informe de seguimiento fallaba si un partido terminado no tenía cuotas de cierre (resultados de
   API-Football llegan antes que el cierre de football-data). Ahora usa el último snapshot pre-partido
   (marcado como tal) y nunca rompe.
4. El seguimiento solo registraba partidos de `fixtures.csv`; ahora también los de API-Football (ARG, BRA)
   con sus cuotas pre-partido (`register_scheduled`).

**Cambios de modelo (v2):**
1. **Pesos del ensamble ≥ 0.** 36 de 38 ligas tenían algún peso negativo (el modelo "invertido"). Restringidos,
   ajustados igual solo con validación: log loss 2026 1,00368 vs 1,00373 y la mitad de varianza frente al
   mercado. Resultado honesto: el peso del modelo queda en ~0 en la mayoría de ligas.
2. **Apuestas en papel solo con cuota ≤ 4,0** (`max_odds`), por el sesgo favorito-longshot del análisis 01;
   el umbral de EV se reelige en validación con esa regla. Advertencia: el tramo de cuotas también se miró en
   2026, así que 2026 ya no es una prueba limpia de esta regla; la prueba limpia es el seguimiento prospectivo.
   En 2026 la regla v2 hace 298 apuestas con −7% (IC95% [−22%; +8%]): tampoco demuestra ventaja.
3. Las predicciones nuevas se guardan como `elo_dc_v2`; las v1 se siguen evaluando por separado.

**Probabilidad oficial del MVP:** modelo + mercado cuando hay cuotas (la más fiable), modelo solo si no hay cuotas,
mercado sin margen en ligas sin modelo validado (Chile). Recomendación por defecto: **no apostar**.

**Dashboard:** `scripts/serve.py` (o `dashboard.bat`) levanta http://127.0.0.1:8000 con inicio, próximos partidos,
resultados del seguimiento, fiabilidad 2026, simulador y explicación para público no técnico.

## 2026-10-09 — v3: reentrenamiento 2016-2025, mercado de goles, combinadas y Serie A / Portugal / Turquía

**Reentrenamiento (`elo_dc_v3`).** Pesos del ensamble (≥ 0), umbral de EV y calibración O/U ajustados con las
predicciones walk-forward de 2016-2025 (antes solo 2016-21); hiperparámetros de Elo/DC sin cambios. 2026 sigue fuera
de todo ajuste. Log loss 1X2 en 2026: 1,00343 (v2: 1,00368; mercado: 1,00342). Con 10 años de datos el ensamble pone
casi todo el peso en el mercado: el modelo propio aporta sobre todo cuando no hay cuotas. La regla de apuestas en
papel v3 en 2026: 168 apuestas, −11% (IC95% [−30%; +8%]).

**Mercado de goles.** Se guardan las cuotas de cierre O/U 2,5 de football-data (antes se descartaban; 457.574 filas
en 22 ligas, `scripts/backfill_ou_odds.py`) y las pre-partido de `fixtures.csv`. En 2026 (5.302 partidos):
Dixon-Coles solo acierta 55,7% (log loss 0,6821); el mercado 57,8% (0,6742); la combinación calibrada 57,5% (0,6743).
Igual que en 1X2: el mercado manda.

**Combinadas.** Todas las selecciones salen de la matriz de marcadores ajustada (IPF) a las probabilidades oficiales
1X2 y O/U 2,5, así que la probabilidad de varias selecciones del mismo partido es exacta (respeta la correlación) y la
de partidos distintos es el producto. Evaluación 2026 a cuota de cierre Bet365 (`footy/evaluation/live.py`):

| Estrategia | 1 | 2 | 3 | 4 piernas |
|---|---:|---:|---:|---:|
| Las más probables: acierto real (esperado) | 55,7% (55,9%) | 32,4% (32,3%) | 19,2% (19,2%) | 11,3% (11,8%) |
| Las más probables: rendimiento | −5,9% | −10,4% | −17,2% | −23,4% |
| Con valor (EV > 0, cuota ≤ 4): rendimiento | −4,6% | +2,0% | +33,3% | +33,1% |
| Con valor: IC95% | [−12; +3] | [−18; +22] | [−16; +83] | [−62; +128] |

- Las probabilidades de combinadas están **bien calibradas** (dice 25% → se cumple 26%; 34% → 34%).
- Combinar las selecciones más probables **pierde siempre y más con cada pierna** (IC excluye 0): el margen se
  multiplica. No es una vía para rentabilizar.
- Las combinadas "con valor" salen positivas, pero con pocos casos e IC que incluyen pérdidas grandes; además se
  calcularon contra el cierre (donde la probabilidad oficial ya incluye el mercado de cierre). **No es una ventaja
  demostrada**: el siguiente paso sería seguirlas en papel de forma prospectiva.

**Serie A, Primeira Liga y Süper Lig en API-Football.** Ya tenían modelo (football-data), pero football-data está
atrasado (último partido cargado: 20-09; su `fixtures.csv` aún lista partidos del 03-10). Se agregan a la recolección
diaria (ids 135, 94, 203) para tener calendario, resultados y cuotas pre-partido. Para enlazar equipos entre fuentes:
emparejamiento tolerante dentro de la misma liga (`repository.fuzzy_team_match`: sin prefijos/sufijos societarios,
"…spor", inclusión de palabras o similitud ≥ 0,85) y alias manuales (Sporting CP, Istanbul Basaksehir, Göztepe…);
la "ı" turca ahora se normaliza. Los 26 equipos vistos se enlazaron sin duplicados. Para no agotar las 100
peticiones/día, las cuotas de un partido no se vuelven a pedir antes de 10 horas. El dashboard marca las ligas con
datos atrasados más de 12 días.

**Aclaración sobre esas ligas:** I1, P1 y T1 (junto con SWE) pasaron el criterio pre-registrado del análisis 03,
pero **no son significativas** tras corregir por 38 comparaciones; en 2026 el ensamble no mejora al mercado en
ninguna. Están en observación, no son "las más fiables para apostar".

## 2026-10-09 — Apuestas sugeridas (regla fija de riesgo/recompensa)

**Regla, fijada antes de mirar resultados** (`footy/betting/suggestions.py`): valor esperado p × cuota − 1 ≥ +3%,
cuota real entre 1,30 y 4,0 (análisis 01: las cuotas largas son las que más pierden), probabilidad ≥ 25%, una
selección por partido. Orden por crecimiento esperado del bankroll (Kelly); monto = ¼ de Kelly con tope de 2,5%.
Riesgo según la probabilidad: bajo ≥ 60%, medio 45-60%, alto < 45%. Dobles: combinaciones de las mejores simples.

**Resultado en 2026** (fuera de muestra, cierre Bet365): 154 apuestas, acierto 36,4% (el sistema esperaba 41,8%),
−5,0% por unidad (IC95% [−26%; +16%]); bankroll 100 → 93,3 con el monto sugerido (peor caída 20%). Dobles: 71,
+7,4% (IC95% [−59%; +74%]). Por riesgo ninguna franja es positiva. **No hay ventaja demostrada** y los umbrales NO
se ajustaron a 2026 para no maquillar el resultado. Las apuestas elegidas por "valor" se aciertan menos de lo
esperado (maldición del ganador: cuando una casa paga más que el consenso, a menudo hay información que el modelo
no ve).

**Medición prospectiva** (reemplazada después por la cartera del apostador profesional, tabla `pro_bets`; el
registro de esta regla quedó como `footy.prediction.experimental_suggestions`, sin uso en producción): la tarea
diaria registraba las sugerencias antes de cada partido (tabla `suggestions`, una
vez por selección) y el dashboard mostraba su resultado real.

## 2026-10-09 — Panel principal con semáforo

El dashboard se reorganiza alrededor de un **panel de apuestas** (pestaña de inicio): apuestas sugeridas arriba,
semáforo de todos los próximos partidos y, al final, la fiabilidad de las probabilidades. La pestaña separada de
sugerencias desaparece; su histórico 2026 pasa a "¿Qué tan fiable es?".

Semáforo por selección (`suggestions.verdict`), coherente con la regla de sugerencias: **verde "Apostar"** si cumple
la regla (valor ≥ +3%, cuota 1,30-4,0, probabilidad ≥ 25%, cuota real); **rojo "No apostar"** si la probabilidad es
< 25%, la cuota > 4,0 o el valor < −5%; **amarillo "Neutral"** en el resto (precio cercano al justo o cuota < 1,30).
Las tarjetas de partido y las tablas de combinadas usan el mismo veredicto, reemplazando la regla antigua de
"apuestas en papel" en la recomendación visible. El verde no implica ventaja demostrada (ver entrada anterior).

## 2026-10-09 — Análisis 05: machine learning sobre el historial de los equipos

Detalle: [analisis/05_ml.md](analisis/05_ml.md). Gradient boosting (scikit-learn) con 88 variables del historial
(`footy/features/history.py`, calculadas solo con partidos anteriores) + liga + Elo/DC walk-forward; 1X2, más de 2,5 y
ambos marcan. Train 2014-07 → 2023, hiperparámetros y mezcla con el mercado en 2024-25, modelo final con 2014-2025,
evaluación única en 2026.

**Error encontrado y corregido antes de usar resultados:** en la primera corrida las cuotas de cierre de Bet365 y
las probabilidades de mercado se colaron como variables al unir tablas (aparecieron como las más importantes): fuga
de información. Ahora las variables salen de una lista blanca por prefijo y un test (`tests/test_ml_features.py`)
verifica que no entren cuotas, mercado ni estadísticas del propio partido. Los números de abajo son los corregidos.

**Resultado 2026:** 1X2 log loss ML 1,0227 (Elo+DC 1,0237; mercado 1,0034); O/U 2,5 ML 0,6797 (DC 0,6821; mercado
0,6742); ambos marcan ML 0,6831 (frecuencia histórica 0,6870). El ML mejora a los modelos anteriores, pero poco; al
combinarlo con el mercado recibe peso 0. Apostar con sus probabilidades: 5.043 apuestas, −10,3% (IC95% [−14%; −7%]).

**Decisión:** el ML reemplaza a Elo + Dixon-Coles como modelo propio (partidos sin cuotas, comparación con el
mercado, "ambos marcan" en la matriz de marcadores). Con cuotas, la probabilidad oficial y las sugerencias no cambian
(siguen ancladas al mercado). El historial público ya está en las cuotas: para buscar ventaja harían falta datos
que el mercado no refleje todavía (alineaciones confirmadas, lesiones, cuotas tempranas para medir CLV).

## 2026-10-09 — El sistema como apostador profesional (análisis 06) y nuevas competiciones

**Cambio de enfoque.** Los modelos propios (Elo, Dixon-Coles, ML) no superan al mercado. Un profesional del value
betting no intenta predecir mejor que el mercado: usa el precio de la casa sharp (Pinnacle) como probabilidad
justa y apuesta en casas blandas cuando pagan más (line shopping), antes de que corrijan. Su indicador es el CLV.

**Evidencia** (`scripts/pro_backtest.py`, cuotas tempranas de football-data, 22 ligas, 109 mil partidos): regla
elegida con 2013-2021 entre 20 combinaciones (umbral 6%, cuota ≤ 4; selección inflada por elegir la mejor). Prueba
2022-2026: 213 apuestas, CLV +5,3% con 77% de apuestas por encima del cierre; rendimiento +2,9% (IC95%
[−17%; +23%]); bankroll ¼ Kelly 100 → 122. Sin Pinnacle (football-data dejó de publicarlo en 2025-26) la
referencia Betfair dio CLV negativo: **sin Pinnacle no se apuesta**. Es la primera señal consistente del proyecto,
pero la ganancia todavía no es significativa y en la práctica las casas limitan a los ganadores.

**Implementación.** `footy/betting/pro.py` (precio justo, mejor cuota, regla, Kelly con topes de 2% por apuesta y
10% diario); cartera en papel `pro_bets` (`footy/prediction/pro_ledger.py`), registrada por la tarea diaria antes
del partido y liquidada con CLV contra Pinnacle; el Panel del dashboard pasa a ser el del apostador profesional; el
semáforo de 1X2 usa esta regla (verde solo con Pinnacle; el valor según el modelo queda en amarillo).

**Competiciones nuevas en API-Football:** Premier League, LaLiga, Bundesliga, Ligue 1 (ya tenían historial de
football-data; alias de nombres agregados), Champions/Europa/Conference League y selecciones (Mundial, eliminatorias
CONMEBOL/UEFA/CONCACAF, Nations League, Copa América, Eurocopa, amistosos; equipos con país "World"). Con 100
peticiones diarias las cuotas se piden por prioridad (`odds_priority`) y una vez cada 10 horas por partido. El
historial de selecciones accesible en el plan gratuito (2022-2024) se carga de a 3 temporadas por día. El ML no
muestra pronósticos para competiciones que no vio al entrenar (selecciones y copas internacionales).

## 2026-10-09 — Modelos de producción y factibilidad de apostar con dinero real

**Producción.** Evaluado el ML en 2026, se reentrena con todos los partidos hasta hoy (173 mil) con los mismos
hiperparámetros y número de árboles (`train_ml.py --production`). Los modelos de evaluación quedan en
`artifacts/ml/models_eval.joblib`; `--eval` se niega a evaluar modelos de producción (ya vieron 2026). La regla del
apostador profesional NO se reajusta con los datos de prueba: queda fija y la mide la cartera en vivo.
Tarea programada: se agrega una ejecución a las 21:15 (la cuota de API-Football se renueva a las 00:00 UTC).

**¿Conviene apostar con dinero real?** Monte Carlo con las apuestas de la prueba (cuota media 3,2, monto medio 1,1%
del bankroll, ~60-90 apuestas al año):

| Ventaja supuesta | Horizonte | Bankroll mediano (inicio 100) | P(perder) | P(perder > 20%) |
|---|---|---:|---:|---:|
| +3% (CLV +5% menos cuota que se mueve) | 1 año | 101,5 | 46% | 6% |
| +3% | 3 años | 105,7 | 42% | 15% |
| 0% (sin ventaja) | 3 años | 96,3 | 56% | 24% |

Aun si la ventaja es real, con este volumen el resultado de uno o tres años es casi una moneda al aire y la ganancia
esperada es pequeña (~+2% anual del bankroll). Recomendación: no apostar dinero real todavía. Primero 2-3 meses de
cartera en papel (≥ 150 apuestas con CLV medio > +2% y > 60% de apuestas sobre el cierre); si se cumple, montos
pequeños que se puedan perder, verificando la cuota mínima antes de cada apuesta y deteniéndose si el CLV real de
100 apuestas es ≤ 0. Riesgos fuera del modelo: límites de cuenta de las casas, cuotas que se mueven, legalidad e
impuestos.

## 2026-10-09 — La máquina se pone a prueba cada día: pronósticos fiables y ajuste automático

**Pronósticos fiables** (`footy/prediction/reliable.py`, tabla `daily_picks`): cada día, en cada partido de las
próximas 36 horas, se registra antes del inicio la selección más probable con probabilidad ≥ 65% entre 1X2,
más/menos 2,5 y ambos marcan (máximo 20 por día), con su motivo (probabilidad, mercado, forma, goles esperados,
cuota). La doble oportunidad se excluyó: acierta casi siempre y no mide nada. Al terminar se liquida y se compara el
acierto real con el esperado, por mercado y por nivel de confianza. No es recomendación de apuesta: pagan poco.

**Ajuste automático** (`footy/prediction/recalibration.py`): temperatura T sobre las probabilidades oficiales 1X2,
ajustada por log loss con las predicciones registradas antes de cada partido. T se encoge hacia 1 según la cantidad
de datos (T_ef = 1 + (T − 1)·n/(n + 300)) y se limita a [0,8; 1,25] para que corrija de a poco y no sobreajuste al
ruido. Se recalcula en la tarea diaria y se guarda su historial. Hoy: 8 partidos liquidados → sin ajuste.

**Corrección:** la cuota estimada de la doble oportunidad (desde el 1X2 de la misma casa) podía quedar ≤ 1 en
partidos muy desiguales; ahora no se muestra si no supera 1,01.

**Dashboard:** el Panel deja de mostrar un "bankroll" sin uso; el monto base queda como ajuste dentro de las
recomendaciones. Recomendador con pestañas (con valor / más fiables / casi con valor) y bitácora (apuestas y
pronósticos registrados con su motivo y resultado), precisión en vivo y estado del ajuste. Filtro por fecha en
Partidos, Semáforo y Combinadas, y en el boleto cada selección es una fila propia aunque sea del mismo partido.

**Corrección de carga (mismo día).** Al abrir el dashboard, cada endpoint recalculaba en paralelo los próximos
partidos y reajustaba los modelos de ~40 ligas (~40 s); mientras tanto el Panel quedaba en blanco y parecía roto.
Ahora: los próximos partidos se calculan una sola vez y las consultas simultáneas esperan ese resultado; los
predictores por liga se guardan en `data/cache/predictors/` y solo se reajustan cuando hay partidos terminados nuevos
(carga en frío de ~40 s a ~4 s); el Panel dibuja cada sección por separado con avisos de carga; los archivos JS/CSS
llevan versión para que el navegador no use copias viejas. El dashboard muestra solo hoy, mañana y pasado mañana
(hora de Chile) y el filtro de fecha queda en Todos / Hoy / Mañana / pasado mañana (sin selector de día).
