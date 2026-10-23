"""Servicio de feed personalizado determinista.

Filtra, califica y ordena los partidos y oportunidades según las preferencias del usuario.
No utiliza LLM (0 costo de tokens, ejecución instantánea y 100% testeable).
El perfil de riesgo solo cambia el orden del feed: el stake sigue siendo 1/4 Kelly con topes 2%/10% (betting.pro).
"""

import logging
import sqlite3
import unicodedata

from footy.db.repository import utc_now
from footy.web import service
from footy_agents.preferences import repo
from footy_agents.schemas import FeedItem, PersonalizedFeedResponse

log = logging.getLogger(__name__)

# peso de la ventaja (edge) en el puntaje según el perfil: (bono fijo, multiplicador del edge)
EDGE_WEIGHTS = {"conservative": (15.0, 50.0), "moderate": (20.0, 100.0), "aggressive": (25.0, 150.0)}


def _normalize_name(name: str) -> str:
    """Minúsculas, sin acentos ni puntuación: 'Ñublense' = 'nublense' y 'Colo-Colo' = 'Colo Colo'."""
    text = unicodedata.normalize("NFKD", name.lower())
    text = "".join(c if c.isalnum() else " " for c in text if not unicodedata.combining(c))
    return " ".join(text.split())


def _value_bets_by_match(matches: list[dict]) -> dict[int, list[dict]]:
    """Apuestas del apostador profesional agrupadas por partido. Si el motor falla, el feed sigue sin ellas."""
    try:
        singles = service.current_suggestions(matches).get("singles", [])
    except Exception as exc:  # noqa: BLE001 - el feed se degrada a solo preferencias en vez de caer
        log.warning("Feed sin apuestas de valor: %s", exc)
        return {}
    out: dict[int, list[dict]] = {}
    for s in singles:
        out.setdefault(s["match"], []).append(s)
    return out


def get_personalized_feed(conn: sqlite3.Connection, user_id: str = "default") -> PersonalizedFeedResponse:
    """Genera el feed ordenado por relevancia personalizada para el usuario."""
    prefs = repo.get_preferences(conn, user_id=user_id)
    raw_matches = service.upcoming()

    fav_teams = {_normalize_name(t) for t in prefs.favorite_teams}
    fav_leagues = set(prefs.favorite_leagues)
    value_bets = _value_bets_by_match(raw_matches)
    edge_bonus, edge_mult = EDGE_WEIGHTS[prefs.risk_profile]

    feed_items: list[FeedItem] = []
    for m in raw_matches:
        ref = m.get("ref", "")
        if not ref.startswith("m:"):
            continue
        match_id = int(ref[2:])
        home, away, league = m.get("home", ""), m.get("away", ""), m.get("league", "")

        # coincidencia exacta del nombre normalizado: una subcadena haría que "Universidad" marque a varios clubes
        is_fav_team = bool(fav_teams & {_normalize_name(home), _normalize_name(away)})
        is_fav_league = league in fav_leagues

        v_bets = value_bets.get(match_id, [])
        best_edge = max((b["edge"] for b in v_bets), default=None)

        score = 10.0 + 50.0 * is_fav_team + 25.0 * is_fav_league
        if best_edge is not None and best_edge > 0:
            score += edge_bonus + best_edge * edge_mult

        feed_items.append(FeedItem(
            match_id=match_id,
            home_team=home,
            away_team=away,
            league=league,
            league_name=m.get("league_name") or league,
            kickoff=m.get("kickoff") or "",
            is_favorite_team=is_fav_team,
            is_favorite_league=is_fav_league,
            value_bets_count=len(v_bets),
            best_edge=best_edge,
            relevance_score=round(score, 2),
        ))

    # Ordenar por puntaje descendente; en empate, por fecha de kickoff ascendente
    feed_items.sort(key=lambda item: (-item.relevance_score, item.kickoff))
    return PersonalizedFeedResponse(
        items=feed_items,
        generated_at=utc_now(),
        risk_profile=prefs.risk_profile,
        total_matches=len(feed_items),
        favorite_matches_count=sum(item.is_favorite_team for item in feed_items),
    )
