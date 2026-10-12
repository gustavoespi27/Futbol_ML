"""Simulador: un partido entre dos equipos de una liga con modelo, o entre clubes de ligas y países distintos
(modelo entre ligas), con cuotas opcionales del usuario."""

from datetime import datetime, timedelta, timezone

import numpy as np

from footy.betting.devig import proportional
from footy.db import repository as repo
from footy.db.connection import connect
from footy.leagues import load_params
from footy.web.services.betting import paper_bet
from footy.web.services.catalog import league_names
from footy.web.services.common import _f, _probs, public
from footy.web.services.context import cross_sim_context, predictor, sim_context, top_scores

OTHERS = "OTROS"            # clubes de ligas que no seguimos, conocidos por las copas internacionales
CLUB_CUPS = ("UCL", "UEL", "UECL", "LIB", "SUD")


def teams(code: str) -> list[dict]:
    """Equipos activos de la liga (jugaron el último año) con su id, para mostrar su escudo en el simulador. Ligas sin
    modelo propio y OTROS (clubes de ligas no seguidas que jugaron copas internacionales en los últimos 2 años) salen
    de la base: sirven para el simulador entre ligas."""
    if code in load_params():
        p = predictor(code)
        active = set(p.recent_counts.index)
        return sorted(({"id": int(i), "name": n} for i, n in p.teams.items() if i in active), key=lambda t: t["name"])
    now = datetime.now(timezone.utc)
    conn = connect()
    if code == OTHERS:
        rows = conn.execute(
            f"""SELECT DISTINCT t.id, t.name FROM teams t JOIN matches m ON t.id IN (m.home_team_id, m.away_team_id)
                JOIN competitions c ON c.id = m.competition_id
                WHERE t.country = 'unknown' AND c.code IN ({",".join("?" * len(CLUB_CUPS))}) AND m.kickoff_utc >= ?""",
            (*CLUB_CUPS, repo.to_iso(now - timedelta(days=730)))).fetchall()
    else:
        rows = conn.execute(
            """SELECT DISTINCT t.id, t.name FROM teams t JOIN matches m ON t.id IN (m.home_team_id, m.away_team_id)
               JOIN competitions c ON c.id = m.competition_id
               WHERE c.code = ? AND c.type = 'league' AND m.kickoff_utc >= ?""",
            (code, repo.to_iso(now - timedelta(days=365)))).fetchall()
    if not rows:
        raise KeyError(f"Sin equipos para {code}")
    return sorted(({"id": r[0], "name": r[1]} for r in rows), key=lambda t: t["name"])


def predict_cross(home_league: str, away_league: str, home_id: int, away_id: int,
                  odds: list[float] | None) -> dict:
    """Partido entre clubes de ligas (o países) distintos con el modelo entre ligas. Con cuotas, el valor esperado
    es orientativo: no hay pesos validados para combinar este modelo con el mercado."""
    from footy.models import cross_league

    full = cross_sim_context(home_league, away_league, home_id, away_id)
    ctx = public(full)
    model = cross_league.load()
    names = league_names() | {OTHERS: "Otras ligas"}
    conn = connect()
    since = repo.to_iso(datetime.now(timezone.utc) - timedelta(days=365))
    played = [conn.execute("SELECT COUNT(*) FROM matches WHERE status = 'finished' AND kickoff_utc >= ? "
                           "AND ? IN (home_team_id, away_team_id)", (since, t)).fetchone()[0]
              for t in (home_id, away_id)]
    off = {s: round(model.offsets.get(model.league_of.get(t, cross_league.OTHER), 0.0))
           for s, t in (("home", home_id), ("away", away_id))}
    p = np.array(ctx["p_official"])
    out = {"league": home_league, "league_name": f"{names.get(home_league, home_league)} vs "
                                                  f"{names.get(away_league, away_league)}",
           "home": ctx["home"], "away": ctx["away"], "home_id": home_id, "away_id": away_id,
           "p_model": ctx["p_model"], "xg": ctx["xg"], "source": "modelo entre ligas", "p_official": ctx["p_official"],
           "btts": ctx["btts"],
           "over_under": {o["key"][1:]: o["p"] for o in ctx["options"] if o["key"].startswith("O")},
           "top_scores": top_scores(full["_M"], 5), "options": ctx["options"], "suggestions": ctx["suggestions"],
           "ref": ctx["ref"],
           "cross": {"home_offset": off["home"], "away_offset": off["away"], "n_cups": model.n_train},
           "confidence": {"level": "alta" if min(played) >= 20 else "media" if min(played) >= 8 else "baja",
                          "min_recent_matches": int(min(played)), "elo_dc_max_diff": None}}
    if odds:
        o = np.array(odds, dtype=float)
        ev = p * o - 1
        k = int(np.argmax(ev))
        out["betting"] = {"odds": list(odds), "margin": _f(float(np.sum(1 / o)) - 1),
                          "p_market": _probs(proportional(o[None, :])[0]), "ev": _probs(ev), "min_ev": None}
        out["recommendation"] = {"bet": False, "text": (
            f"Mayor valor según el modelo: {'local empate visita'.split()[k]} ({ev[k]:+.1%}). Orientativo: el modelo "
            "entre ligas no tiene pesos validados frente al mercado, así que no se recomienda apostar.")}
    return out


def predict(code: str, home: str, away: str, odds: list[float] | None) -> dict:
    p = predictor(code)
    h, a = p.find_team(home), p.find_team(away)
    r = p.predict(h, a, tuple(odds) if odds else None)
    m = r["markets"]
    full = sim_context(code, h.name, a.name, odds)
    ctx = public(full)
    out = {"league": code, "league_name": r["league_name"], "home": h.name, "away": a.name,
           "home_id": h.id, "away_id": a.id,
           "p_model": _probs(r["p_model"]), "p_elo": _probs(r["p_elo"]), "p_dc": _probs(r["p_dc"]),
           "xg": [_f(m["xg_home"], 2), _f(m["xg_away"], 2)], "confidence": r["confidence"], "status": r["status"],
           "source": ctx["source"], "p_official": ctx["p_official"], "btts": ctx["btts"],
           "over_under": {o["key"][1:]: o["p"] for o in ctx["options"] if o["key"].startswith("O")},
           "top_scores": top_scores(full["_M"], 5),
           "options": ctx["options"], "suggestions": ctx["suggestions"], "ref": ctx["ref"]}
    if odds:
        b = r["betting"]
        out["betting"] = {"odds": list(odds), "margin": _f(b["margin"]), "p_market": _probs(b["p_market_fair"]),
                          "ev": _probs(np.array(ctx["p_official"]) * np.array(odds) - 1), "min_ev": b["min_ev"]}
        out["recommendation"] = paper_bet(p.params, np.array(ctx["p_official"]),
                                          {"Tu casa": np.array(odds, dtype=float)})
    return out
