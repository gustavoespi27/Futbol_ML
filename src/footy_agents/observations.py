"""Observaciones tipadas: el resultado de cada herramienta se clasifica para que el agente decida cómo seguir.

Una herramienta puede responder bien y aun así no servir para la pregunta (equipo inexistente, partido sin precio de
Pinnacle, datos atrasados). La observación nombra esa situación (`status`), la explica (`note`) y ofrece las acciones
válidas para continuar (`options`): el LLM elige el camino, no hay un flujo fijo. Las notas no llevan cifras para que
el modelo no cite números sin respaldo de la herramienta.
"""

from typing import Literal

from footy_agents.schemas import AgentSchema, ToolCallRecord

Status = Literal["ok", "empty", "not_found", "ambiguous", "no_pinnacle", "started", "stale_data", "error"]

# Situaciones en las que el orquestador insiste una vez si el modelo responde sin probar la opción sugerida.
RECOVERABLE = {"not_found"}


class Observation(AgentSchema):
    status: Status
    note: str = ""
    options: list[str] = []


OK = Observation(status="ok")


def _failed(record: ToolCallRecord) -> Observation:
    message = record.error_message or ""
    if "Liga no reconocida" in message:
        return Observation(status="not_found", note="La liga no está en el catálogo; usa uno de los códigos cercanos.")
    if record.tool_name == "simulate_match" and ("equipo" in message.lower() or "team" in message.lower()):
        return Observation(status="not_found", note="Un equipo no se reconoció en esa liga.", options=["find_team"])
    if record.tool_name == "get_team_form":
        return Observation(status="not_found", note="No se reconoció el nombre exacto del equipo.",
                           options=["find_team"])
    if record.tool_name == "analyze_match":
        return Observation(status="not_found", note="El partido no está en el calendario próximo.",
                           options=["find_team", "get_upcoming_matches"])
    return Observation(status="error", note="La herramienta falló; corrige los argumentos o explica la limitación.")


def observe(record: ToolCallRecord) -> Observation:
    """Clasifica un resultado de herramienta de forma determinista."""
    if not record.success:
        return _failed(record)
    name, result, args = record.tool_name, record.result, record.arguments
    if name in {"create_watch", "list_watches", "cancel_watch", "add_favorite"} and isinstance(result, dict):
        return Observation(status="ok", note=result.get("note", "Objetivos consultados."),
                           options=["list_watches"] if name == "create_watch" else [])
    if isinstance(result, dict) and "error" in result:
        return Observation(status="not_found", note=str(result["error"]))

    if name == "get_upcoming_matches":
        if not result:
            if args.get("team"):
                return Observation(status="not_found", note="Ningún partido próximo coincide con ese nombre de equipo.",
                                   options=["find_team"])
            return Observation(status="empty", note="No hay partidos próximos con ese filtro.",
                               options=["get_coverage"])
        if not any(row.get("has_pinnacle_price") for row in result):
            return Observation(status="no_pinnacle",
                               note="Ningún partido listado tiene precio de Pinnacle: no se puede evaluar ventaja.",
                               options=["analyze_match", "get_coverage"])
        return OK

    if name == "get_value_bets" and not result:
        return Observation(status="empty", note="Ninguna selección supera la ventaja mínima frente a Pinnacle.",
                           options=["get_coverage"])

    if name == "find_team":
        if not result:
            return Observation(status="not_found", note="No hay equipos con un nombre parecido.")
        exact = [row for row in result if row.get("exact")]
        if len(result) > 1 and len(exact) != 1:
            return Observation(status="ambiguous", note="Varios equipos coinciden; pregunta cuál o elige el exacto.",
                               options=["analyze_match"])
        chosen = exact[0] if exact else result[0]
        if chosen.get("next_match") is None:
            return Observation(status="ok", note="Equipo identificado, sin partido en el calendario próximo: "
                                                 "ofrece su forma reciente.", options=["get_team_form"])
        return Observation(status="ok", note="Equipo identificado.", options=["analyze_match", "get_team_form"])

    if name == "analyze_match":
        if result.get("status") == "started":
            return Observation(status="started", note="El partido ya comenzó: no hay pronóstico previo vigente.",
                               options=["get_upcoming_matches"])
        if result.get("status") == "no_pinnacle":
            return Observation(status="no_pinnacle",
                               note="Sin precio de Pinnacle: entrega probabilidades del modelo, sin hablar de ventaja.",
                               options=["get_coverage"])
        return OK

    if name == "get_coverage" and result.get("stale"):
        return Observation(status="stale_data", note="Los datos no se actualizan hace más de un día: adviértelo.")
    return OK
