# Futbol_ML

Sistema probabilístico de predicción de partidos de fútbol con dashboard web local. Estima la probabilidad de cada
resultado (1X2, doble oportunidad, más/menos goles, ambos marcan, marcadores y combinadas), la compara con las cuotas
de las casas de apuestas y mide públicamente si esas probabilidades se cumplen.

**No garantiza rentabilidad.** La evaluación fuera de muestra muestra que el sistema iguala al mercado pero no lo
supera; por eso la recomendación por defecto es **no apostar**. Su valor está en dar probabilidades honestas y bien
calibradas.

## Dashboard

Doble clic en `dashboard.bat`, o:

```bash
python scripts/serve.py          # abre http://127.0.0.1:8000
```

| Sección | Qué muestra |
|---|---|
| Panel (inicio) | Pantalla principal: apuestas sugeridas con monto según tu bankroll, **semáforo** de todos los próximos partidos (local, empate, visita, más/menos 2,5, ambos marcan) con la mejor opción de cada uno, las más cercanas a tener valor, las de alta probabilidad, el historial real de sugerencias y la fiabilidad de las probabilidades |
| Próximos partidos | Probabilidades 1X2, cuotas de la casa (Bet365/Pinnacle), cuota justa, ganancia por 1.000 apostados, goles esperados, modelo vs mercado y aviso si los datos de la liga están atrasados |
| Combinadas | Constructor de combinadas: opciones de cada partido con probabilidad, cuota de la casa, cuota justa y valor; variantes más probables del mismo partido; boleto para agregar y quitar selecciones con la probabilidad de acertarlo, cuota combinada y ganancia. Incluye el histórico 2026 de combinadas |
| Resultados | Predicciones registradas antes de cada partido vs resultado real, y apuestas en papel con CLV |
| ¿Qué tan fiable es? | Evaluación 2026 en 38 ligas (1X2 y más/menos de 2,5 goles): calibración, simulación de apuestas, tabla por liga e histórico de la regla de apuestas sugeridas (bankroll, por nivel de riesgo) |
| Simulador | Cualquier partido de una liga con modelo, con cuotas opcionales; sus opciones se pueden agregar a la combinada |
| Cómo funciona | Explicación sin tecnicismos y glosario |

La API JSON está documentada en http://127.0.0.1:8000/api/docs. La tarea diaria refresca el dashboard si está abierto.

### Semáforo y apuestas sugeridas

Cada opción con cuota de la casa recibe un color (`footy/betting/suggestions.py`, `verdict`):

| Color | Etiqueta | Cuándo |
|---|---|---|
| Verde | **Apostar** | Paga al menos +3% sobre lo que vale (probabilidad × cuota − 1 ≥ 3%), cuota real entre 1,30 y 4,0 y probabilidad ≥ 25% |
| Amarillo | **Neutral** | Precio cercano al justo (entre −5% y +3%) o muy probable pero con cuota menor a 1,30 |
| Rojo | **No apostar** | Probabilidad < 25%, cuota > 4,0 o paga más de 5% menos de lo que vale |
| Gris | Sin cuota | Aún no hay cuota de la casa (solo se puede descartar por probabilidad baja) |

Las verdes son las apuestas sugeridas: una por partido, ordenadas por crecimiento esperado del bankroll (Kelly), con
monto de ¼ de Kelly y tope de 2,5% del bankroll. Las dobles sugeridas combinan las mejores simples.

### Cómo se calculan las probabilidades

1. **Modelo:** Elo + Dixon-Coles (goles y tiros) por liga, con hiperparámetros elegidos en validación 2016-2021.
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
| Más/menos de 2,5 – modelo solo | 55,7% | 0,6821 |

8.608 partidos de 1X2 en 38 ligas y 5.302 con cuotas O/U en 22 ligas. Cuando el sistema da 60-70% al resultado más
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
  marcan) de Chile, Argentina, Brasil, Serie A, Primeira Liga y Süper Lig. Los equipos se enlazan con los de
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
  models/        Elo + logit ordinal, Dixon-Coles, ensamble log-lineal
  markets/       matriz de marcadores → 1X2, O/U, ambos marcan; selecciones y combinadas
  evaluation/    métricas, walk-forward, evaluación 2026 (live.py)
  betting/       quitar margen, EV, backtest, apuestas sugeridas (suggestions.py)
  prediction/    predictor por liga, seguimiento prospectivo y registro de sugerencias
  web/           dashboard (FastAPI + HTML/JS estático con Chart.js)
scripts/         puntos de entrada (ver tabla)
tests/
```

## Scripts

| Script | Qué hace |
|---|---|
| `scripts/serve.py` | Dashboard web local en http://127.0.0.1:8000 (también `dashboard.bat`) |
| `scripts/daily.py` | Tarea diaria: API-Football, football-data, predicciones de seguimiento, registro de apuestas sugeridas, informe [docs/seguimiento.md](docs/seguimiento.md) y refresco del dashboard |
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

La primera vez hay que poblar la base (`scripts/update_football_data.py`, luego los análisis 03-04 y
`scripts/build_league_models.py`); después basta la tarea diaria.
