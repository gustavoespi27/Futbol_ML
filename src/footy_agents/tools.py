"""Herramientas (tools) tipadas para el agente y orquestador LLM.

Envuelven los servicios existentes en footy.web.service sin modificarlos ni romperlos.
Cada herramienta devuelve un payload condensado y seguro para el contexto del LLM.
"""

import time
from typing import Any

from footy.betting import pro
from footy.web import service
from footy_agents.schemas import ToolCallRecord

MAX_MATCHES = 20


def tool_get_upcoming_matches(limit: int = 10, league: str | None = None) -> list[dict[str, Any]]:
    """Obtiene los próximos partidos programados con su liga, fecha y si tienen cuotas."""
    matches = service.upcoming()
    if league:
        matches = [m for m in matches if m.get("league") == league]
    return [{
        "match_id": int(m["ref"][2:]) if m.get("ref", "").startswith("m:") else None,
        "league": m.get("league"),
        "league_name": m.get("league_name"),
        "kickoff": m.get("kickoff"),
        "home": m.get("home"),
        "away": m.get("away"),
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
    return {
        "model_version": ov.get("model_version"),
        "tracking": ov.get("tracking"),
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

# Esquema para compatibilidad con OpenAI / Ollama tool-calling
OPENAI_TOOLS_SPEC = [
    {
        "type": "function",
        "function": {
            "name": "get_upcoming_matches",
            "description": "Obtiene la lista de próximos partidos con sus cuotas y horarios.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Cantidad máxima de partidos a retornar (máximo 20)"},
                    "league": {"type": "string", "description": "Código opcional de la liga (ej: 'CHL', 'ARG', 'PL')"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_value_bets",
            "description": "Obtiene apuestas con ventaja frente al precio justo (sin margen) de Pinnacle.",
            "parameters": {
                "type": "object",
                "properties": {
                    "min_edge": {
                        "type": "number",
                        "description": "Ventaja mínima porcentual sobre Pinnacle (ej: 0.06 para 6%)"
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "simulate_match",
            "description": "Simula un partido con el modelo matemático Dixon-Coles y retorna xG y probabilidades 1X2.",
            "parameters": {
                "type": "object",
                "properties": {
                    "league": {"type": "string", "description": "Código de la liga (ej: 'CHL', 'ARG')"},
                    "home_team": {"type": "string", "description": "Nombre del equipo local"},
                    "away_team": {"type": "string", "description": "Nombre del equipo visitante"}
                },
                "required": ["league", "home_team", "away_team"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_league_standings",
            "description": "Consulta la tabla de posiciones y racha reciente de una liga.",
            "parameters": {
                "type": "object",
                "properties": {
                    "league": {"type": "string", "description": "Código de la liga (ej: 'CHL', 'ARG', 'PL')"}
                },
                "required": ["league"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_system_performance",
            "description": "Consulta las métricas globales del sistema y estado de las predicciones.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    }
]


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
        res = func(**arguments)
        elapsed = (time.perf_counter() - start_time) * 1000
        return ToolCallRecord(
            tool_name=name,
            arguments=arguments,
            result=res,
            success=True,
            execution_time_ms=round(elapsed, 2)
        )
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

