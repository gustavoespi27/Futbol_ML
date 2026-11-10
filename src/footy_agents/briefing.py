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
from footy_agents.persona import NAME, ROLE
from footy_agents.schemas import ChatEvent, FeedItem, PersonalizedFeedResponse, UserPreferences

HORIZON_HOURS = 24
MAX_ITEMS = 5

BRIEFING_PROMPT = f"Eres {NAME}, el {ROLE} de Futbol_ML: tono cercano y futbolero, sin emojis ni exageraciones. " + """
Escribe en español un resumen breve (3 a 5 oraciones, un solo
párrafo, sin listas ni títulos) de lo que le interesa hoy al usuario, usando SOLO la ficha de hechos en JSON.
Reglas estrictas:
- No agregues partidos, equipos, cifras, cuotas, probabilidades ni resultados que no estén en la ficha.
- Habla solo de las secciones que trae la ficha: si no trae equipos favoritos o ligas favoritas, no los menciones.
- Menciona primero los partidos de sus equipos favoritos, luego las apuestas con valor (edge frente a Pinnacle).
- Explica la cobertura_pinnacle: solo se evaluaron los partidos con referencia; los demás siguen sin cuotas.
- cobertura_pinnacle corresponde al calendario completo; cobertura_24h delimita los hechos de las próximas 24 horas.
- Si no hay apuestas con valor, limita la afirmación a los partidos evaluables y menciona los que faltan.
- Solo puedes decir «no conviene apostar» si la cobertura es completa y hay al menos un partido evaluable.
- Las apuestas son seguimiento en papel, no consejo financiero.
- Perfil de riesgo del usuario: {risk}."""


def _local_time(kickoff: str) -> str:
    dt = datetime.fromisoformat(kickoff.replace("Z", "+00:00")).astimezone(LOCAL_TZ)
    return dt.strftime("%H:%M")


def partidos(n: int) -> str:
    """Único formato de cantidad de partidos para los textos del resumen."""
    return f"{n} partido" + ("" if n == 1 else "s")


def facts(feed: PersonalizedFeedResponse, now: datetime | None = None) -> dict:
    """Ficha de hechos: partidos de las próximas HORIZON_HOURS horas que importan al usuario, ya ordenados."""
    now = now or datetime.now(timezone.utc)
    limit = now + timedelta(hours=HORIZON_HOURS)

    def soon(item: FeedItem) -> bool:
        if not item.kickoff:
            return False
        ko = datetime.fromisoformat(item.kickoff.replace("Z", "+00:00"))
        return now <= ko <= limit

    scheduled = [i for i in feed.items if soon(i)]
    evaluable = sum(i._has_pinnacle for i in scheduled)
    reference_total = sum(i._has_pinnacle for i in feed.items)
    relevant = [i for i in scheduled if i.is_favorite_team or i.is_favorite_league or i.value_bets_count]

    def row(i: FeedItem) -> dict:
        out = {"partido": f"{i.home_team} vs {i.away_team}", "liga": i.league_name or i.league,
               "hora_chile": _local_time(i.kickoff), "equipo_favorito": i.is_favorite_team}
        if i.best_edge is not None:
            out["edge_pinnacle"] = f"+{i.best_edge * 100:.1f}%"
        return out

    return {
        "cobertura_pinnacle": {"con_referencia": reference_total, "total": len(feed.items),
                               "sin_referencia": len(feed.items) - reference_total},
        "cobertura_24h": {"con_referencia": evaluable, "total": len(scheduled),
                               "sin_referencia": len(scheduled) - evaluable, "horizonte_horas": HORIZON_HOURS},
        "partidos_equipos_favoritos": [row(i) for i in relevant if i.is_favorite_team][:MAX_ITEMS],
        "apuestas_con_valor": [row(i) for i in relevant if i.value_bets_count][:MAX_ITEMS],
        "otros_partidos_ligas_favoritas": [row(i) for i in relevant
                                           if i.is_favorite_league and not i.is_favorite_team
                                           and not i.value_bets_count][:MAX_ITEMS],
    }


def llm_facts(f: dict) -> dict:
    """Ficha para el LLM: sin secciones vacías (un modelo pequeño las menciona igual, p. ej. "tus ligas favoritas"
    cuando el usuario no tiene ninguna). Las apuestas con valor van siempre: que no haya también es información."""
    return {k: v for k, v in f.items() if v or k == "apuestas_con_valor"}


def template_briefing(f: dict) -> str:
    """Resumen sin LLM (respaldo cuando el motor de IA local no está disponible)."""
    c = f["cobertura_pinnacle"]
    horizon = f["cobertura_24h"]
    n, total, missing = c["con_referencia"], c["total"], c["sin_referencia"]
    parts = [f"Calendario: {n} de {total} con Pinnacle."]
    fav = f["partidos_equipos_favoritos"]
    if fav:
        parts.append("Hoy juegan tus equipos: " + "; ".join(f"{r['partido']} ({r['hora_chile']})" for r in fav) + ".")
    bets = f["apuestas_con_valor"]
    if bets:
        parts.append("Apuestas con valor frente a Pinnacle: " + "; ".join(
            f"{r['partido']} ({r['edge_pinnacle']})" for r in bets) + " (seguimiento en papel).")
    else:
        if not total:
            parts.append("No hay partidos próximos en este periodo.")
        elif not n:
            parts.append(f"Sin referencia de Pinnacle para evaluar; {partidos(missing)} aún sin cuotas de referencia.")
        else:
            evaluated = horizon["con_referencia"]
            if evaluated:
                parts.append(f"Próximas 24 horas: sin ventaja en {partidos(evaluated)} con precio de Pinnacle.")
            else:
                parts.append("Próximas 24 horas: sin partidos evaluables con precio de Pinnacle.")
            if missing:
                parts.append(f"{partidos(missing)} aún sin cuotas de referencia en el calendario.")
            elif evaluated:
                parts.append("Con cobertura completa, hoy no conviene apostar (seguimiento en papel).")
    if bets and missing:
        parts.append(f"{partidos(missing)} aún sin cuotas de referencia; no se evaluó su ventaja.")
    others = f["otros_partidos_ligas_favoritas"]
    if others:
        parts.append("En tus ligas también hay: " + "; ".join(
            f"{r['partido']} ({r['hora_chile']})" for r in others[:3]) + ".")
    return " ".join(parts)


def run_briefing(client: LLMClient, prefs: UserPreferences, feed: PersonalizedFeedResponse,
                 now: datetime | None = None) -> Iterator[ChatEvent]:
    """Mismo contrato SSE que el chat (token, done). done.iterations = 0: sin hechos que narrar, se usó la plantilla
    sin consultar al LLM; done.success = False: el LLM no respondió y también se usó la plantilla."""
    f = facts(feed, now)
    if not any(f[k] for k in ("partidos_equipos_favoritos", "apuestas_con_valor", "otros_partidos_ligas_favoritas")):
        # con la ficha vacía un modelo pequeño inventa partidos para llenar el párrafo: no se le consulta
        yield ChatEvent(event="token", data={"delta": template_briefing(f)})
        yield ChatEvent(event="done", data={"iterations": 0, "success": True})
        return
    messages = [{"role": "system", "content": BRIEFING_PROMPT.format(risk=prefs.risk_profile)},
                {"role": "user", "content": json.dumps(llm_facts(f), ensure_ascii=False)}]
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
