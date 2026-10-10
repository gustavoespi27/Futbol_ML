"""Simulador: cualquier partido entre dos equipos de una liga con modelo, con cuotas opcionales del usuario."""

import numpy as np

from footy.web.services.betting import paper_bet
from footy.web.services.common import _f, _probs, public
from footy.web.services.context import predictor, sim_context, top_scores


def teams(code: str) -> list[dict]:
    """Equipos activos de la liga (jugaron el último año) con su id, para mostrar su escudo en el simulador."""
    p = predictor(code)
    active = set(p.recent_counts.index)
    return sorted(({"id": int(i), "name": n} for i, n in p.teams.items() if i in active), key=lambda t: t["name"])


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
