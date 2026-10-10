"""EXPERIMENTAL, sin uso en producción: registro de sugerencias simples y combinadas multiselección.

Prototipo de la regla de "apuestas sugeridas" según el modelo propio (footy.betting.suggestions, EV ≥ 3%), anterior
al apostador profesional. Guarda cada sugerencia una sola vez, antes del partido, en la tabla `suggestions` (una fila
por pierna; las piernas de una combinada comparten group_id) y la liquida cuando terminan todos sus partidos: gana si
se cumplen todas las selecciones y la cuota es el producto de las cuotas de las piernas.

Ni la tarea diaria ni el dashboard lo llaman: la cartera oficial es footy.prediction.pro_ledger (tabla `pro_bets`),
que solo apuesta 1X2 con valor frente al precio justo de Pinnacle y mide el CLV. Se conserva para poder seguir
combinadas del modelo propio si alguna vez se valida esa regla (en 2026 no mostró ventaja; ver docs/decisiones.md).
"""

import sqlite3

import numpy as np
import pandas as pd

from footy.db import repository as repo
from footy.markets import combos


def register(conn: sqlite3.Connection, singles: list[dict], doubles: list[dict], version: str) -> dict:
    """singles: dicts con match (match_id), key, p, odds, book, stake. doubles: dicts con legs y stake."""
    now = repo.utc_now()
    before = conn.total_changes
    rows = [(now, f"s:{s['match']}:{s['key']}", "simple", s["match"], s["key"], s["p"], s["odds"], s.get("book"),
             s["stake"], version) for s in singles]
    for d in doubles:
        gid = "d:" + "|".join(f"{leg['match']}:{leg['key']}" for leg in sorted(d["legs"], key=lambda x: x["match"]))
        rows += [(now, gid, "doble", leg["match"], leg["key"], leg["p"], leg["odds"], leg.get("book"), d["stake"],
                  version) for leg in d["legs"]]
    conn.executemany(
        """INSERT OR IGNORE INTO suggestions (created_at, group_id, kind, match_id, selection, p, odds, book, stake,
               model_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", rows)
    conn.commit()
    return {"suggestions": conn.total_changes - before}


def record(conn: sqlite3.Connection) -> dict:
    """Resultado de las sugerencias registradas: liquidadas, pendientes y rendimiento."""
    df = pd.read_sql_query(
        """SELECT s.*, m.status, m.home_goals, m.away_goals, m.kickoff_utc, th.name AS home, ta.name AS away
           FROM suggestions s JOIN matches m ON m.id = s.match_id
           JOIN teams th ON th.id = m.home_team_id JOIN teams ta ON ta.id = m.away_team_id""", conn)
    out = {"settled": 0, "pending": 0, "items": []}
    if df.empty:
        return out
    items = []
    for gid, g in df.groupby("group_id", sort=False):
        done = (g.status == "finished").all()
        void = g.status.isin(["cancelled", "postponed"]).any()
        hits = [combos.pattern_hits(int(r.home_goals), int(r.away_goals), [r.selection])
                for r in g.itertuples() if r.status == "finished"]
        odds = float(np.prod(g.odds))
        won = done and all(hits)
        items.append({
            "group": gid, "kind": g.kind.iloc[0], "created_at": g.created_at.min(), "kickoff": g.kickoff_utc.max(),
            "legs": [{"match": f"{r.home} vs {r.away}", "selection": combos.label([r.selection]), "odds": r.odds,
                      "score": f"{int(r.home_goals)}-{int(r.away_goals)}" if r.status == "finished" else None}
                     for r in g.itertuples()],
            "p": float(np.prod(g.p)), "odds": round(odds, 2), "stake": float(g.stake.iloc[0]),
            "status": "anulada" if void else ("ganada" if won else "perdida") if done else "pendiente",
            "profit": (odds - 1 if won else -1.0) if done and not void else None})
    it = pd.DataFrame(items)
    settled = it[it.status.isin(["ganada", "perdida"])]
    out.update({"settled": len(settled), "pending": int((it.status == "pendiente").sum()),
                "items": sorted(items, key=lambda x: x["kickoff"], reverse=True)[:60]})
    if len(settled):
        won = settled.status == "ganada"
        out.update({"won": int(won.sum()), "hit": round(float(won.mean()), 4),
                    "p_mean": round(float(settled.p.mean()), 4), "units": round(float(settled.profit.sum()), 2),
                    "yield": round(float(settled.profit.mean()), 4)})
    return out
