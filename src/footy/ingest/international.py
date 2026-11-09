"""Resultados públicos CC0 de selecciones absolutas, con nombres y disponibilidad conservadora."""

import csv
import hashlib
import json
import logging
import os
import re
import sqlite3
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import yaml

from footy import config
from footy.db.repository import normalize_name

URL = "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
RAW = config.path("raw") / "international/results.csv"
CATALOG = config.PROJECT_ROOT / "config/international_teams.json"
ALIASES = config.PROJECT_ROOT / "config/team_aliases.yaml"
log = logging.getLogger(__name__)
EXCLUDED = re.compile(r"\b(?:u|sub)[ -]?\d{2}\b|\bwomen\b|\bladies\b|\bfemenin[oa]s?\b|\b[wb]\s*$|A['’]$", re.I)


@dataclass(frozen=True)
class InternationalMatch:
    kickoff: datetime
    available_at: datetime
    home: str
    away: str
    home_goals: int
    away_goals: int
    tournament: str
    neutral: bool | None
    match_id: int | None = None

    def __post_init__(self) -> None:
        if self.kickoff.utcoffset() != timedelta(0) or self.available_at.utcoffset() != timedelta(0):
            raise ValueError("Las fechas internacionales deben ser UTC")
        if self.available_at <= self.kickoff or min(self.home_goals, self.away_goals) < 0:
            raise ValueError("Disponibilidad o marcador internacional inválidos")


class TeamNames:
    def __init__(self) -> None:
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        self.names = {normalize_name(name): name for name in catalog["teams"]}
        aliases = yaml.safe_load(ALIASES.read_text(encoding="utf-8")).get("international", {})
        self.aliases = {normalize_name(name): target for name, target in aliases.items()}
        self.clubs = {normalize_name(name) for name in catalog["excluded_clubs"]}

    def excluded(self, name: str) -> bool:
        return bool(EXCLUDED.search(name)) or normalize_name(name) in self.clubs

    def canonical(self, name: str) -> str | None:
        if self.excluded(name):
            return None
        normalized = normalize_name(name)
        target = self.aliases.get(normalized, name)
        canonical = self.names.get(normalize_name(target))
        if canonical is None:
            raise ValueError(f"Selección absoluta sin alias/catálogo: {name}")
        return canonical


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def refresh_results(force: bool = False) -> Path:
    metadata = RAW.with_suffix(".json")
    try:
        meta = json.loads(metadata.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    checked = meta.get("checked_at", RAW.stat().st_mtime if RAW.exists() else 0)
    if RAW.exists() and not force and time.time() - checked < 24 * 3600:
        return RAW
    headers = {key: meta[value] for key, value in (("If-None-Match", "etag"), ("If-Modified-Since", "modified"))
               if RAW.exists() and meta.get(value)}
    try:
        response = requests.get(URL, headers=headers, timeout=30)
        if response.status_code != 304:
            response.raise_for_status()
            if not RAW.exists() or RAW.read_bytes() != response.content:
                atomic_write(RAW, response.content)
            meta.update(etag=response.headers.get("ETag"), modified=response.headers.get("Last-Modified"))
        elif not RAW.exists():
            raise ValueError("Respuesta 304 sin CSV local")
        meta.update(checked_at=time.time(), sha256=hashlib.sha256(RAW.read_bytes()).hexdigest(), source=URL)
        atomic_write(metadata, json.dumps(meta).encode())
    except (requests.RequestException, ValueError):
        if not RAW.exists():
            raise
        log.warning("Fuente internacional sin respuesta; se conserva el CSV local")
    return RAW


def read_results(path: Path = RAW, names: TeamNames | None = None) -> list[InternationalMatch]:
    names = names or TeamNames()
    matches = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            home, away = names.canonical(row["home_team"]), names.canonical(row["away_team"])
            if home is None or away is None:
                continue
            day = datetime.fromisoformat(row["date"]).replace(tzinfo=timezone.utc)
            hg, ag = int(row["home_score"]), int(row["away_score"])
            if min(hg, ag) < 0 or row["neutral"].upper() not in {"TRUE", "FALSE"}:
                raise ValueError("Marcador o neutralidad internacional inválidos")
            # Sin hora ni zona en CSV: no se permite usar el resultado hasta dos días UTC después.
            matches.append(InternationalMatch(day, day + timedelta(days=2), home, away, hg, ag,
                                               row["tournament"], row["neutral"].upper() == "TRUE"))
    return sorted(matches, key=lambda match: (match.kickoff, match.home, match.away))


def neutral_policy(code: str, round_name: str | None = None) -> bool | None:
    """Eliminatorias y fase regular UNL tienen local; sin sede verificable no se aplica ventaja local."""
    if code.startswith("WCQ_") or (code == "UNL" and not re.search(r"final|semi", round_name or "", re.I)):
        return False
    return None


def supplement(conn: sqlite3.Connection, matches: list[InternationalMatch],
               names: TeamNames) -> list[InternationalMatch]:
    last = max(match.kickoff for match in matches)
    known = {(m.kickoff.date(), m.home, m.away, m.home_goals, m.away_goals) for m in matches}
    rows = conn.execute("""SELECT m.id,m.kickoff_utc,m.home_goals,m.away_goals,m.round,c.code,c.name tournament,
        h.name home,a.name away FROM matches m JOIN competitions c ON c.id=m.competition_id
        JOIN teams h ON h.id=m.home_team_id JOIN teams a ON a.id=m.away_team_id
        WHERE c.type='international' AND m.status='finished' AND m.home_goals IS NOT NULL
          AND m.away_goals IS NOT NULL AND m.kickoff_utc >= ? ORDER BY m.kickoff_utc,m.id""",
        ((last + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),))
    extra = []
    for row in rows:
        home, away = names.canonical(row["home"]), names.canonical(row["away"])
        if home is None or away is None:
            continue
        kickoff = datetime.fromisoformat(row["kickoff_utc"].replace("Z", "+00:00"))
        if any((kickoff.date() + timedelta(days=offset), home, away, row["home_goals"], row["away_goals"]) in known
               for offset in (-1, 0, 1)):
            continue  # Una fecha local del CSV puede ser el día anterior al UTC guardado en DB.
        extra.append(InternationalMatch(kickoff, kickoff + timedelta(hours=3), home, away,
                                        row["home_goals"], row["away_goals"], row["tournament"],
                                        neutral_policy(row["code"], row["round"]), row["id"]))
    return sorted([*matches, *extra], key=lambda match: (match.kickoff, match.home, match.away))


def audit_names(conn: sqlite3.Connection, names: TeamNames) -> dict[str, int]:
    rows = conn.execute("""SELECT DISTINCT t.name FROM teams t JOIN matches m ON t.id IN
        (m.home_team_id,m.away_team_id) JOIN competitions c ON c.id=m.competition_id WHERE c.type='international'""")
    resolved = excluded = 0
    for row in rows:
        if names.canonical(row[0]) is None:
            excluded += 1
        else:
            resolved += 1
    return {"resolved": resolved, "excluded": excluded}
