"""Servidor del dashboard (FastAPI). Arranque: python scripts/serve.py  ->  http://127.0.0.1:8000"""

import re
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from footy.web import logos, schemas, service

STATIC = Path(__file__).with_name("static")
_cache: dict[str, tuple[float, object]] = {}
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _prewarm():
    """Calcula en segundo plano lo más pesado (evaluación 2026, combinadas, próximos partidos)
    para que la primera visita sea rápida."""
    for key, ttl, fn in (("upcoming", 300, service.upcoming), ("suggestions", 300, service.suggestions_data),
                         ("reliable", 300, service.reliable_data), ("league_catalog", 300, service.league_catalog),
                         ("backtest", 3600, service.backtest), ("combo_history", 3600, service.combo_history),
                         ("ml", 3600, service.ml_report)):
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
    """Resultado cacheado; si otra consulta ya lo está calculando, espera ese cálculo en vez de repetirlo."""
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    with _locks_guard:
        lock = _locks.setdefault(key, threading.Lock())
    with lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        value = service.to_json(fn())
        _cache[key] = (time.time(), value)
        return value


# response_model_exclude_unset: los campos opcionales que el backend no envía siguen sin aparecer (contrato idéntico).
TYPED = {"response_model_exclude_unset": True}


@app.get("/api/overview", response_model=schemas.Overview, **TYPED)
def overview():
    return cached("overview", 300, service.overview)


@app.get("/api/upcoming", response_model=list[schemas.MatchSummary], **TYPED)
def upcoming():
    return cached("upcoming", 300, service.upcoming)


@app.get("/api/tracking", response_model=schemas.TrackingOverview, **TYPED)
def tracking():
    return cached("tracking", 300, service.tracking_data)


@app.get("/api/backtest")
def backtest():
    return cached("backtest", 3600, service.backtest)


@app.get("/api/leagues")
def leagues():
    return cached("leagues", 3600, service.leagues_list)


@app.get("/api/league-catalog", response_model=list[schemas.LeagueCatalogItem], **TYPED)
def league_catalog():
    return cached("league_catalog", 300, service.league_catalog)


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


@app.get("/api/ml")
def ml_report():
    return cached("ml", 3600, service.ml_report)


@app.get("/api/reliable")
def reliable():
    return cached("reliable", 300, service.reliable_data)


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


@app.get("/logo/{kind}/{key}")
def logo(kind: str, key: str):
    """Logo de un equipo (/logo/team/<team_id>) o liga (/logo/league/<código>), con caché local."""
    if kind == "team" and key.isdigit():
        api_id = logos.team_api_id(int(key))
    elif kind == "league":
        api_id = logos.league_api_id(key)
    else:
        raise HTTPException(404)
    path = logos.get(kind, api_id) if api_id else None
    if path is None:
        raise HTTPException(404)
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "public, max-age=604800"})


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    """index.html con la versión de cada archivo estático (?v=fecha de modificación): el navegador siempre
    carga el JS/CSS actual después de una actualización, sin quedarse con una copia vieja en caché."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    html = re.sub(r'/static/([\w.-]+\.(?:js|css))"',
                  lambda m: f'/static/{m.group(1)}?v={int((STATIC / m.group(1)).stat().st_mtime)}"', html)
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})
