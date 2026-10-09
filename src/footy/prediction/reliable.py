"""Pronósticos fiables del día: la máquina prueba a diario su precisión.

Cada día, para los partidos de las próximas horas, elige en cada partido la selección más probable entre mercados
simples (1X2, más/menos 2,5, ambos marcan) si su probabilidad es >= MIN_P, y la registra ANTES del
partido con el motivo (tabla `daily_picks`). Al terminar el partido se liquida: así se mide de forma continua si
"cuando el sistema dice 75%, ocurre 75%". Con esos resultados `footy.prediction.recalibration` ajusta las
probabilidades poco a poco.

No es una recomendación de apuesta: una selección muy probable suele pagar poco (ver apostador profesional).
"""

import sqlite3

import numpy as np
import pandas as pd

from footy.db import repository as repo
from footy.markets import combos

MIN_P = 0.65
MAX_PER_DAY = 20
MARKETS = ("1", "X", "2", "O2.5", "U2.5", "BTTS_Y", "BTTS_N")   # sin doble oportunidad: casi siempre acierta
MARKET_NAME = {"1": "1X2", "X": "1X2", "2": "1X2", "1X": "Doble oportunidad", "X2": "Doble oportunidad",
               "O2.5": "Goles", "U2.5": "Goles", "BTTS_Y": "Ambos marcan", "BTTS_N": "Ambos marcan"}


def reason(ctx: dict, opt: dict) -> str:
    """Explicación breve de por qué el sistema confía en esta selección."""
    parts = [f"{opt['p']:.0%} según {ctx.get('source', 'el sistema')}"]
    pm = ctx.get("p_market")
    if pm and opt["key"] in ("1", "X", "2"):
        parts.append(f"el mercado le da {pm['1X2'.index(opt['key'])]:.0%}")
    f = ctx.get("form") or {}
    if f.get("form_h") is not None and f.get("form_a") is not None:
        parts.append(f"forma últimos 5: {f['form_h']:.1f} vs {f['form_a']:.1f} pts")
    if ctx.get("xg"):
        parts.append(f"goles esperados {ctx['xg'][0]:.1f}–{ctx['xg'][1]:.1f}")
    if opt.get("odds"):
        parts.append(f"cuota {opt['odds']:.2f} en {opt.get('book')}")
    return "; ".join(parts)


def candidates(matches: list[dict]) -> list[dict]:
    """La selección más probable (>= MIN_P) de cada partido próximo, ordenadas de más a menos fiable."""
    now = repo.utc_now()
    out = []
    for m in matches:
        if not m.get("options") or not m["ref"].startswith("m:") or (m.get("kickoff") or "") <= now:
            continue
        opts = [o for o in m["options"] if o["key"] in MARKETS and o["p"] >= MIN_P]
        if not opts:
            continue
        best = max(opts, key=lambda o: o["p"])
        out.append({"match": int(m["ref"][2:]), "ref": m["ref"], "key": best["key"], "label": best["label"],
                    "market": MARKET_NAME[best["key"]], "p": best["p"], "odds": best.get("odds"),
                    "book": best.get("book"), "reason": reason(m, best), "home": m["home"], "away": m["away"],
                    "home_id": m.get("home_id"), "away_id": m.get("away_id"), "league": m["league"],
                    "league_name": m["league_name"], "kickoff": m["kickoff"]})
    return sorted(out, key=lambda c: -c["p"])


def register(conn: sqlite3.Connection, picks: list[dict], horizon_hours: float = 36) -> dict:
    """Registra (una vez por partido) los pronósticos de partidos que empiezan dentro de `horizon_hours`."""
    now = repo.utc_now()
    limit = repo.to_iso(repo.from_iso(now) + pd.Timedelta(hours=horizon_hours).to_pytimedelta())
    before = conn.total_changes
    for p in [p for p in picks if p["kickoff"] <= limit][:MAX_PER_DAY]:
        conn.execute(
            """INSERT OR IGNORE INTO daily_picks (created_at, match_id, selection, market, p, odds, book, reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (now, p["match"], p["key"], p["market"], p["p"], p["odds"], p["book"], p["reason"]))
    conn.commit()
    return {"daily_picks": conn.total_changes - before}


def record(conn: sqlite3.Connection) -> dict:
    """Pronósticos registrados: acierto real vs esperado, por mercado y por nivel de confianza."""
    df = pd.read_sql_query(
        """SELECT d.*, m.kickoff_utc, m.status, m.home_goals, m.away_goals, c.code AS league,
                  th.name AS home, ta.name AS away, m.home_team_id AS home_id, m.away_team_id AS away_id
           FROM daily_picks d JOIN matches m ON m.id = d.match_id JOIN competitions c ON c.id = m.competition_id
           JOIN teams th ON th.id = m.home_team_id JOIN teams ta ON ta.id = m.away_team_id
           ORDER BY m.kickoff_utc DESC""", conn)
    out = {"n": 0, "pending": 0, "items": [], "by_market": [], "bins": []}
    if df.empty:
        return out
    fin = df.status == "finished"
    df["hit"] = None
    df.loc[fin, "hit"] = [combos.pattern_hits(int(h), int(a), [k]) for h, a, k in
                          zip(df.home_goals[fin], df.away_goals[fin], df.selection[fin])]
    done = df[fin]
    out["pending"] = int((~fin).sum())
    out["items"] = [{"kickoff": r.kickoff_utc, "league": r.league, "home": r.home, "away": r.away,
                     "home_id": int(r.home_id), "away_id": int(r.away_id), "label": combos.SELECTIONS[r.selection][0],
                     "market": r.market, "p": r.p, "odds": None if pd.isna(r.odds) else float(r.odds),
                     "book": None if pd.isna(r.book) else r.book, "reason": r.reason,
                     "status": "pendiente" if r.status != "finished" else ("acierto" if r.hit else "fallo"),
                     "score": f"{int(r.home_goals)}-{int(r.away_goals)}" if r.status == "finished" else None}
                    for r in df.head(60).itertuples()]
    if len(done):
        hit = done.hit.astype(bool)
        out.update({"n": len(done), "hit": round(float(hit.mean()), 4), "expected": round(float(done.p.mean()), 4)})
        out["by_market"] = [{"market": k, "n": len(g), "hit": round(float(g.hit.astype(bool).mean()), 4),
                             "expected": round(float(g.p.mean()), 4)} for k, g in done.groupby("market")]
        for lo, hi in ((0.65, 0.70), (0.70, 0.75), (0.75, 0.80), (0.80, 1.01)):
            g = done[(done.p >= lo) & (done.p < hi)]
            if len(g):
                out["bins"].append({"range": f"{int(lo * 100)}–{min(int(hi * 100), 100)}%", "n": len(g),
                                    "expected": round(float(g.p.mean()), 4),
                                    "hit": round(float(g.hit.astype(bool).mean()), 4)})
        odds = done.odds.astype(float)
        has = odds.notna()
        if has.any():                      # qué habría pasado apostando 1 unidad a cada pronóstico fiable
            prof = np.where(done.hit[has].astype(bool), odds[has] - 1, -1.0)
            out["yield_if_bet"] = round(float(prof.mean()), 4)
    return out
