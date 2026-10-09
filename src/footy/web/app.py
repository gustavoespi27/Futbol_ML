"""Servidor del dashboard (FastAPI). Arranque: python scripts/serve.py  ->  http://127.0.0.1:8000"""

import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from footy.web import service

STATIC = Path(__file__).with_name("static")
_cache: dict[str, tuple[float, object]] = {}


def _prewarm():
    """Calcula en segundo plano lo más pesado (evaluación 2026, combinadas, próximos partidos)
    para que la primera visita sea rápida."""
    for key, ttl, fn in (("backtest", 3600, service.backtest), ("combo_history", 3600, service.combo_history),
                         ("upcoming7", 300, lambda: service.upcoming(7))):
        try:
            cached(key, ttl, fn)
        except Exception:  # noqa: BLE001 - si falla, se recalcula al pedirlo y ahí se ve el error
            pass


@asynccontextmanager
async def lifespan(_app):
    threading.Thread(target=_prewarm, daemon=True).start()
    yield


app = FastAPI(title="Futbol_ML", docs_url="/api/docs", lifespan=lifespan)


def cached(key: str, ttl: float, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    value = service.to_json(fn())
    _cache[key] = (time.time(), value)
    return value


@app.get("/api/overview")
def overview():
    return cached("overview", 300, service.overview)


@app.get("/api/upcoming")
def upcoming(days: int = 7):
    return cached(f"upcoming{days}", 300, lambda: service.upcoming(days))


@app.get("/api/tracking")
def tracking():
    return cached("tracking", 300, service.tracking_data)


@app.get("/api/backtest")
def backtest():
    return cached("backtest", 3600, service.backtest)


@app.get("/api/leagues")
def leagues():
    return cached("leagues", 3600, service.leagues_list)


@app.get("/api/teams/{code}")
def teams(code: str):
    try:
        return cached(f"teams{code}", 3600, lambda: service.teams(code))
    except KeyError:
        raise HTTPException(404, f"Liga {code} sin modelo")


class PredictIn(BaseModel):
    league: str
    home: str
    away: str
    odds: list[float] | None = Field(default=None, min_length=3, max_length=3)


@app.post("/api/predict")
def predict(body: PredictIn):
    if body.home.strip().lower() == body.away.strip().lower():
        raise HTTPException(422, "Elige dos equipos distintos")
    if body.odds and any(o <= 1 for o in body.odds):
        raise HTTPException(422, "Las cuotas deben ser mayores que 1")
    try:
        return service.to_json(service.predict(body.league, body.home, body.away, body.odds))
    except KeyError as e:
        raise HTTPException(404, e.args[0])


class Leg(BaseModel):
    ref: str
    key: str
    odds: float | None = Field(default=None, gt=1)


class ComboIn(BaseModel):
    legs: list[Leg] = Field(max_length=20)
    group_odds: dict[str, float] = {}


@app.post("/api/combo")
def combo(body: ComboIn):
    try:
        return service.to_json(service.combo([leg.model_dump() for leg in body.legs], body.group_odds))
    except KeyError as e:
        raise HTTPException(404, e.args[0])


@app.get("/api/combos/history")
def combo_history():
    return cached("combo_history", 3600, service.combo_history)


@app.get("/api/suggestions")
def suggestions():
    return cached("suggestions", 300, service.suggestions_data)


@app.post("/api/refresh")
def refresh():
    """Vacía los cachés (después de correr scripts/daily.py)."""
    _cache.clear()
    service.clear_caches()
    threading.Thread(target=_prewarm, daemon=True).start()
    return {"ok": True}


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
