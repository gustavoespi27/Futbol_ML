"""Micro-orquestador del chat: bucle secuencial de tool-calling con guardrails, sin frameworks.

Cada turno del usuario: el LLM decide qué herramientas llamar, se ejecutan con el dispatcher tipado y sus resultados
vuelven al LLM, como máximo MAX_ITERATIONS veces. La última iteración se hace sin herramientas para forzar la
respuesta. El LLM no calcula nada: toda cifra que cite debe salir de un ToolCallRecord (lo exige el system prompt).
"""

import json
import re
from collections.abc import Iterator
from datetime import datetime

from footy.web.services.context import LOCAL_TZ
from footy_agents.grounding import verify_numbers
from footy_agents.llm import LLMBusy, LLMClient, LLMUnavailable, TextDelta, ToolCall
from footy_agents.schemas import ChatEvent, ToolCallRecord, UserPreferences
from footy_agents.tools import OPENAI_TOOLS_SPEC, TOOL_MODELS, execute_tool, upcoming_focus

MAX_ITERATIONS = 4
SAFE_TEXT = "No pude verificar una respuesta con los datos disponibles."


def has_tool_leak(text: str) -> bool:
    """Las llamadas se ejecutan como herramientas, nunca como instrucciones visibles."""
    return bool(re.search(r"CallCheck|Llamando a la herramienta|\b(?:" +
                          "|".join(re.escape(name) for name in TOOL_MODELS) + r")\b", text, re.I))
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
5. Solo describe una selección como apuesta con valor si viene de get_value_bets o lleva value_status=con_ventaja.
   Una probabilidad alta no demuestra ventaja. Sin precio Pinnacle, indica que no se puede evaluar la ventaja.
6. No existen apuestas ni combinadas seguras. Remite a Combinadas como herramienta educativa, sin prometer ganancias.
   No pidas la banca salvo que el usuario solicite límites o montos; usa get_stake_limits para calcularlos.
7. No escribas nombres de herramientas, pseudollamadas ni instrucciones técnicas en la respuesta final.
   Usa llamadas reales para consultar. Si piden simular dos equipos, usa simulate_match.
8. Puedes citar los límites de riesgo oficiales y las cifras aportadas por el usuario, sin inventar cálculos.
9. Una precarga de próximos partidos es solo contexto: NO sustituye la consulta que pidió el usuario.
   Para «en la tabla», consulta get_league_standings con el código de liga de la precarga.
   Para «cuánto apostar si tengo X pesos», llama get_stake_limits con X; esa cifra YA es la banca.
   Nunca preguntes cuánto dedicar ni qué porcentaje quiere arriesgar: los límites son fijos.
   Copia los montos formateados de la herramienta (pesos es-CL); no cambies sus separadores ni hagas cálculos.
   Para «quién gana A vs B», consulta simulate_match y explica las probabilidades sin asegurar un ganador.
10. Si piden una combinada segura, responde primero: «No existen combinadas seguras» y remite a la sección
    Combinadas, de alcance educativo. No inventes una combinación ni recomiendes una apuesta individual como sustituto.
11. CLV significa valor de la línea de cierre. No inventes otras definiciones ni justifiques métricas negativas.

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
    records: list[ToolCallRecord] = []
    try:
        focus = upcoming_focus(message)
    except Exception:  # noqa: BLE001 - precarga opcional; el fallo no debe impedir el chat
        focus = None
    if focus:
        call = ToolCall(id="preload_upcoming", name="get_upcoming_matches", arguments=focus)
        yield ChatEvent(event="tool_start", data={"tool": call.name, "args": call.arguments})
        record = _run_call(call)
        records.append(record)
        messages.extend([{"role": "assistant", "content": "", "tool_calls": [
            {"id": call.id, "type": "function", "function": {"name": call.name,
             "arguments": json.dumps(focus, ensure_ascii=False)}}]}, _tool_message(call, record)])
        yield ChatEvent(event="tool_result", data={"tool": call.name, "success": record.success,
                                                   "elapsed_ms": record.execution_time_ms,
                                                   "summary": summarize(record)})
    leak_retried = False

    for iteration in range(1, MAX_ITERATIONS + 1):
        tools = OPENAI_TOOLS_SPEC if iteration < MAX_ITERATIONS else None
        text: list[str] = []
        calls: list[ToolCall] = []
        try:
            for ev in client.stream_chat(messages, tools):
                if isinstance(ev, TextDelta):
                    text.append(ev.text)
                else:
                    calls.append(ev)
        except LLMBusy as exc:
            yield ChatEvent(event="error", data={"error": str(exc)})
            yield ChatEvent(event="done", data={"iterations": iteration, "success": False})
            return
        except LLMUnavailable:
            if iteration == 1:
                yield ChatEvent(event="token", data={"delta": UNAVAILABLE_TEXT})
            else:
                yield ChatEvent(event="error", data={"error": "El motor de IA local dejó de responder."})
            yield ChatEvent(event="done", data={"iterations": iteration, "success": False})
            return

        if not calls:
            answer = "".join(text)
            if not answer.strip():
                yield ChatEvent(event="error", data={"error": "El modelo no devolvió respuesta."})
                yield ChatEvent(event="done", data={"iterations": iteration, "success": False})
                return
            if has_tool_leak(answer):
                if not leak_retried and iteration < MAX_ITERATIONS:
                    leak_retried = True
                    messages.extend([{"role": "assistant", "content": answer}, {"role": "user", "content":
                        "Ejecuta una llamada real si hace falta consultar; "
                        "responde sin pseudollamadas ni nombres técnicos."}])
                    continue
                yield ChatEvent(event="error", data={"error": SAFE_TEXT})
                yield ChatEvent(event="token", data={"delta": SAFE_TEXT})
                yield ChatEvent(event="done", data={"iterations": iteration, "success": False})
                return
            report = verify_numbers(answer, records, user_message=message)
            if not report.verified:
                yield ChatEvent(event="error", data={"error": SAFE_TEXT})
                yield ChatEvent(event="token", data={"delta": SAFE_TEXT})
            else:
                for start in range(0, len(answer), 80):
                    yield ChatEvent(event="token", data={"delta": answer[start:start + 80]})
            yield ChatEvent(event="done", data={"iterations": iteration, "success": report.verified})
            return

        messages.append({"role": "assistant", "content": "".join(text), "tool_calls": [
            {"id": c.id, "type": "function",
             "function": {"name": c.name, "arguments": json.dumps(c.arguments, ensure_ascii=False)}}
            for c in calls]})
        for call in calls:
            yield ChatEvent(event="tool_start", data={"tool": call.name, "args": call.arguments})
            record = _run_call(call)
            records.append(record)
            yield ChatEvent(event="tool_result", data={"tool": call.name, "success": record.success,
                                                       "elapsed_ms": record.execution_time_ms,
                                                       "summary": summarize(record)})
            messages.append(_tool_message(call, record))

    # el modelo pidió herramientas incluso en la iteración final (sin herramientas ofrecidas): se corta el turno
    yield ChatEvent(event="error", data={"error": f"Se alcanzó el límite de {MAX_ITERATIONS} iteraciones."})
    yield ChatEvent(event="done", data={"iterations": MAX_ITERATIONS, "success": False})
