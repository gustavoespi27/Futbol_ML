"""Herramientas (tools) tipadas para el agente y orquestador LLM.

Envuelven los servicios existentes en footy.web.service sin modificarlos ni romperlos.
Cada herramienta devuelve un payload condensado y seguro para el contexto del LLM.
"""

import time
from typing import Any

from pydantic import ValidationError

from footy.betting import pro
from footy.web import service
from footy_agents.names import normalize_name
from footy_agents.schemas import ToolCallRecord
from footy_agents.tool_args import OPENAI_TOOLS_SPEC, TOOL_MODELS  # noqa: F401 - fachada p?blica

MAX_MATCHES = 20


def _pct(p: float | None) -> str | None:
    return None if p is None else f"{p * 100:.1f}%"


def tool_get_upcoming_matches(limit: int = 10, league: str | None = None,
                              team: str | None = None) -> list[dict[str, Any]]:
    """Próximos partidos con liga, fecha, probabilidades 1X2 del sistema y si tienen cuotas."""
    matches = service.upcoming()
    if league:
        matches = [m for m in matches if m.get("league") == league]
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
        "has_odds": bool(m.get("pro")),
        "recommendation": (m.get("recommendation") or {}).get("text"),
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
    } for s in singles if s["edge"] >= min_edge]


def tool_simulate_match(league: str, home_team: str, away_team: str) -> dict[str, Any]:
    """Simula un partido entre dos equipos de una liga con el modelo del sistema (xG y probabilidades 1X2)."""
    res = service.predict(league, home_team, away_team, None)
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
TOOLS_REGISTRY: dict[str, Any] = {
    "get_upcoming_matches": tool_get_upcoming_matches,
    "get_value_bets": tool_get_value_bets,
    "simulate_match": tool_simulate_match,
    "get_league_standings": tool_get_league_standings,
    "get_system_performance": tool_get_system_performance,
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

