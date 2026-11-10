"""Herramientas (tools) tipadas para el agente y orquestador LLM.

Envuelven los servicios existentes en footy.web.service sin modificarlos ni romperlos.
Cada herramienta devuelve un payload condensado y seguro para el contexto del LLM.
"""

import time
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from difflib import get_close_matches
from math import floor
from typing import Any

from pydantic import ValidationError

from footy.betting import pro
from footy.db.connection import connect
from footy.leagues import load_params
from footy.web import service
from footy.web.services.context import LOCAL_TZ
from footy_agents.names import normalize_name
from footy_agents.schemas import ToolCallRecord
from footy_agents.tool_args import OPENAI_TOOLS_SPEC, TOOL_MODELS  # noqa: F401 - fachada pública

MAX_MATCHES = 20
MAX_TEAMS = 5


def kickoff_local(kickoff: str | None) -> str | None:
    """Fecha local calculada con zona IANA y días españoles independientes del locale de Windows."""
    if not kickoff:
        return None
    value = datetime.fromisoformat(kickoff.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("El kickoff debe incluir zona horaria")
    local = value.astimezone(LOCAL_TZ)
    day = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")[local.weekday()]
    return f"{day} {local:%d-%m}, {local:%H:%M} hora de Chile"

# Apodos frecuentes en Chile -> nombre canónico de la base (una consulta informal no debe terminar en «no encontrado»).
NICKNAMES = {
    "la roja": "Chile", "roja": "Chile", "seleccion chilena": "Chile", "la seleccion": "Chile",
    "albiceleste": "Argentina", "la albiceleste": "Argentina", "la celeste": "Uruguay", "la tri": "Ecuador",
    "la verde": "Bolivia", "la vinotinto": "Venezuela", "la blanquirroja": "Peru", "la bicolor": "Peru",
    "la albirroja": "Paraguay", "el tri": "Mexico", "la canarinha": "Brazil", "la verdeamarela": "Brazil",
    "los cafeteros": "Colombia", "el colo": "Colo Colo", "el cacique": "Colo Colo", "el popular": "Colo Colo",
    "la u": "Universidad de Chile", "los azules": "Universidad de Chile", "la uc": "U. Catolica",
    "los cruzados": "U. Catolica", "la catolica": "U. Catolica",
}
STANDING_KEYS = ("pos", "teams", "points", "played", "won", "drawn", "lost", "gf", "ga")
STALE_HOURS = 30            # mismo umbral que la franja de estado del dashboard


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
    for nickname, canonical in NICKNAMES.items():
        core = nickname.split(" ", 1)[-1]       # «del cacique»: el apodo sin artículo también cuenta si es largo
        if canonical in teams and (f" {nickname} " in f" {query} " or (len(core) >= 5 and f" {core} " in f" {query} ")):
            return {"team": canonical, "limit": MAX_MATCHES}
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


def labeled_1x2(home: str, away: str, p) -> dict[str, Any] | None:
    """Probabilidades con el nombre de cada equipo y el favorito resuelto: el modelo no debe cruzar local y visita."""
    if not p:
        return None
    ranked = sorted(zip((home, "empate", away), p), key=lambda kv: kv[1], reverse=True)
    favorite = ranked[0][0] if ranked[0][0] != "empate" else "ninguno (el empate es lo más probable)"
    return {"home_team": home, "home_win": _pct(p[0]), "draw": _pct(p[1]), "away_team": away, "away_win": _pct(p[2]),
            "summary": f"{home} {_pct(p[0])} · empate {_pct(p[1])} · {away} {_pct(p[2])}", "favorite": favorite}


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

    def probs(m: dict) -> dict[str, Any] | None:
        return labeled_1x2(m.get("home", ""), m.get("away", ""), m.get("p_official"))

    return [{
        "match_id": int(m["ref"][2:]) if m.get("ref", "").startswith("m:") else None,
        "league": m.get("league"),
        "league_name": m.get("league_name"),
        "kickoff": m.get("kickoff"),
        "kickoff_local": kickoff_local(m.get("kickoff")),
        "home": m.get("home"),
        "away": m.get("away"),
        "probabilities_1x2": probs(m),
        "probability_source": m.get("source"),
        "model_name": m.get("model_name"),
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


def _league_team(code: str, name: str) -> dict:
    """Equipo activo de la liga por nombre canónico, apodo o coincidencia parcial única."""
    roster = service.teams(code)
    query = normalize_name(NICKNAMES.get(normalize_name(name), name))
    by_name = {normalize_name(t["name"]): t for t in roster}
    if query in by_name:
        return by_name[query]
    partial = [t for key, t in by_name.items() if query in key or key in query]
    partial = partial or [by_name[k] for k in get_close_matches(query, list(by_name), n=1, cutoff=.75)]
    if len(partial) != 1:
        raise KeyError(f"Equipo '{name}' no encontrado en {code}")
    return partial[0]


def tool_simulate_match(league: str, home_team: str, away_team: str) -> dict[str, Any]:
    """Simula un partido entre dos equipos de una liga con el modelo del sistema (xG y probabilidades 1X2). Las ligas
    sin modelo propio (p. ej. Chile) usan el modelo entre ligas, igual que el simulador del dashboard."""
    code = resolve_league(league)
    home, away = _league_team(code, home_team), _league_team(code, away_team)
    if code in load_params():
        res = service.predict(code, home["name"], away["name"], None)
    else:
        res = service.predict_cross(code, code, home["id"], away["id"], None)
    p_home, p_draw, p_away = res["p_model"]
    return {
        "home": res["home"],
        "away": res["away"],
        "league": code,
        "model": res.get("source"),
        "expected_goals": {"home": res["xg"][0], "away": res["xg"][1]},
        "probabilities_1x2": labeled_1x2(res["home"], res["away"], (p_home, p_draw, p_away)),
        "top_scores": [{"score": s, "probability": _pct(q)} for s, q in res.get("top_scores", [])[:3]],
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


def performance_assessment(tracking: dict[str, Any]) -> str:
    """Interpreta métricas disponibles sin atribuir al mercado una tasa de acierto inexistente."""
    parts = []
    clv = tracking.get("bets_clv")
    if clv is None:
        parts.append("CLV: sin datos disponibles.")
    elif clv < 0:
        parts.append(f"CLV {_pct(clv)}: las apuestas se tomaron a peor precio que el cierre; señal desfavorable.")
    elif clv > 0:
        parts.append(f"CLV {_pct(clv)}: las apuestas se tomaron a mejor precio que el cierre; señal favorable.")
    else:
        parts.append("CLV 0 %: sin diferencia media frente al precio de cierre; señal neutra.")
    yield_ = tracking.get("bets_yield")
    parts.append("Yield: sin datos disponibles." if yield_ is None else
                 f"Yield {_pct(yield_)}: {'pérdida' if yield_ < 0 else 'ganancia' if yield_ > 0 else 'equilibrio'} "
                 "por unidad apostada en el seguimiento en papel.")
    hit = tracking.get("hit_rate")
    parts.append("Aciertos 1X2: sin datos disponibles." if hit is None else
                 f"Aciertos 1X2: {_pct(hit)} de los pronósticos evaluados; no es rentabilidad de apuestas.")
    parts.append("No hay una tasa de acierto 1X2 del mercado en esta herramienta; no se puede comparar ese porcentaje.")
    official, market = tracking.get("ll_official"), tracking.get("ll_market")
    if official is None or market is None:
        parts.append("Log loss: faltan datos para comparar el pronóstico oficial con el mercado.")
    else:
        best = "el mercado es mejor" if market < official else (
            "el pronóstico oficial es mejor" if official < market else "ambos son iguales")
        parts.append(f"Log loss oficial {official:.4f} frente a mercado {market:.4f}: menor es mejor; {best} "
                     "en estas medias publicadas. La comparación no demuestra superioridad estadística "
                     "ni garantiza muestras idénticas.")
    return " ".join(parts)


def tool_get_system_performance() -> dict[str, Any]:
    """Rendimiento real del sistema: seguimiento en vivo (aciertos, log loss, apuestas en papel) y motor vigente."""
    ov = service.overview()
    tracking = dict(ov.get("tracking") or {})
    assessment = performance_assessment(tracking)
    for key in ("hit_rate", "bets_yield", "bets_clv"):     # fracciones -> porcentaje listo para citar
        if tracking.get(key) is not None:
            tracking[key] = _pct(tracking[key])
    return {
        "model_version": ov.get("model_version"),
        "tracking": tracking,
        "assessment": assessment,
        "engine": ov.get("engine"),
        "last_daily_run": ov.get("last_daily_run"),
        "glossary": {
            "hit_rate": "porcentaje de pronósticos 1X2 acertados en partidos ya jugados (no son apuestas)",
            "evaluated": "partidos con pronóstico ya evaluados", "paper_bets": "apuestas en papel registradas",
            "bets_yield": "ganancia o pérdida por unidad apostada en las apuestas en papel",
            "bets_clv": "valor de la línea de cierre promedio: positivo significa que se ganó al precio de cierre",
            "ll_official": "log loss del pronóstico oficial (menor es mejor); ll_market es el del mercado",
            "model_version": "versión del motor estadístico (Elo + Dixon-Coles)",
        },
    }


def _kickoff(m: dict) -> datetime:
    return datetime.fromisoformat(str(m["kickoff"]).replace("Z", "+00:00"))


def _match_id(m: dict) -> int | None:
    ref = m.get("ref") or ""
    return int(ref[2:]) if ref.startswith("m:") else None


def _value_status(m: dict) -> str:
    if not m.get("pro"):
        return "sin_precio_pinnacle"
    return "con_ventaja" if any(o.get("bet") for o in m["pro"]) else "sin_ventaja"


def tool_find_team(name: str) -> list[dict[str, Any]]:
    """Resuelve un nombre informal a equipos canónicos: primero los que juegan pronto, luego el resto de la base."""
    query = normalize_name(name)
    query = normalize_name(NICKNAMES.get(query, NICKNAMES.get(query.removeprefix("la ").strip(), name)))
    upcoming = sorted(service.upcoming(), key=_kickoff)
    next_match: dict[str, dict] = {}
    for m in upcoming:
        for side in ("home", "away"):
            next_match.setdefault(m[side], m)
    with closing(connect()) as conn:
        known = [row[0] for row in conn.execute("SELECT name FROM teams")]
    names = list(dict.fromkeys([*next_match, *known]))
    normalized = {normalize_name(n): n for n in names}
    hits = [n for key, n in normalized.items() if key == query]
    hits += [n for key, n in normalized.items() if query in key.split() or (len(query) >= 4 and query in key)]
    hits += [normalized[key] for key in get_close_matches(query, list(normalized), n=5, cutoff=.75)]
    hits = sorted(dict.fromkeys(hits), key=lambda n: (normalize_name(n) != query, n not in next_match))[:MAX_TEAMS]
    out = []
    for team in hits:
        m = next_match.get(team)
        out.append({"team": team, "exact": normalize_name(team) == query,
                    "next_match": None if m is None else {
                        "match_id": _match_id(m), "league": m.get("league"), "league_name": m.get("league_name"),
                        "kickoff": m.get("kickoff"), "kickoff_local": kickoff_local(m.get("kickoff")),
                        "home": m.get("home"), "away": m.get("away"),
                        "probabilities_1x2": labeled_1x2(m.get("home", ""), m.get("away", ""), m.get("p_official"))}})
    return out


def tool_analyze_match(match_id: int) -> dict[str, Any]:
    """Análisis de un partido del calendario: probabilidades, goles esperados, marcadores y ventaja vs Pinnacle."""
    m = next((m for m in service.upcoming() if _match_id(m) == match_id), None)
    if m is None:
        raise ValueError(f"El partido {match_id} no está en el calendario próximo")
    started = _kickoff(m) <= datetime.now(timezone.utc)
    p, xg = m.get("p_official"), m.get("xg") or [None, None]
    value = [{"selection": {"1": m["home"], "X": "Empate", "2": m["away"]}.get(o["key"], o["key"]),
              "best_odds": round(o["odds"], 2), "bookmaker": o.get("book"),
              "pinnacle_fair_odds": round(o["fair_odds"], 2),
              "edge": _pct(o["edge"])} for o in m.get("pro") or [] if o.get("bet")]
    return {
        "match_id": match_id, "status": "started" if started else "ok" if m.get("pro") else "no_pinnacle",
        "league": m.get("league"), "league_name": m.get("league_name"), "kickoff": m.get("kickoff"),
        "kickoff_local": kickoff_local(m.get("kickoff")),
        "home": m.get("home"), "away": m.get("away"),
        "probability_source": m.get("source"), "model_name": m.get("model_name"),
        "probabilities_1x2": labeled_1x2(m.get("home", ""), m.get("away", ""), p),
        "expected_goals": {"home": xg[0], "away": xg[1]},
        "over_2_5": _pct(m.get("over25")), "both_teams_score": _pct(m.get("btts")),
        "top_scores": [{"score": s, "probability": _pct(q)} for s, q in (m.get("top_scores") or [])[:3]],
        "has_pinnacle_price": bool(m.get("pro")), "value_status": _value_status(m), "value_selections": value,
    }


def tool_get_coverage() -> dict[str, Any]:
    """Frescura de los datos y cobertura de Pinnacle del calendario: explica por qué hay o no recomendaciones."""
    matches = service.upcoming()
    last = service.overview().get("last_daily_run")
    hours = None
    if last:
        hours = round((datetime.now(timezone.utc) - datetime.fromisoformat(last.replace("Z", "+00:00")))
                      .total_seconds() / 3600, 1)
    priced = sorted((m for m in matches if m.get("pro")), key=_kickoff)
    first = priced[0] if priced else None
    return {
        "last_update": last, "hours_since_update": hours, "stale": hours is None or hours >= STALE_HOURS,
        "freshness": "sin registro de actualización" if hours is None else
                     "actualizado hace menos de una hora" if hours < 1 else f"actualizado hace {floor(hours)} horas",
        "upcoming_matches": len(matches), "with_pinnacle_price": len(priced),
        "without_pinnacle_price": len(matches) - len(priced),
        "by_probability_source": dict(Counter(m.get("source") or "sin_fuente" for m in matches)),
        "next_with_pinnacle": None if first is None else {
            "match_id": _match_id(first), "home": first["home"], "away": first["away"], "kickoff": first["kickoff"]},
        "rule": "Solo hay ventaja evaluable frente al precio justo de Pinnacle; sin ese precio no se recomienda "
                "apostar.",
    }


def tool_get_team_form(team: str) -> dict[str, Any]:
    """Cómo llega un equipo: posición en la tabla, últimos resultados, promedios de la temporada y próximo partido."""
    query = normalize_name(NICKNAMES.get(normalize_name(team), team))
    with closing(connect()) as conn:
        rows = [(r[0], r[1]) for r in conn.execute("SELECT id, name FROM teams")]
    exact = [tid for tid, name in rows if normalize_name(name) == query]
    if not exact:
        raise ValueError(f"Equipo no encontrado: {team}. Usa find_team para obtener el nombre exacto")
    profile = service.team_profile(exact[0])
    if not profile:
        raise ValueError(f"Sin ficha disponible para {team}")
    letters = {"W": "G", "D": "E", "L": "P"}
    recent = profile.get("recent") or []
    last = recent[-5:]
    counts = {key: sum(r["outcome"] == outcome for r in last)
              for key, outcome in (("won", "W"), ("drawn", "D"), ("lost", "L"))}
    form = "".join(letters.get(r["outcome"], "?") for r in last)
    form_text = (f"En sus últimos {len(last)} partidos ganó {counts['won']}, empató {counts['drawn']} "
                 f"y perdió {counts['lost']} ({form}, más antiguo a la izquierda)." if last
                 else "No hay partidos recientes disponibles para evaluar su forma.")
    standing, season = profile.get("standing"), profile.get("season")
    return {
        "team": profile["name"], "league_name": profile.get("league_name"),
        "standing": None if not standing else {k: standing[k] for k in STANDING_KEYS},
        "form_last5": form, "last5_counts": counts, "form_text": form_text,
        "last_results": [{"date": r["date"][:10], "opponent": r["opponent"], "home": r["is_home"],
                          "score": f"{r['score'][0]}-{r['score'][1]}", "result": letters.get(r["outcome"], "?"),
                          "competition": r.get("league_name")} for r in recent[-5:]],
        "season_averages": None if not season else {"goals_for_per_game": season.get("gf_pg"),
                                                    "goals_against_per_game": season.get("ga_pg"),
                                                    "matches": season.get("played")},
        "next_matches": [{"opponent": u.get("opponent"), "kickoff": u.get("kickoff") or u.get("date")}
                         for u in (profile.get("upcoming") or [])[:2]],
        "form_legend": "G = ganó, E = empató, P = perdió (más antiguo a la izquierda)",
    }


def tool_get_stake_limits(bankroll: float) -> dict[str, Any]:
    """Topes enteros CLP redondeados hacia abajo: no equivale a recomendar ese monto."""
    single, daily = floor(bankroll * pro.MAX_STAKE), floor(bankroll * pro.MAX_DAILY)
    clp = lambda value: "$" + f"{value:,}".replace(",", ".")  # noqa: E731
    return {"bankroll": bankroll, "bankroll_clp": clp(floor(bankroll)), "max_per_bet": single, "max_daily": daily,
            "max_per_bet_clp": clp(single), "max_daily_clp": clp(daily),
            "kelly_fraction": pro.KELLY_FRACTION, "max_stake_fraction": pro.MAX_STAKE,
            "max_daily_fraction": pro.MAX_DAILY,
            "limits_text": f"Tope por apuesta: {clp(single)} ({pro.MAX_STAKE * 100:g} % de la banca). "
                           f"Tope diario: {clp(daily)} ({pro.MAX_DAILY * 100:g} % de la banca). "
                           "Son topes, no una apuesta sugerida.",
            "note": "Son topes de exposición, no una apuesta sugerida. El monto depende del precio justo de Pinnacle."}


TOOLS_REGISTRY: dict[str, Any] = {
    "get_upcoming_matches": tool_get_upcoming_matches,
    "get_value_bets": tool_get_value_bets,
    "simulate_match": tool_simulate_match,
    "get_league_standings": tool_get_league_standings,
    "get_system_performance": tool_get_system_performance,
    "get_stake_limits": tool_get_stake_limits,
    "find_team": tool_find_team,
    "analyze_match": tool_analyze_match,
    "get_coverage": tool_get_coverage,
    "get_team_form": tool_get_team_form,
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

