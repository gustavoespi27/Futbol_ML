# Futbol_ML

Sistema probabilístico de predicción de partidos de fútbol con dashboard web local. Estima la probabilidad de cada
resultado (1X2, doble oportunidad, más/menos goles, ambos marcan, marcadores y combinadas), la compara con las cuotas
de las casas de apuestas y mide públicamente si esas probabilidades se cumplen.

El sistema funciona como un **apostador profesional de value betting**: toma el precio justo de Pinnacle (la casa
más eficiente), compara todas las casas disponibles y apuesta solo cuando alguna paga ≥ 6% más de lo que vale el
resultado, con monto de ¼ de Kelly, y mide su ventaja con el CLV. En el histórico (2022-2026, fuera de la selección)
el 77% de sus apuestas consiguió mejor cuota que el cierre (CLV medio +5,3%).

**No garantiza rentabilidad.** La ganancia en dinero aún no es estadísticamente concluyente, las casas limitan a
quienes ganan y la mayoría de los días no hay apuestas con valor. Los modelos propios (Elo, Dixon-Coles, ML) dan
probabilidades bien calibradas pero no superan al mercado por sí solos.

## Dashboard

Doble clic en `dashboard.bat`, o:

```bash
python scripts/serve.py          # abre http://127.0.0.1:8000
```

| Sección | Qué muestra |
|---|---|
| Panel (inicio) | Pantalla principal del **apostador profesional**: su cartera en vivo (bankroll simulado, CLV real, apuestas abiertas y liquidadas), las apuestas de hoy con monto según tu bankroll, su historial 2012-2026, **semáforo** de todos los próximos partidos (local, empate, visita, más/menos 2,5, ambos marcan) con la mejor opción de cada uno, las más cercanas a tener valor, las de alta probabilidad, el historial real de sugerencias y la fiabilidad de las probabilidades |
| Próximos partidos | Probabilidades 1X2, cuotas de la casa (Bet365/Pinnacle), cuota justa, ganancia por 1.000 apostados, goles esperados, modelo vs mercado y aviso si los datos de la liga están atrasados |
| Combinadas | Constructor de combinadas: opciones de cada partido con probabilidad, cuota de la casa, cuota justa y valor; variantes más probables del mismo partido; boleto para agregar y quitar selecciones con la probabilidad de acertarlo, cuota combinada y ganancia. Incluye el histórico 2026 de combinadas |
| Resultados | Predicciones registradas antes de cada partido vs resultado real, y apuestas en papel con CLV |
| ¿Qué tan fiable es? | Evaluación 2026 en 38 ligas (1X2 y más/menos de 2,5 goles): calibración, simulación de apuestas, tabla por liga e histórico de la regla de apuestas sugeridas (bankroll, por nivel de riesgo) |
| Simulador | Cualquier partido de una liga con modelo, con cuotas opcionales; sus opciones se pueden agregar a la combinada |
| Cómo funciona | Explicación sin tecnicismos y glosario |

La API JSON está documentada en http://127.0.0.1:8000/api/docs. La tarea diaria refresca el dashboard si está abierto.

### El apostador profesional (`footy/betting/pro.py`)

1. **Precio justo:** cuotas 1X2 de Pinnacle sin margen. Sin Pinnacle no apuesta (en el histórico, otras referencias
   no dieron CLV positivo).
2. **Line shopping:** la mejor cuota entre todas las casas disponibles (API-Football trae ~10: Bet365, Betano, 1xBet,
   William Hill, Marathonbet, BetVictor…). No cuentan Pinnacle, exchanges ni agregados.
3. **Regla:** apostar si mejor cuota × probabilidad justa − 1 ≥ 6% y cuota ≤ 4,0; una apuesta por partido (la de
   mayor crecimiento esperado).
4. **Monto:** ¼ de Kelly, máximo 2% del bankroll por apuesta y 10% por día.
5. **Cartera:** la tarea diaria registra cada apuesta antes del partido (tabla `pro_bets`), la liquida y mide su CLV
   contra Pinnacle al cierre.

Regla elegida con 2013-2021 y probada en 2022-2026 sobre las cuotas tempranas de 22 ligas europeas
([docs/analisis/06_profesional.md](docs/analisis/06_profesional.md)):

| Período | Apuestas | CLV medio | Le ganan al cierre | Rendimiento [IC95%] | Bankroll (inicio 100) |
|---|---:|---:|---:|---|---:|
| Selección 2013-2021 | 419 | +6,8% | 76% | +30,0% [+15%; +45%] | 354 |
| Prueba 2022-2026 | 213 | +5,3% | 77% | +2,9% [−17%; +23%] | 122 |

El semáforo usa la misma regla en 1X2 (verde = apostar). En otros mercados, o sin Pinnacle, el máximo es amarillo:
el valor según el modelo propio no está validado.

### Cómo se calculan las probabilidades

1. **Modelo propio:** machine learning (gradient boosting) con 88 variables del historial de los equipos —forma,
   goles, tiros, localía, temporada, rachas, descanso, enfrentamientos directos, contexto de liga— más las
   predicciones de Elo y Dixon-Coles. Entrenado con 140 mil partidos (2014-2025). Se usa cuando no hay cuotas, para
   comparar modelo vs mercado y para "ambos marcan". Elo + Dixon-Coles quedan como respaldo.
2. **Probabilidad oficial:** combinación con el mercado sin margen, con pesos ≥ 0 ajustados con 2016-2025.
   Sin cuotas se usa el modelo solo; en ligas sin modelo validado (Chile), el mercado.
3. **Más/menos de 2,5 goles:** Dixon-Coles calibrado y combinado con las cuotas O/U cuando existen.
4. **Todo lo demás** (doble oportunidad, otras líneas de goles, ambos marcan, variantes de un mismo partido) sale
   de la matriz de marcadores ajustada a esas probabilidades oficiales, así que es coherente entre mercados.
5. **Combinadas:** dentro de un mismo partido la probabilidad es conjunta (exacta, respeta la correlación);
   entre partidos se multiplica.

### Qué tan fiable es (temporada 2026, fuera de muestra)

| | Acierto | Log loss |
|---|---:|---:|
| 1X2 – probabilidad oficial | 50,6% | 1,0034 |
| 1X2 – mercado (cierre sin margen) | 50,6% | 1,0034 |
| 1X2 – modelo solo | 48,8% | 1,0237 |
| Más/menos de 2,5 – oficial | 57,5% | 0,6743 |
| Más/menos de 2,5 – mercado | 57,8% | 0,6742 |
| Más/menos de 2,5 – Dixon-Coles | 55,7% | 0,6821 |
| 1X2 – ML historial de equipos | 49,2% | 1,0227 |
| Más/menos de 2,5 – ML | 56,3% | 0,6797 |
| Ambos marcan – ML (frecuencia histórica: 0,6870) | 55,7% | 0,6831 |

8.608 partidos de 1X2 en 38 ligas y 5.302 con cuotas O/U en 22 ligas. El ML mejora a Elo + Dixon-Coles en las
tres tareas, pero no alcanza al mercado: combinado con él recibe peso 0, y apostar con sus probabilidades pierde
(−10,3% en 5.043 apuestas). Detalle en [docs/analisis/05_ml.md](docs/analisis/05_ml.md). Cuando el sistema da 60-70% al resultado más
probable, ocurre el 65%; cuando da 70% o más, el 77%.

Apuestas sugeridas: la regla aplicada a 2026 hizo 154 apuestas con −5,0% por unidad (IC95% −26% a +16%); con el
monto sugerido el bankroll pasó de 100 a 93,3 (peor caída 20%). Las elegidas por tener valor se acertaron 36,4% cuando
el sistema esperaba 41,8%: **no hay ventaja demostrada**, por eso cada sugerencia se registra antes del partido y se
mide en el dashboard.

Combinadas: el porcentaje que muestra el sistema se cumple (dice 25% → se acertó 26%). Combinar las selecciones
más probables pierde más con cada pierna (−6% simple, −10% doble, −17% triple, −23% cuádruple, todas significativas);
las combinadas "con valor" salen positivas en 2026 pero sin significancia estadística. Detalle en
[docs/decisiones.md](docs/decisiones.md).

## Datos

- **football-data.co.uk:** 38 ligas desde 2012 con resultados, tiros y cuotas de cierre (1X2; O/U 2,5 en las 22
  ligas europeas). Se atrasa a veces varias semanas.
- **API-Football (plan gratuito, 100 peticiones/día):** calendario, resultados y cuotas pre-partido (1X2, O/U, ambos
  marcan) de ~10 casas, incluida Pinnacle: Premier League, LaLiga, Bundesliga, Serie A, Ligue 1, Primeira Liga,
  Süper Lig, Argentina, Brasil, Chile, Champions/Europa/Conference League y selecciones (Mundial, eliminatorias,
  Nations League, Copa América, Eurocopa, amistosos). Las cuotas se piden por prioridad (`odds_priority`) porque el
  presupuesto no alcanza para todo; el historial de selecciones 2022-2024 se carga de a poco
  (`api_football.backfill`). Los equipos se enlazan con los de
  football-data por nombre (con alias en `config/team_aliases.yaml` y emparejamiento tolerante dentro de la liga).

## Principios

- **Sin data leakage:** cada predicción usa solo información disponible antes del partido.
- **Validación temporal (walk-forward)**, nunca divisiones aleatorias; 2026 se reserva como examen.
- **Calibración por sobre acierto:** log loss y curvas de calibración, siempre contra el mercado.
- **Seguimiento prospectivo:** cada predicción se guarda antes del partido (`predictions`) y se evalúa después.

## Estructura

```
config/          settings.yaml (competiciones, API), football_data.yaml (ligas), league_models.json (parámetros
                 por liga), team_aliases.yaml
data/            raw / processed / db (no versionados)
docs/            decisiones, análisis 01-04 y seguimiento prospectivo
src/footy/
  ingest/        football-data.co.uk y API-Football
  db/            esquema SQLite, enlace de equipos y partidos entre fuentes
  features/      variables del historial de los equipos para el ML (history.py)
  models/        Elo + logit ordinal, Dixon-Coles, ensamble log-lineal, machine learning (ml.py)
  markets/       matriz de marcadores → 1X2, O/U, ambos marcan; selecciones y combinadas
  evaluation/    métricas, walk-forward, evaluación 2026 (live.py)
  betting/       quitar margen, EV, backtest, apostador profesional (pro.py), semáforo (suggestions.py)
  prediction/    predictor por liga, predicciones ML, seguimiento prospectivo, cartera del profesional (pro_ledger.py)
  web/           dashboard (FastAPI + HTML/JS estático con Chart.js)
scripts/         puntos de entrada (ver tabla)
tests/
```

## Scripts

| Script | Qué hace |
|---|---|
| `scripts/serve.py` | Dashboard web local en http://127.0.0.1:8000 (también `dashboard.bat`) |
| `scripts/daily.py` | Tarea diaria: API-Football, football-data, predicciones ML, predicciones de seguimiento, apuestas del apostador profesional, informe [docs/seguimiento.md](docs/seguimiento.md) y refresco del dashboard |
| `scripts/register_task.ps1` | Registra la tarea diaria en el Programador de tareas de Windows (10:00 y 17:30) |
| `scripts/update_football_data.py [CÓDIGOS]` | Descarga/actualiza resultados, estadísticas y cuotas de cierre de football-data.co.uk |
| `scripts/collect_daily.py` | Solo la recolección de API-Football |
| `scripts/backfill_api_football.py CHL 2022 2023 2024` | Calendario de temporadas pasadas desde API-Football |
| `scripts/backfill_ou_odds.py` | Agrega cuotas de cierre O/U 2,5 desde los CSV crudos ya descargados |
| `scripts/reprocess_api_fixtures.py` | Vuelve a guardar fixtures desde las respuestas crudas de API-Football (sin gastar peticiones) |
| `scripts/check_teams.py [--merge A B]` | Detecta y fusiona equipos duplicados entre fuentes |
| `scripts/analyze_market.py` | Análisis 01: margen y calibración del mercado de cierre |
| `scripts/evaluate_models.py` | Análisis 02: Elo y Dixon-Coles vs mercado (walk-forward) en ARG/BRA |
| `scripts/screen_leagues.py` | Análisis 03: el mismo pipeline en 38 ligas, con criterio pre-registrado |
| `scripts/evaluate_shots.py` | Análisis 04: Dixon-Coles entrenado con tiros además de goles |
| `scripts/pro_backtest.py` | Análisis 06: el apostador profesional en el histórico (cuotas tempranas vs Pinnacle, CLV) |
| `scripts/train_ml.py [--eval \| --production]` | Análisis 05: entrena los modelos de ML (1X2, más/menos 2,5, ambos marcan) y los evalúa en 2026 (`artifacts/ml/`, ~15 min); `--production` los reentrena con todos los datos hasta hoy para predecir |
| `scripts/build_league_models.py` | Ajusta pesos, umbrales y calibración O/U por liga (2016-2025) en `config/league_models.json` |
| `scripts/predict.py --league E0 --home X --away Y [--odds L E V]` | Predicción de un partido en consola |

Los análisis están en [docs/analisis/](docs/analisis/) y las decisiones en [docs/decisiones.md](docs/decisiones.md).

## Instalación

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
pip install -e .
copy .env.example .env          # y completar API_FOOTBALL_KEY
pytest
ruff check src scripts tests
```

La primera vez hay que poblar la base (`scripts/update_football_data.py`, luego los análisis 03-04,
`scripts/build_league_models.py`, `scripts/train_ml.py` y `scripts/train_ml.py --production`); después basta la
tarea diaria (`scripts/register_task.ps1`: 10:00, 17:30 y 21:15, justo después de que se renueva la cuota de la API). Los modelos de ML se
guardan en `artifacts/ml/` (no versionado) y conviene reentrenarlos cada temporada.
