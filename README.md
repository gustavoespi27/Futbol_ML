# Footbol_ML

Sistema probabilístico de predicción de partidos de fútbol. Estima probabilidades (1X2, goles esperados, Over/Under, BTTS, marcadores) y las compara con las cuotas del mercado para detectar —o descartar— valor esperado positivo.

**No garantiza rentabilidad.** Si la validación temporal muestra que no hay ventaja frente al mercado, el sistema debe demostrarlo y recomendar NO APOSTAR.

## Alcance actual

Primera División de Chile, Liga Profesional Argentina y Brasileirão. Ver [docs/decisiones.md](docs/decisiones.md) para fuentes de datos y limitaciones.

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

## Instalación

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
pip install -e .
copy .env.example .env          # y completar API_FOOTBALL_KEY
pytest
```
