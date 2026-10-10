"""Carga de partidos terminados con cuotas de cierre 1X2, en formato ancho, para modelar.

Una fila por partido, ordenadas por kickoff. Columnas:
match_id, comp, season, kickoff_utc, date, home_id, away_id, home, away,
home_goals, away_goals, y (0=H, 1=D, 2=A) y <casa>_<H|D|A> para cada casa con cierre.
"""

import sqlite3

import numpy as np
import pandas as pd

SEL = ("H", "D", "A")
BOOKS = {"Pinnacle": "pin", "Market Avg": "avg", "Market Max": "max", "Betfair Exchange": "bfe", "Bet365": "b365"}


STAT_COLS = {"total_shots": "shots", "shots_on_goal": "sot"}


def load_matches(conn: sqlite3.Connection, comps: list[str], with_stats: bool = False) -> pd.DataFrame:
    q = ",".join("?" * len(comps))
    matches = pd.read_sql_query(
        f"""SELECT m.id AS match_id, c.code AS comp, m.season, m.kickoff_utc,
                   m.home_team_id AS home_id, m.away_team_id AS away_id,
                   th.name AS home, ta.name AS away, m.home_goals, m.away_goals
            FROM matches m
            JOIN competitions c ON c.id = m.competition_id
            JOIN teams th ON th.id = m.home_team_id
            JOIN teams ta ON ta.id = m.away_team_id
            WHERE m.status = 'finished' AND c.code IN ({q})
            ORDER BY m.kickoff_utc, m.id""",
        conn, params=comps,
    )
    odds = pd.read_sql_query(
        f"""SELECT o.match_id, o.bookmaker, o.selection, o.price
            FROM odds o JOIN matches m ON m.id = o.match_id
            JOIN competitions c ON c.id = m.competition_id
            WHERE o.market = '1X2' AND o.is_closing = 1 AND c.code IN ({q})""",
        conn, params=comps,
    )
    odds = odds[odds.bookmaker.isin(BOOKS)]
    wide = odds.pivot_table(index="match_id", columns=["bookmaker", "selection"], values="price")
    wide.columns = [f"{BOOKS[b]}_{s}" for b, s in wide.columns]

    df = matches.merge(wide, left_on="match_id", right_index=True, how="left")
    for b in BOOKS.values():
        for s in SEL:
            if f"{b}_{s}" not in df:
                df[f"{b}_{s}"] = np.nan
    if with_stats:
        df = _add_stats(conn, df, comps)
    df["kickoff"] = pd.to_datetime(df.kickoff_utc, utc=True)
    df["y"] = np.select([df.home_goals > df.away_goals, df.home_goals == df.away_goals], [0, 1], 2)
    return df.reset_index(drop=True)


def odds_matrix(df: pd.DataFrame, book: str) -> np.ndarray:
    return df[[f"{book}_{s}" for s in SEL]].to_numpy(dtype=float)


def has_odds(df: pd.DataFrame, book: str) -> np.ndarray:
    return ~np.isnan(odds_matrix(df, book)).any(axis=1)


def _add_stats(conn, df: pd.DataFrame, comps: list[str]) -> pd.DataFrame:
    """Agrega h_shots, a_shots, h_sot, a_sot (NaN si el partido no tiene estadísticas)."""
    q = ",".join("?" * len(comps))
    st = pd.read_sql_query(
        f"""SELECT s.match_id, s.team_id, s.stat, s.value FROM team_match_stats s
            JOIN matches m ON m.id = s.match_id JOIN competitions c ON c.id = m.competition_id
            WHERE s.stat IN ('total_shots', 'shots_on_goal') AND c.code IN ({q})""",
        conn, params=comps,
    )
    st = st.drop_duplicates(["match_id", "team_id", "stat"])
    wide = st.pivot_table(index=["match_id", "team_id"], columns="stat", values="value").rename(columns=STAT_COLS)
    for side, col in (("h", "home_id"), ("a", "away_id")):
        part = wide.add_prefix(f"{side}_")
        df = df.merge(part, left_on=["match_id", col], right_index=True, how="left")
    for c in ("h_shots", "a_shots", "h_sot", "a_sot"):
        if c not in df:
            df[c] = np.nan
    return df


OU_BOOKS = ("Pinnacle", "Market Avg", "Bet365")
OU_CHUNK = 900                                          # ids por consulta (bajo el límite de variables de SQLite)


def load_ou_closing(conn: sqlite3.Connection, match_ids) -> pd.DataFrame:
    """Cierre Over/Under 2,5 por partido: p_over (sin margen; Pinnacle > promedio > Bet365) y cuotas Bet365.

    Índice match_id; columnas p_over, b365_over, b365_under (NaN si falta)."""
    # Vacío con columnas float: tras un merge, p_over debe seguir siendo numérico (NaN) para np.isnan.
    empty = pd.DataFrame({c: pd.Series(dtype=float) for c in ("p_over", "b365_over", "b365_under")},
                         index=pd.Index([], dtype="int64", name="match_id"))
    ids = [int(i) for i in match_ids]
    if not ids:
        return empty
    # Consulta parametrizada en lotes: SQLite limita las variables de enlace por sentencia (999 en versiones antiguas).
    chunks = []
    for k in range(0, len(ids), OU_CHUNK):
        part = ids[k:k + OU_CHUNK]
        chunks.append(pd.read_sql_query(
            f"""SELECT match_id, bookmaker, selection, price FROM odds
                WHERE market = 'OU' AND line = 2.5 AND is_closing = 1
                  AND match_id IN ({",".join("?" * len(part))})""", conn, params=part))
    # Un lote sin filas llega con columnas object y contaminaría el tipo de todo el resultado: se descarta.
    chunks = [c for c in chunks if not c.empty]
    if not chunks:
        return empty
    odds = pd.concat(chunks, ignore_index=True).astype({"price": float})
    wide = odds.pivot_table(index="match_id", columns=["bookmaker", "selection"], values="price")
    out = pd.DataFrame(index=wide.index)
    out["p_over"] = np.nan
    for book in reversed(OU_BOOKS):                      # el primero de OU_BOOKS gana
        if (book, "OVER") in wide and (book, "UNDER") in wide:
            o, u = wide[(book, "OVER")], wide[(book, "UNDER")]
            p = (1 / o) / (1 / o + 1 / u)
            out["p_over"] = p.where(p.notna(), out["p_over"])
    for sel in ("OVER", "UNDER"):
        out[f"b365_{sel.lower()}"] = wide[("Bet365", sel)] if ("Bet365", sel) in wide else np.nan
    return out.dropna(subset=["p_over"])


DRIFT_BOOKS = ("Pinnacle", "Bet365")


def load_odds_drift(conn: sqlite3.Connection, match_ids, books=DRIFT_BOOKS) -> pd.DataFrame:
    """Movimiento de la cuota 1X2 entre el primer y el último snapshot PRE-partido (captured_at < kickoff).

    Una fila por partido, casa y selección con al menos dos snapshots: first, last, n y drift = last / first − 1
    (negativo = la cuota bajó: el mercado se volcó hacia esa selección)."""
    cols = ["match_id", "bookmaker", "selection", "first", "last", "n", "drift"]
    ids = [int(i) for i in match_ids]
    if not ids:
        return pd.DataFrame(columns=cols)
    parts = []
    for k in range(0, len(ids), OU_CHUNK):
        part = ids[k:k + OU_CHUNK]
        parts.append(pd.read_sql_query(
            f"""SELECT o.match_id, o.bookmaker, o.selection, o.price, o.captured_at FROM odds o
                JOIN matches m ON m.id = o.match_id
                WHERE o.market = '1X2' AND o.is_closing = 0 AND o.captured_at < m.kickoff_utc
                  AND o.bookmaker IN ({",".join("?" * len(books))})
                  AND o.match_id IN ({",".join("?" * len(part))})""", conn, params=[*books, *part]))
    parts = [x for x in parts if not x.empty]
    if not parts:
        return pd.DataFrame(columns=cols)
    o = pd.concat(parts, ignore_index=True).astype({"price": float}).sort_values("captured_at")
    g = o.groupby(["match_id", "bookmaker", "selection"]).price
    out = pd.DataFrame({"first": g.first(), "last": g.last(), "n": g.size()}).reset_index()
    out = out[out.n >= 2]
    out["drift"] = out["last"] / out["first"] - 1
    return out[cols].reset_index(drop=True)
