"""Operaciones de escritura/lectura comunes sobre la base de datos.

Todas las escrituras son idempotentes: volver a ingerir la misma fuente
actualiza filas existentes en vez de duplicarlas.
"""

import re
import sqlite3
import unicodedata
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import yaml

from footy import config

MATCH_LINK_WINDOW = timedelta(hours=36)  # tolerancia para enlazar el mismo partido entre fuentes


def utc_now() -> str:
    return to_iso(datetime.now(timezone.utc))


def to_iso(ts: datetime) -> str:
    if ts.tzinfo is None:
        raise ValueError("Se requiere un datetime con zona horaria")
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def from_iso(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


# --- Competiciones ---------------------------------------------------------

def sync_competitions(conn: sqlite3.Connection) -> None:
    """Competiciones de settings.yaml + ligas de config/football_data.yaml."""
    comps = dict(config.settings()["competitions"])
    with open(config.PROJECT_ROOT / "config" / "football_data.yaml", encoding="utf-8") as f:
        fd = yaml.safe_load(f)
    for group in ("extra", "main"):
        for code, c in fd[group].items():
            comps.setdefault(code, {**c, "type": "league"})
    for code, c in comps.items():
        conn.execute(
            """INSERT INTO competitions (code, name, country, type) VALUES (?, ?, ?, ?)
               ON CONFLICT (code) DO UPDATE SET name = excluded.name,
                   country = excluded.country, type = excluded.type""",
            (code, c["name"], c.get("country"), c["type"]),
        )


def competition_id(conn: sqlite3.Connection, code: str) -> int:
    row = conn.execute("SELECT id FROM competitions WHERE code = ?", (code,)).fetchone()
    if row is None:
        raise KeyError(f"Competición desconocida: {code} (¿falta sync_competitions?)")
    return row["id"]


# --- Equipos ---------------------------------------------------------------

# Letras que NFKD no descompone en base + acento (se perderían al pasar a ASCII).
_NON_DECOMPOSABLE = str.maketrans({"ı": "i", "ø": "o", "Ø": "O", "æ": "ae", "ß": "ss", "đ": "d", "ł": "l", "Ł": "L"})
# Palabras que no identifican al club (prefijos/sufijos societarios).
_FILLER = {"fc", "sc", "cf", "ac", "as", "ssc", "ss", "sk", "fk", "cp", "sp", "sad", "calcio", "club", "cd", "ud",
           "afc", "if", "bk", "jk", "spor", "futebol", "clube", "de", "kulubu"}


def normalize_name(name: str) -> str:
    """'Unión La Calera' -> 'union la calera'. Sirve para enlazar fuentes sin falsos positivos."""
    s = name.translate(_NON_DECOMPOSABLE)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", " ", s.lower())
    return s.strip()


@lru_cache
def _manual_aliases() -> dict:
    """config/team_aliases.yaml: {fuente: {nombre_en_fuente: nombre_canónico}}."""
    path = config.PROJECT_ROOT / "config" / "team_aliases.yaml"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def resolve_team(conn: sqlite3.Connection, source: str, alias: str, name: str, country: str) -> int:
    """Devuelve el team_id canónico para (fuente, alias), creándolo si no existe.

    Orden: alias ya conocido -> alias manual en config -> mismo nombre normalizado
    en el mismo país -> equipo nuevo.
    """
    row = conn.execute(
        "SELECT team_id FROM team_aliases WHERE source = ? AND alias = ?", (source, alias)
    ).fetchone()
    if row:
        return row["team_id"]

    canonical = _manual_aliases().get(source, {}).get(name, name)
    target = normalize_name(canonical)
    team_id = None
    for t in conn.execute("SELECT id, name FROM teams WHERE country = ?", (country,)):
        if normalize_name(t["name"]) == target:
            team_id = t["id"]
            break
    if team_id is None:
        team_id = conn.execute(
            "INSERT INTO teams (name, country) VALUES (?, ?)", (canonical, country)
        ).lastrowid

    conn.execute(
        "INSERT INTO team_aliases (source, alias, team_id) VALUES (?, ?, ?)", (source, alias, team_id)
    )
    return team_id


def _core(name: str) -> set[str]:
    toks = []
    for t in normalize_name(name).split():
        if len(t) > 5 and t.endswith("spor"):          # Amedspor ~ Amed, Erzurumspor FK ~ Erzurum
            t = t[:-4]
        if t not in _FILLER and len(t) > 1:
            toks.append(t)
    return set(toks)


def fuzzy_team_match(conn: sqlite3.Connection, name: str, competition_code: str, years: int = 3) -> int | None:
    """Equipo de football-data de la misma competición cuyo nombre coincide sin prefijos/sufijos
    ("SC Braga" ~ "Sp Braga", "Hellas Verona" ~ "Verona"). Devuelve None si no hay uno único."""
    import difflib

    since = to_iso(datetime.now(timezone.utc) - timedelta(days=365 * years))
    cands = conn.execute(
        """SELECT DISTINCT t.id, t.name FROM teams t
           JOIN matches m ON t.id IN (m.home_team_id, m.away_team_id)
           JOIN competitions c ON c.id = m.competition_id
           JOIN team_aliases a ON a.team_id = t.id AND a.source = 'football_data'
           WHERE c.code = ? AND m.kickoff_utc >= ?""", (competition_code, since)).fetchall()
    core = _core(name)
    if not core:
        return None
    hits = []
    for c in cands:
        other = _core(c["name"])
        if not other:
            continue
        joined_a, joined_b = " ".join(sorted(core)), " ".join(sorted(other))
        if core <= other or other <= core or difflib.SequenceMatcher(None, joined_a, joined_b).ratio() >= 0.85:
            hits.append(c["id"])
    return hits[0] if len(hits) == 1 else None


def merge_teams(conn: sqlite3.Connection, from_id: int, into_id: int) -> None:
    """Fusiona un equipo duplicado en otro, re-apuntando todas sus referencias."""
    for table, col in (("team_aliases", "team_id"), ("matches", "home_team_id"),
                       ("matches", "away_team_id"), ("team_match_stats", "team_id"),
                       ("lineups", "team_id"), ("player_match_stats", "team_id"),
                       ("injuries", "team_id")):
        conn.execute(f"UPDATE {table} SET {col} = ? WHERE {col} = ?", (into_id, from_id))
    conn.execute("DELETE FROM teams WHERE id = ?", (from_id,))


# --- Partidos --------------------------------------------------------------

def upsert_match(
    conn: sqlite3.Connection,
    *,
    source: str,
    source_match_id: str,
    competition_id: int,
    season: str,
    kickoff_utc: str,
    home_team_id: int,
    away_team_id: int,
    status: str,
    home_goals: int | None = None,
    away_goals: int | None = None,
    round: str | None = None,
    venue: str | None = None,
) -> int:
    """Inserta o actualiza un partido y devuelve su id.

    Si la fuente no lo conoce aún, intenta enlazarlo a un partido existente de otra
    fuente (mismos equipos y competición, kickoff dentro de MATCH_LINK_WINDOW).
    """
    now = utc_now()
    row = conn.execute(
        "SELECT match_id FROM match_sources WHERE source = ? AND source_match_id = ?",
        (source, source_match_id),
    ).fetchone()
    match_id = row["match_id"] if row else _find_same_match(
        conn, competition_id, home_team_id, away_team_id, kickoff_utc
    )

    if match_id is None:
        match_id = conn.execute(
            """INSERT INTO matches (competition_id, season, round, kickoff_utc, home_team_id,
                   away_team_id, status, home_goals, away_goals, venue, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (competition_id, season, round, kickoff_utc, home_team_id, away_team_id,
             status, home_goals, away_goals, venue, now, now),
        ).lastrowid
    else:
        conn.execute(
            """UPDATE matches SET kickoff_utc = ?, status = ?,
                   home_goals = COALESCE(?, home_goals), away_goals = COALESCE(?, away_goals),
                   round = COALESCE(?, round), venue = COALESCE(?, venue), updated_at = ?
               WHERE id = ?""",
            (kickoff_utc, status, home_goals, away_goals, round, venue, now, match_id),
        )

    conn.execute(
        "INSERT OR IGNORE INTO match_sources (source, source_match_id, match_id) VALUES (?, ?, ?)",
        (source, source_match_id, match_id),
    )
    return match_id


def _find_same_match(conn, competition_id, home_team_id, away_team_id, kickoff_utc) -> int | None:
    k = from_iso(kickoff_utc)
    row = conn.execute(
        """SELECT id FROM matches
           WHERE competition_id = ? AND home_team_id = ? AND away_team_id = ?
             AND kickoff_utc BETWEEN ? AND ?""",
        (competition_id, home_team_id, away_team_id,
         to_iso(k - MATCH_LINK_WINDOW), to_iso(k + MATCH_LINK_WINDOW)),
    ).fetchone()
    return row["id"] if row else None


# --- Cuotas, estadísticas, jugadores ---------------------------------------

def insert_odds(conn: sqlite3.Connection, rows: list[dict]) -> int:
    """rows: dicts con match_id, source, bookmaker, market, line, selection, price, captured_at, is_closing."""
    before = conn.total_changes
    conn.executemany(
        """INSERT OR IGNORE INTO odds (match_id, source, bookmaker, market, line, selection,
               price, captured_at, is_closing)
           VALUES (:match_id, :source, :bookmaker, :market, :line, :selection,
               :price, :captured_at, :is_closing)""",
        rows,
    )
    return conn.total_changes - before


def get_or_create_player(conn: sqlite3.Connection, source: str, source_player_id: str, name: str) -> int:
    row = conn.execute(
        "SELECT id FROM players WHERE source = ? AND source_player_id = ?", (source, source_player_id)
    ).fetchone()
    if row:
        return row["id"]
    return conn.execute(
        "INSERT INTO players (name, source, source_player_id) VALUES (?, ?, ?)",
        (name, source, source_player_id),
    ).lastrowid
