"""Micro-orquestador del chat: bucle secuencial de tool-calling con guardrails, sin frameworks.

Cada turno del usuario: el LLM decide qué herramientas llamar, se ejecutan con el dispatcher tipado y sus resultados
vuelven al LLM, como máximo MAX_ITERATIONS veces. La última iteración se hace sin herramientas para forzar la
respuesta. El LLM no calcula nada: toda cifra que cite debe salir de un ToolCallRecord (lo exige el system prompt).
"""

import json
from collections.abc import Iterator
from datetime import datetime

from footy.web.services.context import LOCAL_TZ
from footy_agents.llm import LLMClient, LLMUnavailable, TextDelta, ToolCall
from footy_agents.schemas import ChatEvent, ToolCallRecord, UserPreferences
from footy_agents.tools import OPENAI_TOOLS_SPEC, execute_tool

MAX_ITERATIONS = 4
MAX_TOOL_CHARS = 6000          # resultado de una herramienta que se le pasa al LLM (protege la ventana de contexto)

UNAVAILABLE_TEXT = ("El motor de IA local no está disponible en este momento (Ollama no responde). "
                    "El feed personalizado, las predicciones y las estadísticas del panel siguen operativos.")

SYSTEM_PROMPT = """Eres el asistente de Futbol_ML, un sistema cuantitativo de predicción de fútbol y apuestas de valor.
Responde siempre en español, de forma breve y directa.

Reglas estrictas:
1. NUNCA inventes probabilidades, cuotas, marcadores, goles esperados, posiciones ni métricas. Toda cifra que cites
   debe venir textualmente del resultado de una herramienta de este turno. Si no tienes el dato, dilo.
2. Para cualquier pregunta sobre partidos, equipos, tablas, apuestas o rendimiento, llama primero a la herramienta
   que corresponda.
3. Las apuestas con valor solo existen frente al precio justo de Pinnacle; el stake es 1/4 de Kelly con tope de 2% del
   bankroll por apuesta y 10% diario. No recomiendes superar esos límites.
4. Las apuestas del sistema son seguimiento en papel; aclara que no es consejo financiero si el usuario pide apostar.

Hoy es {today} (hora de Chile).
Preferencias del usuario: equipos favoritos {teams}; ligas favoritas {leagues}; perfil de riesgo {risk}."""


def system_prompt(prefs: UserPreferences) -> str:
    return SYSTEM_PROMPT.format(
        today=datetime.now(LOCAL_TZ).strftime("%Y-%m-%d"),
        teams=", ".join(prefs.favorite_teams) or "ninguno",
        leagues=", ".join(prefs.favorite_leagues) or "ninguna",
        risk=prefs.risk_profile,
    )


def summarize(record: ToolCallRecord) -> str:
    """Resumen corto para la interfaz (el detalle completo solo lo ve el LLM)."""
    if not record.success:
        return f"Error: {record.error_message}"
    res = record.result
    if isinstance(res, dict) and "error" in res:
        return str(res["error"])
    if isinstance(res, list):
        return f"{len(res)} resultado(s)"
    return "OK"


def _tool_message(call: ToolCall, record: ToolCallRecord) -> dict:
    payload = record.result if record.success else {"error": record.error_message}
    content = json.dumps(payload, ensure_ascii=False, default=str)
    if len(content) > MAX_TOOL_CHARS:
        content = content[:MAX_TOOL_CHARS] + "… (resultado truncado)"
    return {"role": "tool", "tool_call_id": call.id, "content": content}


def _run_call(call: ToolCall) -> ToolCallRecord:
    if call.raw_arguments:
        return ToolCallRecord(tool_name=call.name, arguments={}, result=None, success=False, execution_time_ms=0.0,
                              error_message=f"Argumentos no son JSON válido: {call.raw_arguments[:200]}")
    return execute_tool(call.name, call.arguments)


def run_chat(client: LLMClient, message: str, prefs: UserPreferences,
             history: list[dict] | None = None) -> Iterator[ChatEvent]:
    """Un turno del usuario. Emite eventos tool_start, tool_result, token, done y error (contrato SSE)."""
    messages = [{"role": "system", "content": system_prompt(prefs)}, *(history or []),
                {"role": "user", "content": message}]

    for iteration in range(1, MAX_ITERATIONS + 1):
        tools = OPENAI_TOOLS_SPEC if iteration < MAX_ITERATIONS else None
        text: list[str] = []
        calls: list[ToolCall] = []
        try:
            for ev in client.stream_chat(messages, tools):
                if isinstance(ev, TextDelta):
                    text.append(ev.text)
                    yield ChatEvent(event="token", data={"delta": ev.text})
                else:
                    calls.append(ev)
        except LLMUnavailable:
            if iteration == 1:
                yield ChatEvent(event="token", data={"delta": UNAVAILABLE_TEXT})
            else:
                yield ChatEvent(event="error", data={"error": "El motor de IA local dejó de responder."})
            yield ChatEvent(event="done", data={"iterations": iteration, "success": False})
            return

        if not calls:
            if not "".join(text).strip():
                yield ChatEvent(event="error", data={"error": "El modelo no devolvió respuesta."})
                yield ChatEvent(event="done", data={"iterations": iteration, "success": False})
                return
            yield ChatEvent(event="done", data={"iterations": iteration, "success": True})
            return

        messages.append({"role": "assistant", "content": "".join(text), "tool_calls": [
            {"id": c.id, "type": "function",
             "function": {"name": c.name, "arguments": json.dumps(c.arguments, ensure_ascii=False)}}
            for c in calls]})
        for call in calls:
            yield ChatEvent(event="tool_start", data={"tool": call.name, "args": call.arguments})
            record = _run_call(call)
            yield ChatEvent(event="tool_result", data={"tool": call.name, "success": record.success,
                                                       "elapsed_ms": record.execution_time_ms,
                                                       "summary": summarize(record)})
            messages.append(_tool_message(call, record))

    # el modelo pidió herramientas incluso en la iteración final (sin herramientas ofrecidas): se corta el turno
    yield ChatEvent(event="error", data={"error": f"Se alcanzó el límite de {MAX_ITERATIONS} iteraciones."})
    yield ChatEvent(event="done", data={"iterations": MAX_ITERATIONS, "success": False})
