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
from footy_agents.grounding import check_claims, verify_numbers
from footy_agents.llm import LLMBusy, LLMClient, LLMUnavailable, TextDelta, ToolCall
from footy_agents.memory import entities_from
from footy_agents.observations import RECOVERABLE, Observation, observe
from footy_agents.routing import intent_route, is_follow_up
from footy_agents.schemas import ChatEvent, ToolCallRecord, UserPreferences
from footy_agents.tools import OPENAI_TOOLS_SPEC, TOOL_MODELS, execute_tool, upcoming_focus

MAX_ITERATIONS = 4             # rondas con herramientas: la cuarta inferencia ya no las ofrece
MAX_INFERENCES = 7             # 4 rondas + un reintento por pseudollamada + una recuperación + una reparación
SAFE_TEXT = "No pude verificar una respuesta con los datos disponibles."
SAFE_BET = re.compile(r"\b(?:combinadas?|apuestas?|parlay|pick|fija)\b[^.?!]*\bsegur[ao]s?\b|"
                      r"\bsegur[ao]s?\b[^.?!]*\b(?:combinadas?|apuestas?|parlay|pick)\b|\b(?:la )?fija\b", re.I)
SAFE_BET_TEXT = ("No existen apuestas ni combinadas seguras: cada selección tiene probabilidad de perder y, al "
                 "combinarlas, el riesgo se multiplica. El sistema solo marca valor cuando una cuota supera el precio "
                 "justo de Pinnacle, y aun así es seguimiento en papel, no consejo financiero. En la sección "
                 "Combinadas puedes ver cómo se calcula la probabilidad conjunta, con fines educativos.")
# El modelo anuncia o pide lo que podría consultar él mismo: se le recuerda una vez que use las herramientas.
# Afirmaciones del dominio sin haber consultado nada: deben salir de una herramienta, no de la memoria del modelo.
DOMAIN_CLAIM = re.compile(r"\b(?:pinnacle|apuestas?|partidos?|probabilidad(?:es)?|cuotas?|favorit[oa]s?|"
                          r"atrasad[oa]s?|desactualizad[oa]s?|ventaja|goles|tabla|rendimiento|clv|yield|"
                          r"aciertos?|fiab\w*)\b", re.I)
ASKS_INSTEAD = re.compile(r"\b(?:necesito|buscar[ée]|buscaremos|voy a (?:buscar|consultar)|primero,|"
                          r"podr[ií]as? (?:proporcionar|indicar|darme)|proporciona)\b", re.I)


LEAK = re.compile(r"CallCheck|Llamando a la herramienta|\b(?:" + "|".join(re.escape(n) for n in TOOL_MODELS) + r")\b",
                  re.I)
SENTENCE = re.compile(r"[^.!?\n]*(?:[.!?]+|\n|$)")


def has_tool_leak(text: str) -> bool:
    """Las llamadas se ejecutan como herramientas, nunca como instrucciones visibles."""
    return bool(LEAK.search(text))


def strip_tool_mentions(text: str) -> str:
    """Quita solo las oraciones que nombran herramientas («puedes usar analyze_match»); el resto se conserva."""
    kept = [s for s in SENTENCE.findall(text) if not LEAK.search(s)]
    return re.sub(r"\n{3,}", "\n\n", "".join(kept)).strip()
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
   Para un partido del calendario usa analyze_match; para un encuentro hipotético usa simulate_match.
10. Si piden una combinada segura, responde primero: «No existen combinadas seguras» y remite a la sección
    Combinadas, de alcance educativo. No inventes una combinación ni recomiendes una apuesta individual como sustituto.
11. CLV significa valor de la línea de cierre. No inventes otras definiciones ni justifiques métricas negativas.
12. Cada resultado de herramienta trae status, note y options. Si status no es ok, decide el siguiente paso con
    options en vez de rendirte: not_found → find_team con el nombre que dio el usuario; ambiguous → elige el equipo
    exacto o pregunta cuál; no_pinnacle → entrega las probabilidades del modelo y aclara que no se puede evaluar
    ventaja; started → infórmalo; stale_data → advierte que los datos están atrasados antes de citar cifras.
13. Para analizar un partido concreto usa analyze_match con su match_id (si no lo tienes, búscalo con find_team).
    Para «por qué no hay apuestas» o «qué tan actualizados están los datos», usa get_coverage; nunca afirmes nada
    sobre frescura o cobertura de datos sin haberla consultado. Para «cómo llega» un equipo, usa get_team_form.
14. Los mensajes anteriores de la conversación son contexto: vuelve a consultar las herramientas para las cifras.
15. Termina respondiendo la pregunta original del usuario. Los desvíos sirven para completar la respuesta, no para
    cambiar de tema: si consultaste el rendimiento, cita sus métricas aunque hayas revisado otras cosas.
16. Si un resultado trae *_text, assessment o summary, úsalo textual para esa idea; no lo reformules con otras cifras.
    Usa también favorite para identificar al favorito; no deduzcas un ganador garantizado.

Ruteo (pregunta → herramienta):
«Analiza / quién gana un partido próximo» → find_team → analyze_match.
«¿Y quién es favorito?» → analyze_match con match_id del contexto reciente; vuelve a consultar.
«Simula A contra B» (hipotético) → simulate_match.
«Cómo llega el equipo» → get_team_form; apodo desconocido → find_team.
«Qué partidos hay» → get_upcoming_matches.
«Hay ventaja» → get_value_bets; «por qué no hay apuestas / frescura» → get_coverage.
«Cómo va en la tabla» → get_league_standings.
«Rendimiento / CLV» → get_system_performance; «banca / cuánto apostar» → get_stake_limits.
Si find_team da un único exacto con next_match y pidieron análisis/pronóstico, ve directo a analyze_match;
no repitas get_upcoming_matches ni consultes forma o cobertura antes del análisis.

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


LABELS = {
    "get_upcoming_matches": "próximos partidos", "get_value_bets": "apuestas con valor", "simulate_match": "simulación",
    "get_league_standings": "tabla de posiciones", "get_system_performance": "rendimiento del sistema",
    "get_stake_limits": "límites de exposición", "find_team": "búsqueda del equipo",
    "analyze_match": "análisis del partido", "get_coverage": "cobertura de datos",
    "get_team_form": "forma reciente del equipo",
}
REASONS = {
    "not_found": "no se encontró lo pedido", "empty": "no hubo resultados", "ambiguous": "hay varias coincidencias",
    "no_pinnacle": "no hay precio de Pinnacle", "started": "el partido ya comenzó",
    "stale_data": "los datos están atrasados", "error": "la consulta anterior falló",
}


def _step(kind: str, text: str) -> ChatEvent:
    """Paso visible del razonamiento del agente: observación, desvío, recuperación o reparación."""
    return ChatEvent(event="step", data={"kind": kind, "text": text})


def _tool_message(call: ToolCall, record: ToolCallRecord, obs: Observation) -> dict:
    payload = {"status": obs.status, "note": obs.note, "options": obs.options}
    if record.success:
        payload["data"] = record.result
    else:
        payload["error"] = record.error_message
    content = json.dumps(payload, ensure_ascii=False, default=str)
    if len(content) > MAX_TOOL_CHARS:
        content = content[:MAX_TOOL_CHARS] + "… (resultado truncado)"
    return {"role": "tool", "tool_call_id": call.id, "content": content}


def _assistant_calls(text: str, calls: list[ToolCall]) -> dict:
    return {"role": "assistant", "content": text, "tool_calls": [
        {"id": c.id, "type": "function",
         "function": {"name": c.name, "arguments": json.dumps(c.arguments, ensure_ascii=False)}} for c in calls]}


def _run_call(call: ToolCall) -> ToolCallRecord:
    if call.raw_arguments:
        return ToolCallRecord(tool_name=call.name, arguments={}, result=None, success=False, execution_time_ms=0.0,
                              error_message=f"Argumentos no son JSON válido: {call.raw_arguments[:200]}")
    return execute_tool(call.name, call.arguments)


class _Turn:
    """Estado de un turno: herramientas usadas, opciones sugeridas por las observaciones y mensajes al LLM."""

    def __init__(self, messages: list[dict]):
        self.messages = messages
        self.records: list[ToolCallRecord] = []
        self.suggested: dict[str, str] = {}      # herramienta sugerida -> estado que la sugirió
        self.used: set[str] = set()
        self.entities: dict = {}

    def execute(self, call: ToolCall) -> Iterator[ChatEvent]:
        reason = self.suggested.pop(call.name, None)
        if reason:
            yield _step("deviation", f"Cambio de camino: {LABELS.get(call.name, call.name)}, "
                                     f"porque {REASONS[reason]}.")
        yield ChatEvent(event="tool_start", data={"tool": call.name, "args": call.arguments})
        record = _run_call(call)
        self.records.append(record)
        self.entities = entities_from(record) or self.entities
        self.used.add(call.name)
        obs = observe(record)
        yield ChatEvent(event="tool_result", data={
            "tool": call.name, "success": record.success, "elapsed_ms": record.execution_time_ms,
            "summary": obs.note if record.success and obs.status != "ok" else summarize(record)})
        if obs.status != "ok":
            yield _step("observation", obs.note)
            for option in obs.options:
                if option in TOOL_MODELS and option not in self.used:
                    self.suggested.setdefault(option, obs.status)
        self.messages.append(_tool_message(call, record, obs))

    def pending_recovery(self) -> str | None:
        return next((tool for tool, status in self.suggested.items() if status in RECOVERABLE), None)


def run_chat(client: LLMClient, message: str, prefs: UserPreferences,
             history: list[dict] | None = None, entities: dict | None = None,
             consulted_entities: dict | None = None) -> Iterator[ChatEvent]:
    """Un turno del usuario. Emite eventos step, tool_start, tool_result, token, done y error (contrato SSE).

    El camino no es fijo: cada resultado se clasifica (observations.observe) y el modelo decide con esa observación.
    Si el modelo se rinde ante un «no encontrado» sin probar la vía sugerida, se le pide una vez que la evalúe
    (recuperación); si cita cifras sin respaldo, reescribe una vez sin ellas (reparación) antes de mostrar nada.
    """
    if SAFE_BET.search(message):
        yield _step("policy", "Premisa rechazada: no existen apuestas seguras; responde la regla de riesgo.")
        yield ChatEvent(event="token", data={"delta": SAFE_BET_TEXT})
        yield ChatEvent(event="done", data={"iterations": 0, "success": True})
        return
    follows = is_follow_up(message, entities)
    history = (history or [])[-2:] if follows else []
    entities = entities if follows else None
    if follows:
        subject = (f"{entities.get('home')} vs {entities.get('away')}" if entities and entities.get("home")
                   else (entities or {}).get("team", "el tema anterior"))
        yield _step("observation", f"Continúa la conversación sobre {subject}")
    context = ""
    if entities:
        context = "\nContexto reciente (solo identidad; vuelve a consultar cifras): "
        if entities.get("match_id"):
            context += (f"último partido consultado match_id={entities['match_id']} "
                        f"({entities.get('home', '?')} vs {entities.get('away', '?')}). ")
        context += json.dumps(entities, ensure_ascii=False)
        context += ("\nSi la pregunta continúa sobre este partido (por ejemplo «¿y quién es favorito?»), "
                    "llama directamente a analyze_match con el match_id indicado. No vuelvas a buscar el equipo "
                    "con find_team ni el calendario: ya está identificado. Si el usuario cambia de equipo, "
                    "resuelve la nueva entidad.")
    turn = _Turn([{"role": "system", "content": system_prompt(prefs) + context}, *(history or []),
                  {"role": "user", "content": message}])
    route = intent_route(message, entities)
    recovery_hint = (f"La pregunta original requiere {route[0]}; argumentos conocidos: "
                     f"{json.dumps(route[1], ensure_ascii=False)}. Haz una llamada real y responde a esa pregunta."
                     if route else "Responde a la pregunta original sin inventar datos.")
    try:
        focus = upcoming_focus(message)
    except Exception:  # noqa: BLE001 - precarga opcional; el fallo no debe impedir el chat
        focus = None
    if focus:
        call = ToolCall(id="preload_upcoming", name="get_upcoming_matches", arguments=focus)
        turn.messages.append(_assistant_calls("", [call]))
        yield from turn.execute(call)
        if consulted_entities is not None and turn.entities:
            consulted_entities.update(turn.entities)
        if turn.entities.get("match_id") and ("analiza" in message.lower() or "pronost" in message.lower()):
            route = ("analyze_match", {"match_id": turn.entities["match_id"]})
            recovery_hint = (f"Consulta analyze_match con argumentos {json.dumps(route[1])}; "
                             "responde al análisis pedido.")

    tool_rounds, leak_retried, recovered, repaired = 0, False, False, False
    iteration = 0
    for iteration in range(1, MAX_INFERENCES + 1):
        tools = OPENAI_TOOLS_SPEC if tool_rounds < MAX_ITERATIONS - 1 else None
        text: list[str] = []
        calls: list[ToolCall] = []
        try:
            for ev in client.stream_chat(turn.messages, tools):
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

        if calls:
            if tools is None:   # pidió herramientas cuando ya no se ofrecían: se corta el turno
                break
            turn.messages.append(_assistant_calls("".join(text), calls))
            for call in calls:
                yield from turn.execute(call)
                if consulted_entities is not None and turn.entities:
                    consulted_entities.clear()
                    consulted_entities.update(turn.entities)
            tool_rounds += 1
            continue

        answer = "".join(text)
        if not answer.strip():
            yield ChatEvent(event="error", data={"error": "El modelo no devolvió respuesta."})
            yield ChatEvent(event="done", data={"iterations": iteration, "success": False})
            return
        if has_tool_leak(answer) and len(strip_tool_mentions(answer)) >= 40:
            answer = strip_tool_mentions(answer)      # sugerencia técnica al final de una respuesta útil: se recorta
        if has_tool_leak(answer):
            if not leak_retried:
                leak_retried = True
                turn.messages.extend([{"role": "assistant", "content": answer}, {"role": "user", "content":
                    "Ejecuta una llamada real si hace falta consultar; "
                    "responde sin pseudollamadas ni nombres técnicos."}])
                continue
            yield ChatEvent(event="error", data={"error": SAFE_TEXT})
            yield ChatEvent(event="token", data={"delta": SAFE_TEXT})
            yield ChatEvent(event="done", data={"iterations": iteration, "success": False})
            return
        unsupported = ASKS_INSTEAD.search(answer) or DOMAIN_CLAIM.search(answer)
        missing_route = route and route[0] not in turn.used
        if not recovered and (missing_route or (not turn.used and unsupported)) and tool_rounds < MAX_ITERATIONS - 1:
            recovered = True
            label = LABELS.get(route[0], route[0]) if route else "datos de este turno"
            yield _step("recovery", f"El agente decide consultar {label}")
            turn.messages.extend([{"role": "assistant", "content": answer},
                                  {"role": "user", "content": recovery_hint}])
            continue
        pending = turn.pending_recovery()
        if pending and not recovered and tool_rounds < MAX_ITERATIONS - 1:
            recovered = True
            yield _step("recovery", f"Antes de responder, el agente prueba otra vía: {LABELS.get(pending, pending)}.")
            turn.messages.extend([{"role": "assistant", "content": answer}, {"role": "user", "content":
                f"Antes de responder: la observación sugiere {pending} y aún no lo usaste. "
                "Úsalo con el nombre que dio el usuario y luego responde."}])
            continue
        report = verify_numbers(answer, turn.records, user_message=message)
        claims = check_claims(answer, turn.records)
        report.unverified.extend(claims.unverified)
        report.verified = report.verified and claims.verified
        if not report.verified and not repaired:
            repaired = True
            yield _step("repair", "La respuesta contiene cifras sin respaldo o una interpretación incorrecta; "
                                  "el agente la reescribe con los textos verificados.")
            turn.messages.extend([{"role": "assistant", "content": answer}, {"role": "user", "content":
                "Corrige estos hallazgos de verificación: "
                + ", ".join(report.unverified) + ". Si las necesitas, vuelve a consultarlas con la herramienta "
                "que corresponda; si no, reescribe la respuesta completa sin ellas. Copia literalmente form_text, "
                "limits_text y assessment para las ideas correspondientes, sin reinterpretarlas."}])
            continue
        if not report.verified:
            yield ChatEvent(event="error", data={"error": SAFE_TEXT})
            yield ChatEvent(event="token", data={"delta": SAFE_TEXT})
        else:
            for start in range(0, len(answer), 80):
                yield ChatEvent(event="token", data={"delta": answer[start:start + 80]})
        yield ChatEvent(event="done", data={"iterations": iteration, "success": report.verified})
        return

    yield ChatEvent(event="error", data={"error": f"Se alcanzó el límite de {MAX_ITERATIONS} iteraciones."})
    yield ChatEvent(event="done", data={"iterations": iteration, "success": False})
