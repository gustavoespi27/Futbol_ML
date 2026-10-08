"""Seguimiento prospectivo: predicciones registradas ANTES de cada partido, sin dinero real.

1. Descarga los próximos partidos con cuotas pre-partido de football-data.co.uk
   (fixtures.csv y new_league_fixtures.csv).
2. Guarda partido + snapshot de cuotas (is_closing=0, captured_at=ahora).
3. Predice con los parámetros validados de la liga y guarda la predicción con su hora.
   "Apuesta en papel" si el EV (probabilidad combinada con el mercado) supera el umbral.
4. Cuando llegan resultado y cuotas de cierre, `evaluate` compara contra el mercado:
   log loss, CLV (cuota tomada vs cuota de cierre) y yield.
"""

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from io import StringIO

import numpy as np
import pandas as pd

from footy.betting.devig import proportional
from footy.db import repository as repo
from footy.ingest import football_data as fd
from footy.leagues import load_params
from footy.prediction.predictor import LeaguePredictor

log = logging.getLogger(__name__)
SOURCE = "football_data_fixtures"
MODEL_VERSION = "elo_dc_v1"
PRE_BOOKS = {"PS": "Pinnacle", "B365": "Bet365", "BFE": "Betfair Exchange", "Max": "Market Max", "Avg": "Market Avg"}
MARKET_REFERENCE = ("Pinnacle", "Betfair Exchange", "Market Avg")   # para quitar margen, en este orden
PAPER_BOOKS = {"Bet365": 0.0, "Betfair Exchange": 0.05}             # casa -> comisión sobre ganancias
FLAGGED = ("T1", "I1", "P1", "SWE")                                  # pasaron el criterio del análisis 03
MIN_HOURS_BETWEEN = 6


def fetch_fixtures() -> pd.DataFrame:
    """Próximos partidos de las ligas con parámetros, en formato estándar."""
    params = load_params()
    frames = []
    main = fd._get(f"{fd.BASE}/fixtures.csv")
    if main:
        fd._save_raw("fixtures", main)
        d = pd.read_csv(StringIO(main), on_bad_lines="skip")
        d = d.rename(columns={"Div": "code", "HomeTeam": "Home", "AwayTeam": "Away"})
        frames.append(d)
    extra = fd._get(f"{fd.BASE}/new_league_fixtures.csv")
    if extra:
        fd._save_raw("new_league_fixtures", extra)
        d = pd.read_csv(StringIO(extra), on_bad_lines="skip")
        by_country = {v["country"]: c for c, v in fd.leagues()["extra"].items()}
        d["code"] = d.Country.str.strip().map(by_country)
        d.loc[d.League.str.strip() == "Copa De La Liga Profesional", "code"] = None
        frames.append(d)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df = df[df.code.isin(params)].copy()
    df["Home"], df["Away"] = df.Home.astype(str).str.strip(), df.Away.astype(str).str.strip()
    df["kickoff_utc"] = fd._kickoff(df.Date, df.Time if "Time" in df else pd.Series([None] * len(df)))
    return df.reset_index(drop=True)


def register(conn: sqlite3.Connection, fixtures: pd.DataFrame) -> dict:
    now = datetime.now(timezone.utc)
    now_iso = repo.to_iso(now)
    counts = {"fixtures": 0, "predictions": 0, "paper_bets": 0}
    fixtures = fixtures[fixtures.kickoff_utc > now_iso]
    for code, group in fixtures.groupby("code"):
        try:
            predictor = LeaguePredictor(code)
        except Exception:
            log.exception("No se pudo ajustar el modelo de %s", code)
            continue
        country = fd._country(code)
        comp_id = repo.competition_id(conn, code)
        season = conn.execute("SELECT season FROM matches WHERE competition_id = ? ORDER BY kickoff_utc DESC LIMIT 1",
                              (comp_id,)).fetchone()
        for row in group.to_dict("records"):
            home = repo.resolve_team(conn, fd.SOURCE, row["Home"], row["Home"], country)
            away = repo.resolve_team(conn, fd.SOURCE, row["Away"], row["Away"], country)
            match_id = repo.upsert_match(
                conn, source=SOURCE, source_match_id=f"{code}|{row['Date']}|{row['Home']}|{row['Away']}",
                competition_id=comp_id, season=season["season"] if season else str(now.year),
                kickoff_utc=row["kickoff_utc"], home_team_id=home, away_team_id=away, status="scheduled")
            counts["fixtures"] += 1
            books = _odds_by_book(row)
            repo.insert_odds(conn, [
                {"match_id": match_id, "source": SOURCE, "bookmaker": b, "market": "1X2", "line": 0.0,
                 "selection": s, "price": float(o), "captured_at": now_iso, "is_closing": 0}
                for b, odds in books.items() for s, o in zip("HDA", odds)])
            if _recent_prediction(conn, match_id, now):
                continue
            ref = next((b for b in MARKET_REFERENCE if b in books), None)
            pr = predictor.probabilities(home, away, books[ref] if ref else None)
            extra = {"league": code, "market_reference": ref, "params_source": predictor.params["source"],
                     "min_ev": predictor.params["min_ev"], "lam": pr["lam"], "mu": pr["mu"], "paper_bets": []}
            if ref:
                extra["p_market"] = pr["p_market"].round(5).tolist()
                extra["p_final"] = pr["p_final"].round(5).tolist()
                for book, commission in PAPER_BOOKS.items():
                    if book not in books:
                        continue
                    eff = 1 + (books[book] - 1) * (1 - commission)
                    ev = pr["p_final"] * eff - 1
                    k = int(np.argmax(ev))
                    if ev[k] > predictor.params["min_ev"]:
                        extra["paper_bets"].append({"book": book, "sel": "HDA"[k], "odds": float(books[book][k]),
                                                    "effective_odds": float(eff[k]), "ev": float(ev[k])})
                        counts["paper_bets"] += 1
            conn.execute(
                """INSERT INTO predictions (match_id, model_version, created_at, p_home, p_draw, p_away,
                       lambda_home, lambda_away, extra_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (match_id, MODEL_VERSION, now_iso, *map(float, pr["p_model"]), pr["lam"], pr["mu"],
                 json.dumps(extra)))
            counts["predictions"] += 1
        conn.commit()
    return counts


def _odds_by_book(row: dict) -> dict[str, np.ndarray]:
    out = {}
    for prefix, book in PRE_BOOKS.items():
        vals = [fd._num(row.get(f"{prefix}{s}")) for s in "HDA"]
        if all(v is not None and v > 1 for v in vals):
            out[book] = np.array(vals)
    return out


def _recent_prediction(conn, match_id: int, now: datetime) -> bool:
    since = repo.to_iso(now - timedelta(hours=MIN_HOURS_BETWEEN))
    return conn.execute("SELECT 1 FROM predictions WHERE match_id = ? AND model_version = ? AND created_at > ?",
                        (match_id, MODEL_VERSION, since)).fetchone() is not None


# --- Evaluación -------------------------------------------------------------

def evaluate(conn: sqlite3.Connection) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Última predicción previa al kickoff de cada partido terminado + cierre del mercado."""
    preds = pd.read_sql_query(
        """SELECT p.*, m.kickoff_utc, m.home_goals, m.away_goals, th.name AS home, ta.name AS away
           FROM predictions p JOIN matches m ON m.id = p.match_id
           JOIN teams th ON th.id = m.home_team_id JOIN teams ta ON ta.id = m.away_team_id
           WHERE m.status = 'finished' AND p.created_at < m.kickoff_utc AND p.model_version = ?""",
        conn, params=(MODEL_VERSION,))
    if preds.empty:
        return pd.DataFrame(), pd.DataFrame()
    preds = preds.sort_values("created_at").groupby("match_id").tail(1).reset_index(drop=True)
    closing = pd.read_sql_query(
        f"""SELECT match_id, bookmaker, selection, price FROM odds
            WHERE is_closing = 1 AND market = '1X2' AND match_id IN ({",".join(map(str, preds.match_id))})""", conn)
    close = closing.pivot_table(index="match_id", columns=["bookmaker", "selection"], values="price")

    rows, bets = [], []
    for r in preds.to_dict("records"):
        extra = json.loads(r["extra_json"])
        y = 0 if r["home_goals"] > r["away_goals"] else 1 if r["home_goals"] == r["away_goals"] else 2
        rec = {"match_id": r["match_id"], "league": extra["league"], "kickoff": r["kickoff_utc"],
               "partido": f"{r['home']} vs {r['away']}", "y": y,
               "ll_model": -np.log([r["p_home"], r["p_draw"], r["p_away"]][y])}
        if "p_final" in extra:
            rec["ll_final"] = -np.log(extra["p_final"][y])
        fair = _closing_fair(close, r["match_id"])
        if fair is not None:
            rec["ll_market_close"] = -np.log(fair[0][y])
            rec["market_close_book"] = fair[1]
        rows.append(rec)
        for b in extra["paper_bets"]:
            k = "HDA".index(b["sel"])
            won = k == y
            profit = b["effective_odds"] - 1 if won else -1.0
            clv = None
            if fair is not None:
                clv = b["odds"] * fair[0][k] - 1          # cuota tomada vs probabilidad justa de cierre
            bets.append({"league": extra["league"], "partido": rec["partido"], "book": b["book"], "sel": b["sel"],
                         "odds": b["odds"], "ev": b["ev"], "won": won, "profit": profit, "clv": clv})
    return pd.DataFrame(rows), pd.DataFrame(bets)


def _closing_fair(close: pd.DataFrame, match_id: int):
    if match_id not in close.index:
        return None
    for book in ("Pinnacle", "Betfair Exchange", "Market Avg"):
        cols = [(book, s) for s in "HDA"]
        if all(c in close.columns for c in cols):
            odds = close.loc[match_id, cols].to_numpy(dtype=float)
            if not np.isnan(odds).any():
                return proportional(odds[None, :])[0], book
    return None


def report(conn: sqlite3.Connection) -> str:
    matches, bets = evaluate(conn)
    pending = conn.execute(
        """SELECT COUNT(DISTINCT p.match_id) FROM predictions p JOIN matches m ON m.id = p.match_id
           WHERE m.status != 'finished' AND p.model_version = ?""", (MODEL_VERSION,)).fetchone()[0]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    md = [f"# Seguimiento prospectivo ({MODEL_VERSION})", "",
          f"*Actualizado {now} por `scripts/daily.py`. Predicciones registradas antes de cada partido; sin dinero real.*", "",
          f"Partidos evaluados: **{len(matches)}** · pendientes de resultado: **{pending}** · apuestas en papel: **{len(bets)}**", "",
          f"Ligas marcadas en el análisis 03: {', '.join(FLAGGED)}.", ""]
    if matches.empty:
        md += ["Todavía no hay partidos terminados con predicción previa."]
        return "\n".join(md)
    m = matches.dropna(subset=["ll_market_close"])
    md += ["## Calidad probabilística (log loss; menor es mejor)", "",
           "| Grupo | Partidos | Modelo | Modelo + mercado pre-partido | Mercado al cierre |",
           "|---|---:|---:|---:|---:|"]
    for name, g in (("Todas", m), ("Ligas marcadas", m[m.league.isin(FLAGGED)])):
        if len(g):
            md.append(f"| {name} | {len(g)} | {g.ll_model.mean():.4f} | {g.ll_final.mean():.4f} | {g.ll_market_close.mean():.4f} |")
    if not bets.empty:
        md += ["", "## Apuestas en papel", "",
               "CLV = cuota tomada × probabilidad justa al cierre − 1. CLV medio positivo y sostenido es la señal "
               "más rápida de ventaja real; el yield necesita miles de apuestas para ser concluyente.", "",
               "| Grupo | Apuestas | Acierto | Yield | CLV medio | % con CLV > 0 |", "|---|---:|---:|---:|---:|---:|"]
        for name, g in (("Todas", bets), ("Ligas marcadas", bets[bets.league.isin(FLAGGED)])):
            if len(g):
                clv = g.clv.dropna()
                md.append(f"| {name} | {len(g)} | {g.won.mean():.1%} | {g.profit.mean():+.1%} | "
                          f"{clv.mean():+.2%} | {(clv > 0).mean():.0%} |" if len(clv) else
                          f"| {name} | {len(g)} | {g.won.mean():.1%} | {g.profit.mean():+.1%} | | |")
    return "\n".join(md)
