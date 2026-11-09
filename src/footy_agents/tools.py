"""Herramientas (tools) tipadas para el agente y orquestador LLM.

Envuelven los servicios existentes en footy.web.service sin modificarlos ni romperlos.
Cada herramienta devuelve un payload condensado y seguro para el contexto del LLM.
"""

import time
from difflib import get_close_matches
from math import floor
from typing import Any

from pydantic import ValidationError

from footy.betting import pro
from footy.web import service
from footy_agents.names import normalize_name
from footy_agents.schemas import ToolCallRecord
from footy_agents.tool_args import OPENAI_TOOLS_SPEC, TOOL_MODELS  # noqa: F401 - fachada p?blica

MAX_MATCHES = 20


def resolve_league(league: str) -> str:
    """Resuelve códigos y nombres del catálogo; los alias no agregan ligas inexistentes."""
    catalog = service.league_catalog()
    names = {normalize_name(str(row[key])): row["code"] for row in catalog for key in ("code", "name")}
    aliases = {"chilean primera division": "CHL", "primera division chilena": "CHL", "liga chilena": "CHL",
               "laliga": "SP1", "la liga espanola": "SP1", "english premier league": "E0"}
    codes = {r["code"] for r in catalog}
    names.update({alias: code for alias, code in aliases.items() if code in codes})
    query = normalize_name(league)
    if query in names:
        return names[query]
    close = list(dict.fromkeys(names[n] for n in get_close_matches(query, list(names), n=5, cutoff=.25)))[:3]
    raise ValueError(f"Liga no reconocida: {league}. Códigos cercanos: {', '.join(close or sorted(codes)[:3])}")


def upcoming_focus(message: str) -> dict[str, Any] | None:
    """Precarga solo cuando la consulta nombra un equipo o liga del calendario disponible."""
    query = normalize_name(message)
    matches = service.upcoming()
    teams = list(dict.fromkeys(m[k] for m in matches for k in ("home", "away")))
    for name in teams:
        normalized = normalize_name(name)
        short = " ".join(w for w in normalized.split() if w not in {"fc", "cf", "afc", "sc", "club"})
        if normalized and (f" {normalized} " in f" {query} " or (len(short) >= 4 and f" {short} " in f" {query} ")):
            return {"team": name, "limit": MAX_MATCHES}
    for league in service.league_catalog():
        if (normalize_name(league["code"]) in query.split() or normalize_name(league["name"]) in query) \
                and any(m["league"] == league["code"] for m in matches):
            return {"league": league["code"], "limit": MAX_MATCHES}
    return None


def _pct(p: float | None) -> str | None:
    return None if p is None else f"{p * 100:.1f}%"


def tool_get_upcoming_matches(limit: int = 10, league: str | None = None,
                              team: str | None = None) -> list[dict[str, Any]]:
    """Próximos partidos con liga, fecha, probabilidades 1X2 del sistema y si tienen cuotas."""
    matches = service.upcoming()
    if league:
        code = resolve_league(league)
        matches = [m for m in matches if m.get("league") == code]
    if team:
        q = normalize_name(team)
        matches = [m for m in matches
                   if q in normalize_name(m.get("home", "")) or q in normalize_name(m.get("away", ""))]

    def probs(m: dict) -> dict[str, str | None] | None:
        p = m.get("p_official")
        return {"home_win": _pct(p[0]), "draw": _pct(p[1]), "away_win": _pct(p[2])} if p else None

    return [{
        "match_id": int(m["ref"][2:]) if m.get("ref", "").startswith("m:") else None,
        "league": m.get("league"),
        "league_name": m.get("league_name"),
        "kickoff": m.get("kickoff"),
        "home": m.get("home"),
        "away": m.get("away"),
        "probabilities_1x2": probs(m),
        "probability_source": m.get("source"),
        "has_pinnacle_price": bool(m.get("pro")),
        "value_status": "sin_precio_pinnacle" if not m.get("pro") else
                        "con_ventaja" if any(o.get("bet") for o in m["pro"]) else "sin_ventaja",
        "recommendation": "Sin referencia Pinnacle; no evaluar ventaja" if not m.get("pro") else
                          "Selección con ventaja frente a Pinnacle" if any(o.get("bet") for o in m["pro"])
                          else "Ninguna selección cumple la regla de ventaja",
    } for m in matches[:max(1, min(limit, MAX_MATCHES))]]


def tool_get_value_bets(min_edge: float = pro.MIN_EDGE) -> list[dict[str, Any]]:
    """Apuestas del apostador profesional: ventaja frente al precio justo de Pinnacle (el motor ya exige
    pro.MIN_EDGE; `min_edge` solo puede endurecer ese umbral)."""
    singles = service.current_suggestions(service.upcoming()).get("singles", [])
    return [{
        "match": s["match"],
        "home": s.get("home"),
        "away": s.get("away"),
        "league": s.get("league"),
        "market": s.get("label"),
        "bookmaker": s.get("book"),
        "odds": s.get("odds"),
        "fair_odds": round(s["fair_odds"], 2),
        "edge": round(s["edge"], 4),
        "stake": s.get("stake"),
        "reason": s.get("reason"),
    } for s in singles if s["edge"] >= max(min_edge, pro.MIN_EDGE)]


def tool_simulate_match(league: str, home_team: str, away_team: str) -> dict[str, Any]:
    """Simula un partido entre dos equipos de una liga con el modelo del sistema (xG y probabilidades 1X2)."""
    res = service.predict(resolve_league(league), home_team, away_team, None)
    p_home, p_draw, p_away = res["p_model"]
    return {
        "home": res["home"],
        "away": res["away"],
        "league": res["league"],
        "expected_goals": {"home": res["xg"][0], "away": res["xg"][1]},
        "probabilities_1x2": {"home_win": p_home, "draw": p_draw, "away_win": p_away},
        "top_scores": res.get("top_scores", [])[:3],
    }


def tool_get_league_standings(league: str) -> dict[str, Any]:
    """Obtiene la tabla de posiciones y la racha reciente de una liga."""
    league = resolve_league(league)
    st = service.standings(league)
    if not st:
        return {"error": f"No hay tabla disponible para la liga {league}"}
    return {
        "league": league,
        "league_name": st.get("league_name"),
        "season": st.get("season"),
        "top_standings": [{
            "position": row["pos"],
            "team": row["name"],
            "played": row["played"],
            "points": row["points"],
            "gd": row["gd"],
            "recent": row["recent"],
        } for row in st["rows"][:8]],
    }


def tool_get_system_performance() -> dict[str, Any]:
    """Rendimiento real del sistema: seguimiento en vivo (aciertos, log loss, apuestas en papel) y motor vigente."""
    ov = service.overview()
    tracking = dict(ov.get("tracking") or {})
    for key in ("hit_rate", "bets_yield", "bets_clv"):     # fracciones -> porcentaje listo para citar
        if tracking.get(key) is not None:
            tracking[key] = _pct(tracking[key])
    return {
        "model_version": ov.get("model_version"),
        "tracking": tracking,
        "engine": ov.get("engine"),
        "last_daily_run": ov.get("last_daily_run"),
    }


# Mapeo de herramientas para ejecución dinámica
def tool_get_stake_limits(bankroll: float) -> dict[str, Any]:
    """Topes enteros CLP redondeados hacia abajo: no equivale a recomendar ese monto."""
    single, daily = floor(bankroll * pro.MAX_STAKE), floor(bankroll * pro.MAX_DAILY)
    clp = lambda value: "$" + f"{value:,}".replace(",", ".")  # noqa: E731
    return {"bankroll": bankroll, "bankroll_clp": clp(floor(bankroll)), "max_per_bet": single, "max_daily": daily,
            "max_per_bet_clp": clp(single), "max_daily_clp": clp(daily),
            "kelly_fraction": pro.KELLY_FRACTION, "max_stake_fraction": pro.MAX_STAKE,
            "max_daily_fraction": pro.MAX_DAILY,
            "note": "Son topes de exposición, no una apuesta sugerida. El monto depende del precio justo de Pinnacle."}


TOOLS_REGISTRY: dict[str, Any] = {
    "get_upcoming_matches": tool_get_upcoming_matches,
    "get_value_bets": tool_get_value_bets,
    "simulate_match": tool_simulate_match,
    "get_league_standings": tool_get_league_standings,
    "get_system_performance": tool_get_system_performance,
    "get_stake_limits": tool_get_stake_limits,
}


def execute_tool(name: str, arguments: dict[str, Any]) -> ToolCallRecord:
    """Ejecuta una herramienta registrada de forma segura y mide el tiempo de respuesta."""
    start_time = time.perf_counter()
    func = TOOLS_REGISTRY.get(name)

    if not func:
        elapsed = (time.perf_counter() - start_time) * 1000
        return ToolCallRecord(
            tool_name=name,
            arguments=arguments,
            result=None,
            success=False,
            execution_time_ms=round(elapsed, 2),
            error_message=f"Herramienta '{name}' no registrada."
        )

    try:
        validated = TOOL_MODELS[name].model_validate(arguments)
        res = func(**validated.model_dump())
        elapsed = (time.perf_counter() - start_time) * 1000
        return ToolCallRecord(
            tool_name=name,
            arguments=arguments,
            result=res,
            success=True,
            execution_time_ms=round(elapsed, 2)
        )
    except ValidationError as exc:
        return ToolCallRecord(tool_name=name, arguments=arguments, result=None, success=False,
                              execution_time_ms=round((time.perf_counter() - start_time) * 1000, 2),
                              error_message=f"Argumentos inválidos: {exc}")
    except Exception as exc:  # noqa: BLE001 - una herramienta que falla no debe tumbar al agente
        elapsed = (time.perf_counter() - start_time) * 1000
        return ToolCallRecord(
            tool_name=name,
            arguments=arguments,
            result=None,
            success=False,
            execution_time_ms=round(elapsed, 2),
            error_message=str(exc)
        )

