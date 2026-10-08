# Footbol_ML

Sistema probabilístico de predicción de partidos de fútbol. Estima probabilidades (1X2, goles esperados, Over/Under, BTTS, marcadores) y las compara con las cuotas del mercado para detectar —o descartar— valor esperado positivo.

**No garantiza rentabilidad.** Si la validación temporal muestra que no hay ventaja frente al mercado, el sistema debe demostrarlo y recomendar NO APOSTAR.

## Alcance actual

Foco en Argentina y Brasil (histórico desde 2012 con cuotas de cierre) y recolección diaria hacia adelante de Chile, Argentina y Brasil. Para buscar ligas donde el modelo pueda superar al mercado se evalúan además 36 ligas de football-data.co.uk. Ver [docs/decisiones.md](docs/decisiones.md) para fuentes de datos y limitaciones.

## Principios

- **Sin data leakage:** cada feature se calcula solo con información disponible antes del momento de predicción.
- **Validación temporal (walk-forward)**, nunca divisiones aleatorias.
- **Calibración por sobre accuracy:** log loss, RPS, Brier y curvas de calibración, siempre comparadas contra el mercado.
- **Modelos simples primero:** un modelo complejo solo se adopta si mejora fuera de muestra.

## Estructura

```
config/          settings.yaml (ligas, fuentes, umbrales)
data/            raw / processed / db (no versionados)
docs/            registro de decisiones
src/footy/
  ingest/        descarga de fuentes
  db/            esquema SQLite y acceso
  features/      Elo, rolling stats, contexto
  models/        mercado, Elo, Dixon-Coles, GLM, GBM, ensambles
  markets/       goles esperados → 1X2, O/U, BTTS, marcadores
  evaluation/    métricas, calibración, walk-forward
  betting/       quitar margen, EV, staking, backtest
  monitoring/    registro de predicciones y degradación
scripts/         puntos de entrada (update_data, train, backtest, predict)
tests/
```

## Scripts

| Script | Qué hace |
|---|---|
| `scripts/update_football_data.py [CÓDIGOS]` | Descarga/actualiza resultados, estadísticas y cuotas de cierre de football-data.co.uk |
| `scripts/collect_daily.py` | Recolección diaria desde API-Football: calendario, cuotas pre-partido, detalles (tarea programada) |
| `scripts/backfill_api_football.py CHL 2022 2023 2024` | Calendario de temporadas pasadas desde API-Football |
| `scripts/check_teams.py [--merge A B]` | Detecta y fusiona equipos duplicados entre fuentes |
| `scripts/analyze_market.py` | Análisis 01: margen y calibración del mercado de cierre |
| `scripts/evaluate_models.py` | Análisis 02: Elo y Dixon-Coles vs mercado (walk-forward) en ARG/BRA |
| `scripts/screen_leagues.py` | Análisis 03: el mismo pipeline en todas las ligas, con criterio pre-registrado |
| `scripts/evaluate_shots.py` | Análisis 04: Dixon-Coles entrenado con tiros además de goles |
| `scripts/build_league_models.py` | Consolida los parámetros validados por liga en `config/league_models.json` |
| `scripts/predict.py --league E0 --home X --away Y [--odds L E V]` | Predicción de un partido: 1X2, goles esperados, marcadores, O/U, BTTS, EV y recomendación |
| `scripts/daily.py` | Tarea diaria: recolección, resultados/cuotas de cierre, predicciones de seguimiento e informe [docs/seguimiento.md](docs/seguimiento.md) |

Los análisis generados están en [docs/analisis/](docs/analisis/) y las decisiones en [docs/decisiones.md](docs/decisiones.md).

## Instalación

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
pip install -e .
copy .env.example .env          # y completar API_FOOTBALL_KEY
pytest
```
