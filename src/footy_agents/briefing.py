"""Resumen personalizado en lenguaje natural (el "párrafo matutino" del usuario).

El código decide QUÉ contar (ficha de hechos determinista sacada del feed); el LLM solo decide CÓMO contarlo, sin
herramientas y sin poder agregar cifras. Si el LLM no responde, el resumen se arma con una plantilla: el usuario
siempre recibe su resumen.
"""

import json
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

from footy.web.services.context import LOCAL_TZ
from footy_agents.llm import LLMClient, LLMUnavailable, TextDelta
from footy_agents.schemas import ChatEvent, FeedItem, PersonalizedFeedResponse, UserPreferences

HORIZON_HOURS = 24
MAX_ITEMS = 5

BRIEFING_PROMPT = """Eres el asistente de Futbol_ML. Escribe en español un resumen breve (3 a 5 oraciones, un solo
párrafo, sin listas ni títulos) de lo que le interesa hoy al usuario, usando SOLO la ficha de hechos en JSON.
Reglas estrictas:
- No agregues cifras, cuotas, probabilidades ni resultados que no estén en la ficha.
- Menciona primero los partidos de sus equipos favoritos, luego las apuestas con valor (edge frente a Pinnacle).
- Si no hay apuestas con valor, dilo: no apostar también es una decisión.
- Las apuestas son seguimiento en papel, no consejo financiero.
- Perfil de riesgo del usuario: {risk}."""


def _local_time(kickoff: str) -> str:
    dt = datetime.fromisoformat(kickoff.replace("Z", "+00:00")).astimezone(LOCAL_TZ)
    return dt.strftime("%H:%M")


def facts(feed: PersonalizedFeedResponse, now: datetime | None = None) -> dict:
    """Ficha de hechos: partidos de las próximas HORIZON_HOURS horas que importan al usuario, ya ordenados."""
    now = now or datetime.now(timezone.utc)
    limit = now + timedelta(hours=HORIZON_HOURS)

    def soon(item: FeedItem) -> bool:
        if not item.kickoff:
            return False
        ko = datetime.fromisoformat(item.kickoff.replace("Z", "+00:00"))
        return now <= ko <= limit

    relevant = [i for i in feed.items if soon(i) and (i.is_favorite_team or i.is_favorite_league or i.value_bets_count)]

    def row(i: FeedItem) -> dict:
        out = {"partido": f"{i.home_team} vs {i.away_team}", "liga": i.league_name or i.league,
               "hora_chile": _local_time(i.kickoff), "equipo_favorito": i.is_favorite_team}
        if i.best_edge is not None:
            out["edge_pinnacle"] = f"+{i.best_edge * 100:.1f}%"
        return out

    return {
        "partidos_equipos_favoritos": [row(i) for i in relevant if i.is_favorite_team][:MAX_ITEMS],
        "apuestas_con_valor": [row(i) for i in relevant if i.value_bets_count][:MAX_ITEMS],
        "otros_partidos_ligas_favoritas": [row(i) for i in relevant
                                           if i.is_favorite_league and not i.is_favorite_team
                                           and not i.value_bets_count][:MAX_ITEMS],
    }


def template_briefing(f: dict) -> str:
    """Resumen sin LLM (respaldo cuando el motor de IA local no está disponible)."""
    parts = []
    fav = f["partidos_equipos_favoritos"]
    if fav:
        parts.append("Hoy juegan tus equipos: " + "; ".join(f"{r['partido']} ({r['hora_chile']})" for r in fav) + ".")
    bets = f["apuestas_con_valor"]
    if bets:
        parts.append("Apuestas con valor frente a Pinnacle: " + "; ".join(
            f"{r['partido']} ({r['edge_pinnacle']})" for r in bets) + " (seguimiento en papel).")
    else:
        parts.append("No hay apuestas con valor en las próximas 24 horas: hoy no conviene apostar.")
    others = f["otros_partidos_ligas_favoritas"]
    if others:
        parts.append("En tus ligas también hay: " + "; ".join(
            f"{r['partido']} ({r['hora_chile']})" for r in others[:3]) + ".")
    return " ".join(parts)


def run_briefing(client: LLMClient, prefs: UserPreferences, feed: PersonalizedFeedResponse,
                 now: datetime | None = None) -> Iterator[ChatEvent]:
    """Mismo contrato SSE que el chat (token, done); done.success indica si lo redactó el LLM."""
    f = facts(feed, now)
    messages = [{"role": "system", "content": BRIEFING_PROMPT.format(risk=prefs.risk_profile)},
                {"role": "user", "content": json.dumps(f, ensure_ascii=False)}]
    wrote = False
    try:
        for ev in client.stream_chat(messages, None):
            if isinstance(ev, TextDelta) and ev.text:
                wrote = True
                yield ChatEvent(event="token", data={"delta": ev.text})
    except LLMUnavailable:
        if wrote:
            yield ChatEvent(event="error", data={"error": "El motor de IA local dejó de responder."})
            yield ChatEvent(event="done", data={"iterations": 1, "success": False})
            return
    if not wrote:
        yield ChatEvent(event="token", data={"delta": template_briefing(f)})
        yield ChatEvent(event="done", data={"iterations": 1, "success": False})
        return
    yield ChatEvent(event="done", data={"iterations": 1, "success": True})
