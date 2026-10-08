"""Qué competiciones usa cada liga para entrenar, y parámetros validados por liga."""

import json

from footy import config
from footy.ingest.football_data import leagues

PARAMS_PATH = config.PROJECT_ROOT / "config" / "league_models.json"


def family(code: str) -> tuple[list[str], list[str]]:
    """(competiciones para Elo, competiciones para Dixon-Coles).

    Elo usa todas las divisiones del país (los ascendidos llegan con historial);
    Dixon-Coles solo la liga evaluada (y la copa argentina, entre los mismos equipos).
    """
    cfg = leagues()
    if code == "ARG":
        return ["ARG", "ARGC"], ["ARG", "ARGC"]
    if code in cfg["main"]:
        country = cfg["main"][code]["country"]
        return [c for c, v in cfg["main"].items() if v["country"] == country], [code]
    return [code], [code]


def league_name(code: str) -> str:
    cfg = leagues()
    return (cfg["extra"].get(code) or cfg["main"][code])["name"]


def load_params() -> dict:
    """Parámetros por liga elegidos en validación (generados por scripts/build_league_models.py)."""
    return json.loads(PARAMS_PATH.read_text(encoding="utf-8"))
