"""Carga de configuración (config/settings.yaml) y secretos (.env)."""

import os
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.yaml"


@lru_cache
def settings() -> dict:
    with open(SETTINGS_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def path(key: str) -> Path:
    """Ruta absoluta de una entrada de `paths` en settings.yaml."""
    return PROJECT_ROOT / settings()["paths"][key]


def api_football_key() -> str:
    load_dotenv(PROJECT_ROOT / ".env")
    key = os.getenv("API_FOOTBALL_KEY", "").strip()
    if not key:
        raise RuntimeError("Falta API_FOOTBALL_KEY en .env (ver .env.example)")
    return key
