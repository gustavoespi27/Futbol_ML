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


def load_matches(conn: sqlite3.Connection, comps: list[str]) -> pd.DataFrame:
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
    df["kickoff"] = pd.to_datetime(df.kickoff_utc, utc=True)
    df["y"] = np.select([df.home_goals > df.away_goals, df.home_goals == df.away_goals], [0, 1], 2)
    return df.reset_index(drop=True)


def odds_matrix(df: pd.DataFrame, book: str) -> np.ndarray:
    return df[[f"{book}_{s}" for s in SEL]].to_numpy(dtype=float)


def has_odds(df: pd.DataFrame, book: str) -> np.ndarray:
    return ~np.isnan(odds_matrix(df, book)).any(axis=1)
