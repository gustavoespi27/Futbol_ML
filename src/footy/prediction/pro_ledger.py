"""Cartera del apostador profesional: registra sus apuestas antes del partido, las liquida y mide el CLV.

Es dinero simulado: bankroll inicial 100 unidades; cada apuesta usa la fracción (¼ Kelly con topes) del bankroll
disponible al momento de liquidarla, en orden de kickoff.
"""

import sqlite3

import numpy as np
import pandas as pd

from footy.betting import pro
from footy.db import repository as repo

START_BANK = 100.0


def place(conn: sqlite3.Connection, picks: list[dict]) -> dict:
    """picks: salida de pro.pick con match = match_id (int). Solo partidos que aún no empiezan; una vez por partido."""
    now = repo.utc_now()
    before = conn.total_changes
    for p in picks:
        k = conn.execute("SELECT kickoff_utc FROM matches WHERE id = ?", (p["match"],)).fetchone()
        if k is None or k[0] <= now:
            continue
        conn.execute(
            """INSERT OR IGNORE INTO pro_bets (created_at, match_id, selection, book, odds, p_fair, pinnacle_odds,
                   edge, stake) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (now, p["match"], p["sel"], p["book"], p["odds"], p["p_fair"], p["pinnacle"], p["edge"], p["stake"]))
    conn.commit()
    return {"pro_bets": conn.total_changes - before}


def _closing(conn, match_id: int, kickoff: str) -> dict | None:
    """Pinnacle 1X2 al cierre: cuota de cierre si existe; si no, el último snapshot antes del kickoff."""
    rows = conn.execute(
        """SELECT selection, price, is_closing, captured_at FROM odds
           WHERE match_id = ? AND bookmaker = 'Pinnacle' AND market = '1X2'
             AND (is_closing = 1 OR captured_at < ?)""", (match_id, kickoff)).fetchall()
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["sel", "price", "is_closing", "captured_at"])
    df = df.sort_values(["is_closing", "captured_at"]).groupby("sel").tail(1)
    d = dict(zip(df.sel, df.price))
    return {"Pinnacle": d} if all(s in d for s in pro.SEL) else None


def record(conn: sqlite3.Connection) -> dict:
    df = pd.read_sql_query(
        """SELECT b.*, m.kickoff_utc, m.status, m.home_goals, m.away_goals, c.code AS league,
                  m.home_team_id AS home_id, m.away_team_id AS away_id,
                  th.name AS home, ta.name AS away
           FROM pro_bets b JOIN matches m ON m.id = b.match_id JOIN competitions c ON c.id = m.competition_id
           JOIN teams th ON th.id = m.home_team_id JOIN teams ta ON ta.id = m.away_team_id
           ORDER BY m.kickoff_utc""", conn)
    out = {"start": START_BANK, "bank": START_BANK, "settled": 0, "open": 0, "items": []}
    if df.empty:
        return out
    bank, items, settled = START_BANK, [], []
    for r in df.itertuples():
        item = {"match_id": r.match_id, "partido": f"{r.home} vs {r.away}", "league": r.league,
                "home": r.home, "away": r.away, "home_id": int(r.home_id), "away_id": int(r.away_id),
                "kickoff": r.kickoff_utc,
                "sel": r.selection, "book": r.book, "odds": r.odds, "p_fair": r.p_fair, "edge": r.edge,
                "stake": r.stake, "created_at": r.created_at, "status": "abierta", "profit": None, "clv": None}
        item["reason"] = pro.reason({"sel": r.selection, "book": r.book, "odds": r.odds, "p_fair": r.p_fair,
                                     "edge": r.edge, "stake": r.stake})
        close = _closing(conn, r.match_id, r.kickoff_utc)
        if close:
            item["clv"] = pro.clv(r.odds, close, r.selection)
        if r.status == "finished":
            res = "H" if r.home_goals > r.away_goals else "D" if r.home_goals == r.away_goals else "A"
            won = res == r.selection
            amount = bank * r.stake
            profit = amount * (r.odds - 1) if won else -amount
            bank += profit
            item.update({"status": "ganada" if won else "perdida", "score": f"{r.home_goals}-{r.away_goals}",
                         "amount": amount, "profit": profit, "units": (r.odds - 1) if won else -1.0, "bank": bank})
            settled.append(item)
        elif r.status in ("cancelled", "postponed"):
            item["status"] = "anulada"
        else:
            item["amount"] = bank * r.stake
        items.append(item)
    clvs = [i["clv"] for i in items if i["clv"] is not None and i["kickoff"] <= repo.utc_now()]
    out.update({"bank": round(bank, 2), "settled": len(settled), "open": sum(i["status"] == "abierta" for i in items),
                "items": items[::-1][:80]})
    if settled:
        u = np.array([i["units"] for i in settled])
        out.update({"won": int(sum(i["status"] == "ganada" for i in settled)), "yield": round(float(u.mean()), 4),
                    "roi_bank": round(bank / START_BANK - 1, 4)})
    if clvs:
        out.update({"clv": round(float(np.mean(clvs)), 4), "clv_pos": round(float(np.mean(np.array(clvs) > 0)), 4),
                    "clv_n": len(clvs)})
    return out
