"""Ingesta de football-data.co.uk ("extra leagues": ARG, BRA).

Formato: Country, League, Season, Date (dd/mm/yyyy), Time (hora del Reino Unido),
Home, Away, HG, AG, Res y cuotas de CIERRE 1X2 (PSC*, MaxC*, AvgC*, BFEC*, B365C*).
No hay cuotas de apertura: las cuotas se guardan con is_closing=1 y
captured_at = kickoff (es la última información de mercado antes del partido).
"""

import sqlite3
from datetime import datetime, timezone
from io import StringIO
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from footy import config
from footy.db import repository as repo

SOURCE = "football_data"
UK = ZoneInfo("Europe/London")

# Columnas de cierre -> nombre de la casa
CLOSING_BOOKMAKERS = {
    "PSC": "Pinnacle",
    "B365C": "Bet365",
    "BFEC": "Betfair Exchange",
    "MaxC": "Market Max",
    "AvgC": "Market Avg",
}

# Valor de la columna League -> código de competición
LEAGUE_CODES = {
    "Liga Profesional": "ARG",
    "Primera Division": "ARG",
    "Copa De La Liga Profesional": "ARGC",
    "Serie A": "BRA",
}


def download(code: str) -> pd.DataFrame:
    url = config.settings()["competitions"][code]["football_data_url"]
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    text = r.content.decode("utf-8-sig")
    raw_dir = config.path("raw") / SOURCE
    raw_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (raw_dir / f"{code}_{stamp}.csv").write_text(text, encoding="utf-8")
    return parse(text)


def parse(text: str) -> pd.DataFrame:
    df = pd.read_csv(StringIO(text), dtype={"Season": str})
    for col in ("Country", "League", "Season", "Home", "Away"):
        df[col] = df[col].astype(str).str.strip()
    local = pd.to_datetime(df["Date"] + " " + df["Time"], format="%d/%m/%Y %H:%M")
    df["kickoff_utc"] = [repo.to_iso(ts.to_pydatetime().replace(tzinfo=UK)) for ts in local]
    return df


def store(conn: sqlite3.Connection, df: pd.DataFrame) -> dict:
    now = repo.utc_now()
    counts = {"matches": 0, "odds": 0, "skipped": 0}
    for row in df.itertuples(index=False):
        comp_code = LEAGUE_CODES.get(row.League)
        if comp_code is None:
            counts["skipped"] += 1
            continue
        country = config.settings()["competitions"][comp_code]["country"]
        home = repo.resolve_team(conn, SOURCE, row.Home, row.Home, country)
        away = repo.resolve_team(conn, SOURCE, row.Away, row.Away, country)
        played = pd.notna(row.HG) and pd.notna(row.AG)
        status = "finished" if played else ("scheduled" if row.kickoff_utc > now else "postponed")

        match_id = repo.upsert_match(
            conn,
            source=SOURCE,
            source_match_id=f"{row.Season}|{row.Date}|{row.Home}|{row.Away}",
            competition_id=repo.competition_id(conn, comp_code),
            season=row.Season,
            kickoff_utc=row.kickoff_utc,
            home_team_id=home,
            away_team_id=away,
            status=status,
            home_goals=int(row.HG) if played else None,
            away_goals=int(row.AG) if played else None,
        )
        counts["matches"] += 1
        counts["odds"] += repo.insert_odds(conn, _closing_odds(match_id, row))
    conn.commit()
    return counts


def _closing_odds(match_id: int, row) -> list[dict]:
    rows = []
    values = row._asdict()
    for prefix, bookmaker in CLOSING_BOOKMAKERS.items():
        prices = [values.get(f"{prefix}{s}") for s in ("H", "D", "A")]
        if any(p is None or pd.isna(p) or p <= 1 for p in prices):
            continue  # solo tripletas completas: necesarias para quitar el margen
        for sel, price in zip(("H", "D", "A"), prices):
            rows.append({
                "match_id": match_id, "source": SOURCE, "bookmaker": bookmaker,
                "market": "1X2", "line": 0.0, "selection": sel, "price": float(price),
                "captured_at": row.kickoff_utc, "is_closing": 1,
            })
    return rows
