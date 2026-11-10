"""Continuidad e intención deterministas; no calcula pronósticos ni ejecuta herramientas."""

import re

from footy_agents.names import normalize_name
from footy_agents.tools import NICKNAMES, service, upcoming_focus


def is_follow_up(message: str, entities: dict | None) -> bool:
    """Solo referencias cortas sin un equipo o liga distintos conservan memoria."""
    q = normalize_name(message).lstrip("¿¡ ")
    if len(message.strip()) >= 80 or not (
        q.startswith("y ") or any(re.search(r"\b" + phrase + r"\b", q)
                                 for phrase in ("ese partido", "este partido", "el mismo", "ahi", "favorito",
                                                "y manana"))
    ):
        return False
    entities = entities or {}
    known = {normalize_name(str(entities[k])) for k in ("home", "away", "team", "league", "league_name")
             if entities.get(k)}
    mentions: set[str] = set()
    for alias, canonical in NICKNAMES.items():
        if f" {alias} " in f" {q} ":
            mentions.add(normalize_name(canonical))
    try:
        focus = upcoming_focus(message)
        if focus:
            mentions.update(normalize_name(str(focus[k])) for k in ("team", "league") if focus.get(k))
        for league in service.league_catalog():
            for key in ("code", "name"):
                if f" {normalize_name(league[key])} " in f" {q} ":
                    if not {normalize_name(league['code']), normalize_name(league['name'])} & known:
                        return False
        for match in service.upcoming():
            for side in ("home", "away"):
                name = normalize_name(match[side])
                if f" {name} " in f" {q} ":
                    mentions.add(name)
    except (KeyError, ValueError, OSError, RuntimeError):
        return False  # si no se puede comprobar la identidad, evitar arrastrar otro tema
    return not (mentions - known)


def intent_route(message: str, entities: dict | None = None) -> tuple[str, dict] | None:
    """Una herramienta por intención original; los argumentos desconocidos no se inventan."""
    q = normalize_name(message)
    for pattern, tool in (
        (r"rendimiento|fiable|fiabilidad|clv|yield|acierto", "get_system_performance"),
        (r"banca|cuanto.*apostar|pesos", "get_stake_limits"),
        (r"por que no hay|cobertura|actualizad", "get_coverage"),
        (r"valor|ventaja", "get_value_bets"),
        (r"como llega|forma|racha", "get_team_form"),
        (r"tabla|posicion", "get_league_standings"),
        (r"simula", "simulate_match"),
        (r"partidos.*(?:vienen|hay)|calendario", "get_upcoming_matches"),
    ):
        if re.search(pattern, q):
            args: dict = {}
            if tool == "get_stake_limits":
                number = re.search(r"\d[\d.,]*", message)
                if number:
                    raw = number[0]
                    raw = re.sub(r"[.,](?=\d{3}(?:\D|$))", "", raw)
                    args = {"bankroll": float(raw.replace(",", "."))}
            elif tool == "get_team_form" and entities and entities.get("team"):
                args = {"team": entities["team"]}
            elif tool == "get_league_standings" and entities and entities.get("league"):
                args = {"league": entities["league"]}
            return tool, args
    if entities and entities.get("match_id"):
        return "analyze_match", {"match_id": entities["match_id"]}
    if "analiza" in q or "pronost" in q:
        return "analyze_match", {}
    return None
