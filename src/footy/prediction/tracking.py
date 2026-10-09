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
MODEL_VERSION = "elo_dc_v3"     # v3: pesos ajustados con 2016-2025 (v2: pesos >= 0 y cuota <= max_odds)
PRE_BOOKS = {"PS": "Pinnacle", "B365": "Bet365", "BFE": "Betfair Exchange", "Max": "Market Max", "Avg": "Market Avg"}
PRE_OU_BOOKS = {"B365": "Bet365", "P": "Pinnacle", "Max": "Market Max", "Avg": "Market Avg", "BFE": "Betfair Exchange"}
MARKET_REFERENCE = ("Pinnacle", "Betfair Exchange", "Market Avg", "Bet365")   # para quitar margen, en este orden
PAPER_BOOKS = {"Bet365": 0.0, "Betfair Exchange": 0.05}             # casa -> comisión sobre ganancias
FLAGGED = ("T1", "I1", "P1", "SWE")                                  # pasaron el criterio del análisis 03
MIN_HOURS_BETWEEN = 6
ALL_VERSIONS = ("elo_dc_v1", "elo_dc_v2", MODEL_VERSION)


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
                for b, odds in books.items() for s, o in zip("HDA", odds)]
                + fd.closing_ou_odds(match_id, row, PRE_OU_BOOKS, is_closing=0, captured_at=now_iso, source=SOURCE))
            if not _recent_prediction(conn, match_id, now):
                _store_prediction(conn, predictor, code, match_id, home, away, books, now_iso, counts)
        conn.commit()
    return counts


def register_scheduled(conn: sqlite3.Connection, horizon_hours: float = 48) -> dict:
    """Igual que `register`, para partidos ya en la base (API-Football: ARG, BRA) usando el último
    snapshot de cuotas pre-partido de cada casa."""
    now = datetime.now(timezone.utc)
    now_iso = repo.to_iso(now)
    counts = {"fixtures": 0, "predictions": 0, "paper_bets": 0}
    params = load_params()
    rows = pd.read_sql_query(
        """SELECT m.id, c.code, m.home_team_id, m.away_team_id FROM matches m
           JOIN competitions c ON c.id = m.competition_id
           WHERE m.status = 'scheduled' AND m.kickoff_utc BETWEEN ? AND ?""",
        conn, params=(now_iso, repo.to_iso(now + timedelta(hours=horizon_hours))))
    rows = rows[rows.code.isin(params)]
    for code, group in rows.groupby("code"):
        try:
            predictor = LeaguePredictor(code)
        except Exception:
            log.exception("No se pudo ajustar el modelo de %s", code)
            continue
        for r in group.to_dict("records"):
            counts["fixtures"] += 1
            if _recent_prediction(conn, r["id"], now):
                continue
            books = latest_odds(conn, r["id"])
            _store_prediction(conn, predictor, code, r["id"], r["home_team_id"], r["away_team_id"],
                              books, now_iso, counts)
        conn.commit()
    return counts


def latest_odds(conn: sqlite3.Connection, match_id: int) -> dict[str, np.ndarray]:
    """Último snapshot 1X2 pre-partido por casa (sin cuotas de cierre)."""
    df = pd.read_sql_query(
        """SELECT bookmaker, selection, price, captured_at FROM odds
           WHERE match_id = ? AND market = '1X2' AND is_closing = 0""", conn, params=(match_id,))
    out = {}
    for book, g in df.sort_values("captured_at").groupby("bookmaker"):
        last = g[g.captured_at == g.captured_at.max()].set_index("selection").price
        if all(s in last.index for s in "HDA") and (last > 1).all():
            out[book] = last.loc[list("HDA")].to_numpy(dtype=float)
    return out


def latest_market_odds(conn: sqlite3.Connection, match_id: int) -> dict:
    """Último snapshot pre-partido por casa y mercado:
    {"1X2": {casa: {sel: cuota}}, "OU": {casa: {(línea, sel): cuota}}, "BTTS": {casa: {sel: cuota}}}."""
    df = pd.read_sql_query(
        """SELECT bookmaker, market, line, selection, price, captured_at FROM odds
           WHERE match_id = ? AND is_closing = 0 AND market IN ('1X2', 'OU', 'BTTS')""", conn, params=(match_id,))
    out: dict = {"1X2": {}, "OU": {}, "BTTS": {}}
    if df.empty:
        return out
    df = df.sort_values("captured_at").groupby(["bookmaker", "market", "line", "selection"]).tail(1)
    for r in df.itertuples(index=False):
        key = (float(r.line), r.selection) if r.market == "OU" else r.selection
        out[r.market].setdefault(r.bookmaker, {})[key] = float(r.price)
    return out


def _store_prediction(conn, predictor, code, match_id, home, away, books, now_iso, counts) -> None:
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
            ev = np.where(books[book] > predictor.params.get("max_odds", np.inf), -np.inf, ev)
            k = int(np.argmax(ev))
            if ev[k] > predictor.params["min_ev"]:
                extra["paper_bets"].append({"book": book, "sel": "HDA"[k], "odds": float(books[book][k]),
                                            "effective_odds": float(eff[k]), "ev": float(ev[k])})
                counts["paper_bets"] += 1
    conn.execute(
        """INSERT INTO predictions (match_id, model_version, created_at, p_home, p_draw, p_away,
               lambda_home, lambda_away, extra_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (match_id, MODEL_VERSION, now_iso, *map(float, pr["p_model"]), pr["lam"], pr["mu"], json.dumps(extra)))
    counts["predictions"] += 1


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

def evaluate(conn: sqlite3.Connection,
             versions: tuple[str, ...] = (MODEL_VERSION,)) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Última predicción previa al kickoff de cada partido terminado (por versión) + cierre del mercado.

    Si todavía no hay cuotas de cierre se usa el último snapshot pre-partido (columna close_kind)."""
    q = ",".join("?" * len(versions))
    preds = pd.read_sql_query(
        f"""SELECT p.*, m.kickoff_utc, m.home_goals, m.away_goals, th.name AS home, ta.name AS away,
                   m.home_team_id AS home_id, m.away_team_id AS away_id
            FROM predictions p JOIN matches m ON m.id = p.match_id
            JOIN teams th ON th.id = m.home_team_id JOIN teams ta ON ta.id = m.away_team_id
            WHERE m.status = 'finished' AND p.created_at < m.kickoff_utc AND p.model_version IN ({q})""",
        conn, params=versions)
    if preds.empty:
        return pd.DataFrame(), pd.DataFrame()
    preds = preds.sort_values("created_at").groupby(["match_id", "model_version"]).tail(1).reset_index(drop=True)
    close = _reference_odds(conn, preds.match_id.unique())

    rows, bets = [], []
    for r in preds.to_dict("records"):
        extra = json.loads(r["extra_json"])
        y = 0 if r["home_goals"] > r["away_goals"] else 1 if r["home_goals"] == r["away_goals"] else 2
        p_model = [r["p_home"], r["p_draw"], r["p_away"]]
        p_off = extra.get("p_final", p_model)                    # probabilidad oficial: con mercado si lo hubo
        rec = {"match_id": r["match_id"], "model_version": r["model_version"], "league": extra["league"],
               "kickoff": r["kickoff_utc"], "home": r["home"], "away": r["away"],
               "home_id": int(r["home_id"]), "away_id": int(r["away_id"]),
               "partido": f"{r['home']} vs {r['away']}", "score": f"{r['home_goals']}-{r['away_goals']}", "y": y,
               "p_model": p_model, "p_official": p_off, "p_market": extra.get("p_market"),
               "pick": int(np.argmax(p_off)), "hit": int(np.argmax(p_off)) == y,
               "ll_model": -np.log(p_model[y]), "ll_final": -np.log(p_off[y]),
               "ll_market_close": np.nan, "market_close_book": None, "close_kind": None}
        fair = _closing_fair(close, r["match_id"])
        if fair is not None:
            rec["ll_market_close"] = -np.log(fair[0][y])
            rec["market_close_book"], rec["close_kind"] = fair[1], fair[2]
        rows.append(rec)
        for b in extra["paper_bets"]:
            k = "HDA".index(b["sel"])
            won = k == y
            profit = b["effective_odds"] - 1 if won else -1.0
            clv = None
            if fair is not None:
                clv = b["odds"] * fair[0][k] - 1          # cuota tomada vs probabilidad justa de cierre
            bets.append({"model_version": r["model_version"], "league": extra["league"], "kickoff": r["kickoff_utc"],
                         "partido": rec["partido"], "book": b["book"], "sel": b["sel"],
                         "odds": b["odds"], "ev": b["ev"], "won": won, "profit": profit, "clv": clv})
    return pd.DataFrame(rows), pd.DataFrame(bets)


def _reference_odds(conn, match_ids) -> pd.DataFrame:
    """Cuotas 1X2 de referencia por partido y casa: el cierre si existe; si no, el último snapshot pre-partido."""
    ids = ",".join(map(str, match_ids))
    odds = pd.read_sql_query(
        f"""SELECT o.match_id, o.bookmaker, o.selection, o.price, o.is_closing, o.captured_at
            FROM odds o JOIN matches m ON m.id = o.match_id
            WHERE o.market = '1X2' AND o.match_id IN ({ids})
              AND (o.is_closing = 1 OR o.captured_at < m.kickoff_utc)""", conn)
    odds = odds.sort_values(["is_closing", "captured_at"]).groupby(["match_id", "bookmaker", "selection"]).tail(1)
    return odds.set_index(["match_id", "bookmaker", "selection"])


def _closing_fair(close: pd.DataFrame, match_id: int):
    """(probabilidades justas, casa, 'cierre' | 'último pre-partido') o None."""
    if match_id not in close.index.get_level_values(0):
        return None
    sub = close.loc[match_id]
    for book in ("Pinnacle", "Betfair Exchange", "Market Avg", "Bet365"):
        if all((book, s) in sub.index for s in "HDA"):
            rows = sub.loc[[(book, s) for s in "HDA"]]
            kind = "cierre" if rows.is_closing.min() == 1 else "último pre-partido"
            return proportional(rows.price.to_numpy(dtype=float)[None, :])[0], book, kind
    return None


def report(conn: sqlite3.Connection) -> str:
    matches, bets = evaluate(conn, ALL_VERSIONS)
    pending = conn.execute(
        """SELECT COUNT(DISTINCT p.match_id) FROM predictions p JOIN matches m ON m.id = p.match_id
           WHERE m.status != 'finished'""").fetchone()[0]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    md = [f"# Seguimiento prospectivo ({MODEL_VERSION})", "",
          f"*Actualizado {now} por `scripts/daily.py`. Predicciones registradas antes de cada partido; "
          "sin dinero real.*", "",
          f"Partidos evaluados: **{len(matches)}** · pendientes de resultado: **{pending}** · "
          f"apuestas en papel: **{len(bets)}**", "",
          f"Ligas marcadas en el análisis 03: {', '.join(FLAGGED)}.", ""]
    if matches.empty:
        md += ["Todavía no hay partidos terminados con predicción previa."]
        return "\n".join(md)
    md += ["## Calidad probabilística (log loss; menor es mejor)", "",
           "Mercado de referencia: cuotas de cierre sin margen; si aún no llegan, el último snapshot pre-partido.", "",
           "| Versión | Grupo | Partidos | Acierto | Modelo | Modelo + mercado pre-partido | Mercado (referencia) |",
           "|---|---|---:|---:|---:|---:|---:|"]
    for version, mv in matches.groupby("model_version"):
        for name, g in (("Todas", mv), ("Ligas marcadas", mv[mv.league.isin(FLAGGED)])):
            if len(g):
                mk = g.ll_market_close.dropna()
                md.append(f"| {version} | {name} | {len(g)} | {g.hit.mean():.0%} | {g.ll_model.mean():.4f} | "
                          f"{g.ll_final.mean():.4f} | {f'{mk.mean():.4f} ({len(mk)})' if len(mk) else '–'} |")
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
