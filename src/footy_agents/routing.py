"""Continuidad e intención deterministas; no calcula pronósticos ni ejecuta herramientas."""

import re

from footy_agents.calendar import calendar_args
from footy_agents.names import normalize_name
from footy_agents.tools import NICKNAMES, service, upcoming_focus


def is_follow_up(message: str, entities: dict | None) -> bool:
    """Solo referencias cortas sin un equipo o liga distintos conservan memoria."""
    q = normalize_name(message).lstrip("¿¡ ")
    if len(message.strip()) >= 80 or not (
        re.match(r"^(?:y|si|dale|ok)\b", q) or any(re.search(r"\b" + phrase + r"\b", q)
                                 for phrase in ("ese partido", "este partido", "el mismo", "ahi", "favorito",
                                                "y manana", "eso", "esa", "ese", "otro", "otra",
                                                "otros", "otras", "mas", "esos", "esas", "estos", "estas",
                                                "el primero", "el segundo", "la primera", "de la lista",
                                                "compara cuotas", "cuanto paga", "que casa paga mas"))
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
        matches = service.upcoming()
        for match in matches:
            id_ = match.get("match_id") or str(match.get("ref", "")).removeprefix("m:")
            if str(id_) in {str(i) for i in entities.get("shown_ids", [])}:
                known.update(normalize_name(str(match[k])) for k in ("home", "away", "league", "league_name")
                             if match.get(k))
        for match in matches:
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
    if entities and entities.get("match_id") and re.search(r"compara cuotas|cuanto paga|que casa paga mas", q):
        return "request_odds", {"match_id": entities["match_id"]}
    for pattern, tool in ((r"deja de vigilar|cancela.*vigilan", "cancel_watch"),
                          (r"que vigilas|mis alertas|lista.*vigilan|mis vigilan", "list_watches"),
                          (r"agrega.*favoritos|anade.*favoritos", "add_favorite"),
                          (r"avisame|vigila|alerta", "create_watch")):
        if re.search(pattern, q):
            args: dict = {}
            if tool == "cancel_watch":
                id_ = re.search(r"\b\d+\b", q)
                if id_:
                    args["id"] = int(id_[0])
            return tool, args
    for pattern, tool in (
        (r"recomendacion|mas fiables?|casi con valor|cerca de tener valor|"
         r"secciones? de apuestas|donde (?:estan|veo|encuentro).*apuestas", "get_recommendations"),
        (r"rendimiento|fiable|fiabilidad|clv|yield|acierto", "get_system_performance"),
        (r"banca|cuanto.*apostar|pesos", "get_stake_limits"),
        (r"por que no hay|cobertura|actualizad", "get_coverage"),
        (r"valor|ventaja", "get_value_bets"),
        (r"como llega|forma|racha", "get_team_form"),
        (r"tabla|posicion", "get_league_standings"),
        (r"simula", "simulate_match"),
        (r"partidos?.*(?:vienen|hay|juega)|calendario|(?:otros?|mas).*partidos?|"
         r"partidos.*(?:importantes?|destacad|grandes?)", "get_upcoming_matches"),
    ):
        if re.search(pattern, q):
            args: dict = {}
            if tool == "get_upcoming_matches":
                args = calendar_args(message, entities)
            if tool == "get_recommendations":
                section = ("casi_valor" if re.search(r"casi|cerca de tener", q) else
                           "fiables" if re.search(r"fiables?", q) else "todas")
                args = {"section": section}
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
    if entities and entities.get("shown_ids") and re.match(r"^(?:si|dale|ok|otros?|otras?|mas)\b", q):
        return "get_upcoming_matches", calendar_args(message, entities)
    if entities and entities.get("match_id"):
        return "analyze_match", {"match_id": entities["match_id"]}
    if "analiza" in q or "pronost" in q or re.search(r"probab.*partido", q):
        return "analyze_match", {}
    return None
