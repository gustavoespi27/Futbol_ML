"""Apuestas: semáforo del profesional, regla de seguimiento en papel, apuestas sugeridas y pronósticos fiables.

Las funciones reciben la lista de próximos partidos ya calculada (footy.web.services.context.upcoming): este módulo
no construye contextos, solo decide sobre ellos.
"""

import json

import numpy as np

from footy import config
from footy.betting import pro
from footy.db import repository as repo
from footy.db.connection import connect
from footy.evaluation import live
from footy.prediction import recalibration
from footy.web.services.common import _f


def pro_verdict(po: dict) -> dict:
    """Semáforo del apostador profesional para 1X2 (precio justo de Pinnacle vs la mejor cuota disponible)."""
    e = f"{po['edge'] * 100:+.1f}%".replace(".", ",")
    green = lambda r: {"level": "green", "label": "Apostar", "reason": r}  # noqa: E731
    red = lambda r: {"level": "red", "label": "No apostar", "reason": r}  # noqa: E731
    yellow = lambda r: {"level": "yellow", "label": "Neutral", "reason": r}  # noqa: E731
    if po["bet"]:
        return green(f"{po['book']} paga {e} sobre el precio justo de Pinnacle")
    if po["p_fair"] < 0.25 and po["edge"] < pro.MIN_EDGE:
        return red(f"Probabilidad baja ({po['p_fair']:.0%}) y sin valor ({e})")
    if po["edge"] >= pro.MIN_EDGE:
        return yellow(f"Valor {e} pero cuota > {pro.MAX_ODDS:g}: riesgo alto")
    if po["edge"] < -0.05:
        return red(f"La mejor cuota paga {e} respecto del precio justo")
    return yellow(f"Cerca del precio justo ({e}); falta ≥ +6%")


def paper_bet(params: dict, p, books: dict) -> dict:
    """Regla de seguimiento: EV > umbral de validación y cuota <= max_odds. Es seguimiento en papel, no consejo."""
    best = None
    for book, odds in books.items():
        ev = np.where(odds > params.get("max_odds", np.inf), -np.inf, np.asarray(p) * odds - 1)
        k = int(np.argmax(ev))
        if ev[k] > params["min_ev"] and (best is None or ev[k] > best["ev"]):
            best = {"bet": True, "sel": k, "book": book, "odds": _f(odds[k], 2), "ev": _f(ev[k])}
    if best:
        best["text"] = "Valor marginal según el modelo (solo seguimiento en papel; sin ventaja demostrada)."
        return best
    return {"bet": False, "text": "No apostar: ninguna cuota supera el umbral de valor."}


def candidates(matches: list[dict]) -> list[dict]:
    """Todas las selecciones con cuota de los partidos que aún no empiezan."""
    now = repo.utc_now()
    out = []
    for m in matches:
        if not m.get("options") or not m["ref"].startswith("m:") or (m.get("kickoff") or "") <= now:
            continue
        for o in m["options"]:
            if o.get("odds"):
                out.append({"match": int(m["ref"][2:]), "ref": m["ref"], "key": o["key"], "label": o["label"],
                            "p": o["p"], "odds": float(o["odds"]), "book": o["book"], "estimated": o["estimated"],
                            "fair": o["fair"], "verdict": o.get("verdict"), "home": m["home"], "away": m["away"],
                            "home_id": m.get("home_id"), "away_id": m.get("away_id"), "league": m["league"],
                            "league_name": m["league_name"],
                            "kickoff": m["kickoff"], "source": m["source"]})
    return out


def current_suggestions(matches: list[dict]) -> dict:
    """Apuestas del apostador profesional (footy.betting.pro) para los próximos partidos."""
    from footy.betting import suggestions as sg

    now = repo.utc_now()
    info = {m["ref"]: m for m in matches if m["ref"].startswith("m:") and (m.get("kickoff") or "") > now}
    opps = {int(ref[2:]): m.get("pro") or [] for ref, m in info.items()}
    labels = {"1": "Gana local", "X": "Empate", "2": "Gana visita"}
    enrich = lambda o: {**o, "p": o["p_fair"], "ev": o["edge"], "label": labels[o["key"]],  # noqa: E731
                        "ref": f"m:{o['match']}", **{k: info[f"m:{o['match']}"][k]
                                                     for k in ("home", "away", "league_name", "kickoff",
                                                               "home_id", "away_id", "league")}}
    singles = [{**s, "reason": pro.reason(s)} for s in (enrich(o) for o in pro.pick(opps))]
    near = [enrich({**o, "match": mid}) for mid, os_ in opps.items() for o in os_ if not o["bet"]
            and o["odds"] <= pro.MAX_ODDS and o["p_fair"] >= 0.25]
    closest_pro: dict = {}
    for c in sorted(near, key=lambda c: -c["edge"]):
        closest_pro.setdefault(c["match"], {**c, "verdict": pro_verdict(c),
                                            "min_odds": round((1 + pro.MIN_EDGE) / c["p_fair"], 2)})
    cands = candidates(matches)
    safest: dict = {}
    for c in cands:                                   # alta probabilidad (aunque el valor sea negativo)
        if not c["estimated"] and c["p"] >= 0.70 and c["odds"] >= 1.15:
            if c["match"] not in safest or c["p"] > safest[c["match"]]["p"]:
                safest[c["match"]] = {**c, "ev": c["p"] * c["odds"] - 1}
    doubles = sg.pick_doubles([{**s, "p": s["p_fair"]} for s in singles])
    for d in doubles:                    # en una doble el valor se multiplica pierna a pierna
        d["ev"] = float(np.prod([1 + leg["edge"] for leg in d["legs"]]) - 1)
        d["stake"] = min(pro.stake(d["p"], d["odds"]), pro.MAX_STAKE / 2)
    return {"rules": pro.RULES, "singles": singles, "doubles": doubles,
            "closest": list(closest_pro.values())[:6],
            "safest": sorted(safest.values(), key=lambda c: -c["p"])[:8],
            "n_matches_with_odds": len({c["match"] for c in cands}),
            "n_matches_sharp": sum(bool(v) for v in opps.values())}


def suggestions_data(matches: list[dict]) -> dict:
    from footy.prediction import pro_ledger

    path = config.path("processed") / "pro" / "backtest.json"
    bt = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return {**current_suggestions(matches), "history": live.combo_backtest().get("suggestions", {}),
            "pro_backtest": bt, "ledger": pro_ledger.record(connect())}


def reliable_data(matches: list[dict]) -> dict:
    """Pronósticos fiables de hoy, su historial de aciertos y el ajuste automático de probabilidades."""
    from footy.prediction import reliable

    return {"today": reliable.candidates(matches)[:30], "record": reliable.record(connect()),
            "calibration": recalibration.load(), "min_p": reliable.MIN_P}


def register_reliable(matches: list[dict], conn=None) -> dict:
    from footy.prediction import reliable

    return reliable.register(conn or connect(), reliable.candidates(matches))


def register_suggestions(matches: list[dict], conn=None) -> dict:
    """El apostador profesional coloca (en papel) sus apuestas antes del partido. Lo llama scripts/daily.py."""
    from footy.prediction import pro_ledger

    return pro_ledger.place(conn or connect(), current_suggestions(matches)["singles"])
