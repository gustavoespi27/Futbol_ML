"""Combinadas: probabilidad conjunta, cuota justa y de la casa de un boleto, e histórico 2026."""

from footy.evaluation import live
from footy.markets import combos
from footy.web.services.common import _f
from footy.web.services.context import context


def combo(legs: list[dict], group_odds: dict | None = None) -> dict:
    """legs: [{"ref", "key", "odds"?}]. Selecciones del mismo partido se evalúan juntas (probabilidad conjunta
    exacta); partidos distintos se multiplican. group_odds: cuota que ofrece la casa para una variante de un
    mismo partido ({ref: cuota}), porque las casas no la calculan como producto."""
    group_odds = group_odds or {}
    by_ref: dict[str, list[dict]] = {}
    for leg in legs:
        if leg["key"] not in combos.SELECTIONS:
            raise KeyError(f"Selección desconocida: {leg['key']}")
        by_ref.setdefault(leg["ref"], []).append(leg)
    groups, p_total, book_total, fair_total = [], 1.0, 1.0, 1.0
    for ref, gl in by_ref.items():
        ctx = context(ref)
        if "_M" not in ctx:
            raise KeyError(f"{ctx['home']} vs {ctx['away']}: sin probabilidades disponibles")
        keys = list(dict.fromkeys(leg["key"] for leg in gl))
        p = combos.prob(ctx["_M"], keys)
        opt = {o["key"]: o for o in ctx["options"]}
        if len(keys) == 1:
            user = gl[0].get("odds")
            book = user or opt[keys[0]]["odds"]
            book_src = "tuya" if user else opt[keys[0]]["book"]
        else:
            book = group_odds.get(ref)
            book_src = "tuya" if book else None
        groups.append({"ref": ref, "match": f"{ctx['home']} vs {ctx['away']}", "league_name": ctx["league_name"],
                       "league": ctx["league"], "home_id": ctx.get("home_id"), "away_id": ctx.get("away_id"),
                       "kickoff": ctx.get("kickoff"), "keys": keys, "label": combos.label(keys), "p": _f(p),
                       "fair": _f(1 / p, 2) if p > 0 else None, "odds": _f(book, 2), "odds_source": book_src,
                       "impossible": p == 0, "same_match": len(keys) > 1,
                       "items": [{"key": k, "label": combos.SELECTIONS[k][0], "p": _f(combos.prob(ctx["_M"], [k])),
                                  "odds": opt[k]["odds"], "book": opt[k]["book"]} for k in keys]})
        p_total *= p
        fair_total = fair_total * (1 / p) if p > 0 else None
        book_total = book_total * book if (book_total is not None and book) else None
    n = len(groups)
    hist = next((r for r in live.combo_backtest()["strategies"]["probables"] if r["legs"] == n), None) if n else None
    return {"groups": groups, "legs": n, "p": _f(p_total), "fair_odds": _f(fair_total, 2) if fair_total else None,
            "book_odds": _f(book_total, 2) if (n and book_total) else None,
            "ev": _f(p_total * book_total - 1) if (n and book_total) else None, "history": hist}


def combo_history() -> dict:
    return live.combo_backtest()
