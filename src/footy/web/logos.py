"""Logos de equipos y ligas (imágenes públicas de API-Football, no consumen cuota), con caché local.

Cada logo se descarga una sola vez a data/cache/logos/ y después se sirve desde disco. Si no existe se guarda una
marca `.missing` para no volver a pedirlo; el navegador muestra entonces las iniciales del equipo.
"""

from functools import lru_cache
from pathlib import Path

import requests
import yaml

from footy import config
from footy.db.connection import connect

CDN = "https://media.api-sports.io/football"
CACHE = config.PROJECT_ROOT / "data" / "cache" / "logos"


@lru_cache
def _league_ids() -> dict[str, int]:
    ids = {code: c["api_football_id"] for code, c in config.settings()["competitions"].items()
           if "api_football_id" in c}
    path = config.PROJECT_ROOT / "config" / "logos.yaml"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            ids.update((yaml.safe_load(f) or {}).get("leagues", {}))
    return ids


def league_api_id(code: str) -> int | None:
    return _league_ids().get(code)


def team_api_id(team_id: int) -> int | None:
    rows = connect().execute(
        "SELECT alias FROM team_aliases WHERE source = 'api_football' AND team_id = ?", (team_id,)).fetchall()
    ids = [int(r[0]) for r in rows if str(r[0]).isdigit()]
    return min(ids) if ids else None


def get(kind: str, api_id: int) -> Path | None:
    """Ruta local del logo (descargándolo si hace falta) o None si no existe."""
    folder = {"team": "teams", "league": "leagues"}[kind]
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{kind}_{api_id}.png"
    missing = path.with_suffix(".missing")
    if path.exists():
        return path
    if missing.exists():
        return None
    try:
        r = requests.get(f"{CDN}/{folder}/{api_id}.png", timeout=10, headers={"User-Agent": "Futbol_ML"})
    except requests.RequestException:
        return None                                  # sin red: se reintenta en la próxima visita
    if r.status_code == 200 and r.headers.get("content-type", "").startswith("image") and len(r.content) > 200:
        path.write_bytes(r.content)
        return path
    missing.touch()
    return None
