"""Ingesta de football-data.co.uk (ligas listadas en config/football_data.yaml).

Dos formatos:
- "extra" (new/<code>.csv): Country, League, Season, Date, Time, Home, Away, HG, AG
  y solo cuotas de CIERRE 1X2.
- "main" (mmz4281/<yyzz>/<div>.csv): Div, Date, [Time], HomeTeam, AwayTeam, FTHG, FTAG,
  estadísticas (tiros, tiros al arco, corners, faltas, tarjetas; xG desde 2026/27) y cuotas.

Horas en hora del Reino Unido (sin hora antes de 2019/20 en "main": se asume 15:00).
Solo se guardan cuotas de cierre: is_closing=1, captured_at = kickoff. 1X2 en ambos formatos;
Over/Under 2,5 (market "OU", selección OVER/UNDER) solo existe en "main".
Las estadísticas del partido se conocen al terminar: captured_at = kickoff + 3 h.
"""

import hashlib
import json
import logging
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from io import StringIO
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yaml

from footy import config
from footy.db import repository as repo

SOURCE = "football_data"
UK = ZoneInfo("Europe/London")
BASE = "https://www.football-data.co.uk"
log = logging.getLogger(__name__)


def _database_key(path: Path) -> str:
    try:
        inode = path.stat().st_ino
    except FileNotFoundError:
        inode = 0
    return f"{path.resolve()}:{inode}"


def _cache_paths(url: str) -> tuple[Path, Path]:
    cache = config.PROJECT_ROOT / "data/cache/football_data"
    cache.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(url.encode()).hexdigest()
    return cache / f"{key}.json", cache / f"{key}.csv"


def _metadata(path: Path) -> dict:
    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
        return metadata if isinstance(metadata, dict) else {}
    except (OSError, ValueError):
        return {}


def _atomic(path: Path, content: str) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def _fetch(url: str, only_changed: bool = False) -> tuple[str | None, tuple[str, str] | None]:
    meta_path, csv_path = _cache_paths(url)
    meta = _metadata(meta_path)
    headers = {}
    if csv_path.is_file():
        if meta.get("etag"):
            headers["If-None-Match"] = meta["etag"]
        if meta.get("last_modified"):
            headers["If-Modified-Since"] = meta["last_modified"]
    response = requests.get(url, headers=headers, timeout=60)
    if response.status_code == 404:
        return None, None
    if response.status_code == 304:
        text = csv_path.read_text(encoding="utf-8")
    else:
        response.raise_for_status()
        try:
            text = response.content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = response.content.decode("latin-1")
        _atomic(csv_path, text)
        meta.update(etag=response.headers.get("ETag"), last_modified=response.headers.get("Last-Modified"))
    digest = hashlib.sha256(text.encode()).hexdigest()
    meta["content_hash"] = digest
    _atomic(meta_path, json.dumps(meta))
    identity = _database_key(config.path("database"))
    if only_changed and meta.get("applied", {}).get(identity) == digest:
        log.info("CSV sin cambios, sin parseo: %s", url)
        return None, None
    return text, (str(meta_path), digest)

CLOSING_BOOKMAKERS = {
    "PSC": "Pinnacle",
    "B365C": "Bet365",
    "BFEC": "Betfair Exchange",
    "MaxC": "Market Max",
    "AvgC": "Market Avg",
}

# En Over/Under 2,5 Pinnacle usa otro prefijo (PC>2.5 en vez de PSC).
CLOSING_OU_BOOKMAKERS = {**{k: v for k, v in CLOSING_BOOKMAKERS.items() if k != "PSC"}, "PC": "Pinnacle"}

# Solo Argentina mezcla dos torneos en el mismo archivo.
ARG_LEAGUES = {"Liga Profesional": "ARG", "Primera Division": "ARG", "Copa De La Liga Profesional": "ARGC"}

# Columnas de estadísticas (formato main) -> nombre en team_match_stats
STATS = {"S": "total_shots", "ST": "shots_on_goal", "C": "corner_kicks", "F": "fouls",
         "Y": "yellow_cards", "R": "red_cards", "xG": "expected_goals"}


@lru_cache
def leagues() -> dict:
    with open(config.PROJECT_ROOT / "config" / "football_data.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def league_info(code: str) -> dict:
    cfg = leagues()
    return cfg["extra"].get(code) or cfg["main"][code]


def _get(url: str) -> str | None:
    return _fetch(url)[0]


def _save_raw(name: str, text: str) -> None:
    raw_dir = config.path("raw") / SOURCE
    raw_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (raw_dir / f"{name}_{stamp}.csv").write_text(text, encoding="utf-8")


def download(code: str, seasons: list[int] | None = None, *, only_changed: bool = False) -> pd.DataFrame:
    """Descarga una liga y devuelve el formato estándar. `seasons` (años de inicio) solo aplica a "main"."""
    markers = []

    def fetch(url: str) -> str | None:
        if not only_changed:
            return _get(url)
        text, marker = _fetch(url, only_changed=True)
        if marker:
            markers.append(marker)
        return text

    if code in leagues()["extra"]:
        text = fetch(f"{BASE}/new/{code}.csv")
        if not text:
            return pd.DataFrame()
        _save_raw(code, text)
        frame = parse_extra(text, code)
        frame.attrs["http_sources"] = markers
        return frame
    frames = []
    first = leagues()["first_season"]
    now = datetime.now(timezone.utc)
    last = now.year if now.month >= 7 else now.year - 1
    for year in seasons or range(first, last + 1):
        tag = f"{year % 100:02d}{(year + 1) % 100:02d}"
        text = fetch(f"{BASE}/mmz4281/{tag}/{code}.csv")
        if not text:
            continue
        _save_raw(f"{code}_{tag}", text)
        frames.append(parse_main(text, code, f"{year}/{year + 1}"))
    frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    frame.attrs["http_sources"] = markers
    return frame


def _kickoff(date: pd.Series, time: pd.Series) -> list[str]:
    d = pd.to_datetime(date, format="%d/%m/%Y", errors="coerce")
    d = d.fillna(pd.to_datetime(date, format="%d/%m/%y", errors="coerce"))
    t = pd.to_timedelta(time.fillna("15:00").astype(str).str.strip() + ":00")
    return [repo.to_iso((x + dt).to_pydatetime().replace(tzinfo=UK)) for x, dt in zip(d, t)]


def parse_extra(text: str, code: str) -> pd.DataFrame:
    df = pd.read_csv(StringIO(text), dtype={"Season": str})
    for col in ("League", "Season", "Home", "Away"):
        df[col] = df[col].astype(str).str.strip()
    if code == "ARG":
        df["comp_code"] = df.League.map(ARG_LEAGUES)
    else:
        main_league = df.League.mode().iloc[0]   # descarta filas sueltas de otras categorías (p. ej. playoffs)
        df["comp_code"] = [code if lg == main_league else None for lg in df.League]
    df["kickoff_utc"] = _kickoff(df.Date, df.Time)
    return df


def parse_main(text: str, code: str, season: str) -> pd.DataFrame:
    df = pd.read_csv(StringIO(text), on_bad_lines="skip", encoding_errors="replace")
    df = df.dropna(subset=["HomeTeam", "AwayTeam", "Date"]).copy()   # copy: evita un frame fragmentado
    df = df.rename(columns={"HomeTeam": "Home", "AwayTeam": "Away", "FTHG": "HG", "FTAG": "AG"})
    df["Home"], df["Away"] = df.Home.astype(str).str.strip(), df.Away.astype(str).str.strip()
    df["Season"] = season
    df["comp_code"] = code
    df["kickoff_utc"] = _kickoff(df.Date, df["Time"] if "Time" in df else pd.Series([None] * len(df)))
    return df


def store(conn: sqlite3.Connection, df: pd.DataFrame) -> dict:
    now = repo.utc_now()
    counts = {"matches": 0, "odds": 0, "stats": 0, "skipped": 0}
    countries: dict[str, str] = {}
    for row in df.to_dict("records"):
        comp_code = row.get("comp_code")
        if not isinstance(comp_code, str):
            counts["skipped"] += 1
            continue
        if comp_code not in countries:
            countries[comp_code] = _country(comp_code)
        country = countries[comp_code]
        home = repo.resolve_team(conn, SOURCE, row["Home"], row["Home"], country)
        away = repo.resolve_team(conn, SOURCE, row["Away"], row["Away"], country)
        played = pd.notna(row["HG"]) and pd.notna(row["AG"])
        status = "finished" if played else ("scheduled" if row["kickoff_utc"] > now else "postponed")

        match_id = repo.upsert_match(
            conn,
            source=SOURCE,
            source_match_id=f"{row['Season']}|{row['Date']}|{row['Home']}|{row['Away']}",
            competition_id=repo.competition_id(conn, comp_code),
            season=row["Season"],
            kickoff_utc=row["kickoff_utc"],
            home_team_id=home,
            away_team_id=away,
            status=status,
            home_goals=int(row["HG"]) if played else None,
            away_goals=int(row["AG"]) if played else None,
        )
        counts["matches"] += 1
        counts["odds"] += repo.insert_odds(conn, _closing_odds(match_id, row) + closing_ou_odds(match_id, row))
        counts["stats"] += _store_stats(conn, match_id, home, away, row)
    conn.commit()
    database = Path(conn.execute("PRAGMA database_list").fetchone()[2])
    for filename, digest in df.attrs.get("http_sources", []):
        meta_path = Path(filename)
        try:
            meta = _metadata(meta_path)
            meta.setdefault("applied", {})[_database_key(database)] = digest
            _atomic(meta_path, json.dumps(meta))
        except OSError:
            log.warning("No se pudo confirmar caché HTTP: %s", meta_path)
    return counts


def _country(comp_code: str) -> str:
    if comp_code in ("ARG", "ARGC"):
        return "Argentina"
    return league_info(comp_code)["country"]


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(f) else f


def _closing_odds(match_id: int, row: dict) -> list[dict]:
    rows = []
    for prefix, bookmaker in CLOSING_BOOKMAKERS.items():
        prices = [_num(row.get(f"{prefix}{s}")) for s in ("H", "D", "A")]
        if any(p is None or p <= 1 for p in prices):
            continue  # solo tripletas completas: necesarias para quitar el margen
        for sel, price in zip(("H", "D", "A"), prices):
            rows.append({
                "match_id": match_id, "source": SOURCE, "bookmaker": bookmaker,
                "market": "1X2", "line": 0.0, "selection": sel, "price": price,
                "captured_at": row["kickoff_utc"], "is_closing": 1,
            })
    return rows


def closing_ou_odds(match_id: int, row: dict, prefixes: dict = CLOSING_OU_BOOKMAKERS,
                    is_closing: int = 1, captured_at: str | None = None, source: str = SOURCE) -> list[dict]:
    """Cuotas Over/Under 2,5 (columnas '<prefijo>>2.5' y '<prefijo><2.5'), solo pares completos."""
    rows = []
    for prefix, bookmaker in prefixes.items():
        over, under = _num(row.get(f"{prefix}>2.5")), _num(row.get(f"{prefix}<2.5"))
        if over is None or under is None or over <= 1 or under <= 1:
            continue
        for sel, price in (("OVER", over), ("UNDER", under)):
            rows.append({"match_id": match_id, "source": source, "bookmaker": bookmaker, "market": "OU",
                         "line": 2.5, "selection": sel, "price": price,
                         "captured_at": captured_at or row["kickoff_utc"], "is_closing": is_closing})
    return rows


def _store_stats(conn, match_id: int, home: int, away: int, row: dict) -> int:
    n = 0
    known_at = repo.to_iso(repo.from_iso(row["kickoff_utc"]) + timedelta(hours=3))
    for suffix, stat in STATS.items():
        for side, team in (("H", home), ("A", away)):
            v = _num(row.get(f"{side}{suffix}"))
            if v is None:
                continue
            conn.execute(
                """INSERT OR REPLACE INTO team_match_stats (match_id, team_id, stat, value, source, captured_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (match_id, team, stat, v, SOURCE, known_at),
            )
            n += 1
    return n
