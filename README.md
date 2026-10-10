# Futbol ML

[![CI](https://github.com/gustavoespi27/Futbol_ML/actions/workflows/ci.yml/badge.svg)](https://github.com/gustavoespi27/Futbol_ML/actions/workflows/ci.yml)

**Sistema probabilístico de predicción de fútbol y value betting, con dashboard web local.**

Futbol ML estima la probabilidad de cada resultado de un partido (1X2, doble oportunidad, más/menos goles, ambos
marcan, marcadores exactos y combinadas), la compara con las cuotas de las casas de apuestas y **mide públicamente si
esas probabilidades se cumplen**. Sobre esa base opera un *apostador profesional* automatizado que solo recomienda
apostar cuando una casa paga más que el precio justo del mercado más eficiente (Pinnacle).

> **Aviso.** Proyecto de análisis con fines educativos; no es consejo de apuestas ni garantiza rentabilidad. La
> ganancia en dinero aún no es estadísticamente concluyente, las casas limitan a quienes ganan y la mayoría de los
> días no hay apuestas con valor. Los modelos propios entregan probabilidades bien calibradas, pero no superan al
> mercado por sí solos.

---

## Contenido

- [Resultados clave](#resultados-clave)
- [Inicio rápido](#inicio-rápido)
- [Dashboard](#dashboard)
- [Aprendizaje diario](#aprendizaje-diario)
- [El apostador profesional](#el-apostador-profesional)
- [Modelo de probabilidades](#modelo-de-probabilidades)
- [Evaluación fuera de muestra](#evaluación-fuera-de-muestra)
- [Datos](#datos)
- [Principios metodológicos](#principios-metodológicos)
- [Arquitectura](#arquitectura)
- [Scripts](#scripts)
- [Documentación](#documentación)

---

## Resultados clave

| Indicador | Valor |
|---|---|
| Acierto del resultado más probable (1X2, 2026, 8.608 partidos, 38 ligas) | 50,6 % — igual al mercado de cierre |
| Calibración | Cuando el sistema da 60-70 %, ocurre el 65 %; cuando da ≥ 70 %, el 77 % |
| Combinadas | El porcentaje anunciado se cumple (25 % → 26 % acertadas) |
| Apostador profesional, prueba 2022-2026 | 77 % de las apuestas superó la cuota de cierre (CLV medio +5,3 %) |
| Rendimiento en dinero, prueba 2022-2026 | +2,9 % por unidad, IC95 % [−17 %; +23 %]: **no concluyente** |

---

## Inicio rápido

**Requisitos:** Python ≥ 3.11 y una clave gratuita de [API-Football](https://www.api-football.com/).

```bash
python -m venv .venv
.venv\Scripts\activate              # Windows
pip install -r requirements.txt
pip install -e .
copy .env.example .env              # completar API_FOOTBALL_KEY
```

**Primera carga de datos y modelos** (una sola vez):

```bash
python scripts/update_football_data.py          # resultados, estadísticas y cuotas desde 2012
python scripts/screen_leagues.py                # análisis 03 (ligas con modelo validado)
python scripts/evaluate_shots.py                # análisis 04
python scripts/build_league_models.py           # pesos y calibración por liga
python scripts/train_ml.py                      # entrena y evalúa el ML (~15 min)
python scripts/train_ml.py --production         # reentrena con todos los datos para predecir
```

**Uso diario:**

```bash
python scripts/serve.py                         # dashboard en http://127.0.0.1:8000 (o doble clic en dashboard.bat)
powershell scripts/register_task.ps1            # programa la tarea diaria (10:00, 17:30 y 21:15)
```

**Calidad:**

```bash
pytest
ruff check src scripts tests
```

La clave de API vive solo en `.env` (no versionado). Los modelos de ML se guardan en `artifacts/ml/` y conviene
reentrenarlos cada temporada.

---

## Dashboard

Interfaz en español, con tema claro/oscuro y diseño adaptable a móvil: paleta cobalto (navegación) y esmeralda
(valor positivo), Plus Jakarta Sans en títulos y JetBrains Mono en cuotas y métricas, barras con efecto vidrio,
esqueletos de carga y gráficos con estilo de terminal financiera. Muestra los partidos de **hoy, mañana y pasado
mañana** (hora de Chile).

| Sección | Contenido |
|---|---|
| **Panel** | Indicadores del día; recomendador con pestañas *Con valor*, *Más fiables* y *Casi con valor*, cada una con su motivo; semáforo de todos los próximos partidos (local, empate, visita, más/menos 2,5, ambos marcan) con la mejor opción; bitácora de apuestas y pronósticos registrados con su resultado; precisión en vivo; historial del ajuste automático y respaldo histórico 2012-2026 |
| **Partidos** | Probabilidades 1X2, cuotas (Bet365/Pinnacle), cuota justa, ganancia por 1.000 apostados, goles esperados, modelo vs mercado y aviso de datos atrasados |
| **Combinadas** | Constructor de combinadas con todas las opciones de cada partido (probabilidad, cuota, cuota justa y valor), variantes más probables de un mismo partido, boleto con probabilidad conjunta, cuota combinada y calculadora de la apuesta; histórico 2026 de combinadas |
| **Resultados** | Predicciones registradas antes de cada partido vs resultado real, y apuestas en papel con CLV |
| **Fiabilidad** | Evaluación 2026 en 38 ligas: calibración, simulación de apuestas, tabla por liga, modelos de ML e historial de la regla de apuestas |
| **Simulador** | Cualquier partido de una liga con modelo; con cuotas y monto opcionales calcula retorno, ganancia neta, pérdida y ganancia esperada; sus opciones se pueden agregar a la combinada |
| **Cómo funciona** | Explicación sin tecnicismos y glosario |

**Navegación y filtros**

- **Buscador de equipos y ligas** en Partidos, Semáforo y Combinadas: sugerencias mientras se escribe (sin importar
  tildes ni mayúsculas), sección *Equipos* con escudo y liga, filtros por continente y país, selección de todas las
  ligas de un país o continente y navegación con teclado.
- **Filtro por día:** Todos, Hoy, Mañana y pasado mañana, con la cantidad de partidos de cada uno.
- **Combinadas:** los partidos del boleto aparecen primero, resaltados con la etiqueta *En tu combinada*; el botón
  *↑ Tus partidos* vuelve a ellos desde cualquier punto de la lista. Cada selección del boleto es una fila propia,
  también si pertenece al mismo partido.
- **Listas largas** (semáforo, recomendaciones, bitácora, partidos, tablas de resultados) se desplazan dentro de su
  tarjeta con encabezado fijo, sin zonas desplazables anidadas.
- **Lectura rápida:** la barra 1X2 marca dónde estaba el mercado sin margen; las selecciones con valor frente a
  Pinnacle se destacan con borde esmeralda e insignia *VALOR +X%*.
- **Boleto:** tipo automático (simple, mismo partido o combinada), aviso de si la correlación entre selecciones
  del mismo partido favorece o penaliza, montos rápidos y ganancia potencial destacada.
- **Escudos y logos** de API-Football (imágenes públicas, no consumen cuota) servidos por `/logo/team/<id>` y
  `/logo/league/<código>` con caché local; si falta un logo se muestran las iniciales.

**Rendimiento.** Los cálculos pesados se hacen una sola vez y se comparten entre consultas simultáneas; los modelos
por liga se guardan en `data/cache/predictors/` y solo se reajustan cuando hay partidos terminados nuevos, por lo que
el dashboard abre en segundos. Los archivos estáticos se versionan automáticamente para que el navegador siempre cargue
la última versión. La API JSON está documentada en http://127.0.0.1:8000/api/docs.

---

## Aprendizaje diario

La tarea `scripts/daily.py` (programada a las 10:00, 17:30 y 21:15) ejecuta los siguientes pasos; si uno falla, los
demás continúan:

| Paso | Qué hace |
|---|---|
| `api_football` | Calendario, resultados y cuotas pre-partido de ~10 casas, según prioridad por competición |
| `football_data` | Resultados, estadísticas y cuotas de cierre de la temporada en curso |
| `recalibrate` | **Ajuste automático:** con los resultados de las predicciones registradas ajusta una temperatura *T* que corrige si el sistema es demasiado seguro (*T* > 1 suaviza) o tímido (*T* < 1); con pocos datos se encoge hacia 1 y se limita a [0,8; 1,25] |
| `ml` | Predicciones del modelo de machine learning para los próximos partidos |
| `tracking`, `tracking_api` | Registro de predicciones antes de cada partido para su evaluación posterior |
| `suggestions` | Cartera del apostador profesional: registra cada apuesta con su motivo, la liquida y mide su CLV |
| `reliable` | **Pronósticos fiables:** registra antes del inicio la selección más probable de cada partido (≥ 65 %; 1X2, más/menos 2,5, ambos marcan) y al terminar mide acierto real vs esperado |
| `report` | Informe local `docs/seguimiento.md` (no versionado) y refresco del dashboard si está abierto |

---

## El apostador profesional

Implementado en `footy/betting/pro.py`:

1. **Precio justo:** cuotas 1X2 de Pinnacle sin margen. Sin Pinnacle no apuesta (en el histórico, otras referencias
   no dieron CLV positivo).
2. **Line shopping:** mejor cuota entre las casas disponibles (Bet365, Betano, 1xBet, William Hill, Marathonbet,
   BetVictor, entre otras). No cuentan Pinnacle, exchanges ni agregadores.
3. **Regla:** apostar si `mejor cuota × probabilidad justa − 1 ≥ 6 %` y cuota ≤ 4,0; una apuesta por partido, la de
   mayor crecimiento esperado.
4. **Monto:** ¼ de Kelly, con máximo 2 % del bankroll por apuesta y 10 % por día.
5. **Control:** cada apuesta se registra antes del partido (tabla `pro_bets`) y se mide su CLV contra Pinnacle al cierre.

Regla elegida con 2013-2021 y probada en 2022-2026 sobre cuotas tempranas de 22 ligas europeas
([análisis 06](docs/analisis/06_profesional.md)):

| Período | Apuestas | CLV medio | Superan al cierre | Rendimiento [IC95 %] | Bankroll (inicio 100) |
|---|---:|---:|---:|---|---:|
| Selección 2013-2021 | 419 | +6,8 % | 76 % | +30,0 % [+15 %; +45 %] | 354 |
| Prueba 2022-2026 | 213 | +5,3 % | 77 % | +2,9 % [−17 %; +23 %] | 122 |

El semáforo aplica la misma regla en 1X2 (verde = apostar). En otros mercados, o sin Pinnacle, el máximo es amarillo,
porque el valor según el modelo propio no está validado.

---

## Modelo de probabilidades

1. **Modelo propio:** gradient boosting con pérdida Poisson que predice los goles esperados del local (λ) y de la
   visita (μ) a partir de 88 variables del historial de los equipos (forma, goles, tiros, localía, temporada,
   rachas, descanso, enfrentamientos directos, contexto de liga) más las predicciones de Elo y Dixon-Coles. 1X2,
   más/menos y ambos marcan salen de la misma matriz de marcadores, así que son coherentes entre sí. Entrenado con
   140 mil partidos (2014-2025). Elo + Dixon-Coles quedan como respaldo.
2. **Probabilidad oficial:** combinación log-lineal con el mercado sin margen, con pesos ≥ 0 ajustados en 2016-2025.
   Sin cuotas se usa el modelo; en ligas sin modelo validado, el mercado.
3. **Más/menos 2,5 goles:** Dixon-Coles calibrado y combinado con las cuotas O/U cuando existen.
4. **Resto de mercados** (doble oportunidad, otras líneas, ambos marcan, variantes de un partido): se derivan de una
   matriz de marcadores ajustada a las probabilidades oficiales, lo que garantiza coherencia entre mercados.
5. **Combinadas:** probabilidad conjunta exacta dentro de un mismo partido (respeta la correlación) y producto entre
   partidos distintos.
6. **Recalibración:** la temperatura del ajuste diario se aplica a las probabilidades publicadas.

---

## Evaluación fuera de muestra

Temporada 2026, no vista durante el ajuste: 8.608 partidos de 1X2 en 38 ligas y 5.302 con cuotas O/U en 22 ligas.

| Mercado y fuente | Acierto | Log loss |
|---|---:|---:|
| 1X2 – probabilidad oficial | 50,6 % | 1,0034 |
| 1X2 – mercado (cierre sin margen) | 50,6 % | 1,0034 |
| 1X2 – ML historial de equipos | 49,1 % | 1,0207 |
| 1X2 – Elo + Dixon-Coles | 48,8 % | 1,0237 |
| Más/menos 2,5 – oficial | 57,5 % | 0,6743 |
| Más/menos 2,5 – mercado | 57,8 % | 0,6742 |
| Más/menos 2,5 – ML | 56,9 % | 0,6790 |
| Más/menos 2,5 – Dixon-Coles | 55,7 % | 0,6821 |
| Ambos marcan – ML (frecuencia histórica: 0,6870) | 56,0 % | 0,6830 |

**Lectura.** El ML mejora a Elo + Dixon-Coles en las tres tareas, pero no alcanza al mercado: combinado con él recibe
peso 0 y apostar solo con sus probabilidades pierde (−13,3 % en 4.606 apuestas; [análisis 05](docs/analisis/05_ml.md)).
Las apuestas elegidas por valor según el modelo en 2026 acertaron 36,4 % cuando se esperaba 41,8 % (−5,0 % por
unidad en 154 apuestas): **no hay ventaja demostrada fuera del precio de Pinnacle**, por eso toda sugerencia se
registra antes del partido y se mide en el dashboard.

**Combinadas.** Combinar las selecciones más probables pierde más con cada pierna (−6 % simple, −10 % doble, −17 %
triple, −23 % cuádruple, todas significativas). Las combinadas "con valor" salen positivas en 2026, pero sin
significancia estadística ([decisiones](docs/decisiones.md)).

---

## Datos

| Fuente | Cobertura |
|---|---|
| [football-data.co.uk](https://www.football-data.co.uk/) | 38 ligas desde 2012: resultados, tiros y cuotas de cierre (1X2; O/U 2,5 en 22 ligas europeas). Puede atrasarse varias semanas |
| [API-Football](https://www.api-football.com/) (plan gratuito, 100 peticiones/día) | Calendario, resultados y cuotas pre-partido (1X2, O/U, ambos marcan) de ~10 casas incluida Pinnacle: Premier League, LaLiga, Bundesliga, Serie A, Ligue 1, Primeira Liga, Süper Lig, Argentina, Brasil, Chile, competiciones UEFA y selecciones (Mundial, eliminatorias, Nations League, Copa América, Eurocopa, amistosos) |

Las cuotas se solicitan por prioridad (`odds_priority`) para respetar el presupuesto diario; el historial de
selecciones se carga gradualmente (`api_football.backfill`). Los equipos de ambas fuentes se enlazan por nombre, con
alias en `config/team_aliases.yaml` y emparejamiento tolerante dentro de cada liga.

---

## Principios metodológicos

- **Sin data leakage:** cada predicción usa solo información disponible antes del partido.
- **Validación temporal (walk-forward)**, nunca divisiones aleatorias; 2026 se reserva como examen.
- **Calibración por sobre acierto:** log loss y curvas de calibración, siempre comparadas con el mercado.
- **Seguimiento prospectivo:** toda predicción y apuesta se registra antes del partido y se evalúa después.
- **Honestidad estadística:** los resultados se reportan con intervalos de confianza y se distingue entre lo
  validado y lo que aún no lo está.

---

## Arquitectura

```
config/            settings.yaml (competiciones, API), football_data.yaml, league_models.json, team_aliases.yaml
data/              raw / processed / db / cache (no versionado)
artifacts/ml/      modelos de machine learning entrenados (no versionado)
docs/              decisiones, análisis 01-06 y seguimiento prospectivo
src/footy/
  ingest/          football-data.co.uk y API-Football
  db/              esquema SQLite y enlace de equipos y partidos entre fuentes
  features/        variables del historial de los equipos (history.py)
  models/          Elo + logit ordinal, Dixon-Coles, ensamble log-lineal, machine learning (ml.py)
  markets/         matriz de marcadores → 1X2, O/U, ambos marcan; selecciones y combinadas
  evaluation/      métricas, walk-forward, evaluación 2026 (live.py)
  betting/         margen, EV, backtest, apostador profesional (pro.py), semáforo (suggestions.py)
  prediction/      predictor por liga, ML, seguimiento, cartera (pro_ledger.py),
                   pronósticos fiables (reliable.py), recalibración (recalibration.py)
  web/             FastAPI (app.py), fachada de datos (service.py) y frontend estático (HTML/CSS/JS, Chart.js)
    services/      catalog, context, betting, combos, evaluation, simulator: un submódulo por responsabilidad
scripts/           puntos de entrada
tests/             pruebas unitarias (pytest)
```

**Stack:** Python 3.11+, pandas, NumPy, SciPy, scikit-learn, SQLite, FastAPI, Uvicorn; frontend en JavaScript sin
frameworks con Chart.js.

---

## Scripts

| Script | Descripción |
|---|---|
| `scripts/serve.py` | Dashboard web local en http://127.0.0.1:8000 (también `dashboard.bat`) |
| `scripts/daily.py` | Tarea diaria completa (ver [Aprendizaje diario](#aprendizaje-diario)) |
| `scripts/register_task.ps1` | Registra la tarea diaria en el Programador de tareas de Windows (10:00, 17:30 y 21:15) |
| `scripts/update_football_data.py [CÓDIGOS]` | Descarga o actualiza datos de football-data.co.uk |
| `scripts/collect_daily.py` | Solo la recolección de API-Football |
| `scripts/backfill_api_football.py CHL 2022 2023 2024` | Calendario de temporadas pasadas desde API-Football |
| `scripts/backfill_ou_odds.py` | Agrega cuotas de cierre O/U 2,5 desde los CSV ya descargados |
| `scripts/reprocess_api_fixtures.py` | Reprocesa fixtures desde las respuestas crudas guardadas (sin gastar peticiones) |
| `scripts/check_teams.py [--merge A B]` | Detecta y fusiona equipos duplicados entre fuentes |
| `scripts/build_league_models.py` | Ajusta pesos, umbrales y calibración O/U por liga (2016-2025) |
| `scripts/train_ml.py [--eval \| --production]` | Entrena y evalúa los modelos de ML; `--production` reentrena con todos los datos |
| `scripts/predict.py --league E0 --home X --away Y [--odds L E V]` | Predicción de un partido por consola |
| `scripts/analyze_market.py` | Análisis 01: margen y calibración del mercado de cierre |
| `scripts/evaluate_models.py` | Análisis 02: Elo y Dixon-Coles vs mercado |
| `scripts/screen_leagues.py` | Análisis 03: el mismo pipeline en 38 ligas, con criterio pre-registrado |
| `scripts/evaluate_shots.py` | Análisis 04: Dixon-Coles con tiros además de goles |
| `scripts/pro_backtest.py` | Análisis 06: el apostador profesional en el histórico |

---

## Documentación

| Documento | Tema |
|---|---|
| [01 – Mercado de cierre](docs/analisis/01_mercado_cierre.md) | Margen y calibración de las casas |
| [02 – Modelos](docs/analisis/02_modelos.md) | Elo y Dixon-Coles frente al mercado |
| [03 – Ligas](docs/analisis/03_ligas.md) | Validación en 38 ligas |
| [04 – Tiros](docs/analisis/04_tiros.md) | Aporte de los tiros al modelo |
| [05 – Machine learning](docs/analisis/05_ml.md) | Modelo sobre el historial de los equipos |
| [06 – Apostador profesional](docs/analisis/06_profesional.md) | Value betting contra Pinnacle y CLV |
| [Decisiones](docs/decisiones.md) | Registro de decisiones de diseño y sus motivos |
