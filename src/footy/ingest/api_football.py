"""Cliente de API-Football (v3) y parsers hacia la base de datos.

Restricciones del plan Free (verificadas 2026-10-07, ver docs/decisiones.md):
- 100 peticiones/día, 10/minuto.
- `season` solo 2022-2024; `date` solo ayer..mañana (UTC); `ids` bloqueado.
- `fixtures?id=` funciona para cualquier temporada y trae alineaciones,
  estadísticas, jugadores y eventos en una sola petición.
"""

import json
import logging
import re
import sqlite3
import time
from datetime import datetime

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from footy import config
from footy.db import repository as repo

SOURCE = "api_football"
BASE_URL = "https://v3.football.api-sports.io"

log = logging.getLogger(__name__)

STATUS_MAP = {
    "TBD": "scheduled", "NS": "scheduled",
    "1H": "live", "HT": "live", "2H": "live", "ET": "live", "BT": "live", "P": "live",
    "SUSP": "live", "INT": "live", "LIVE": "live",
    "FT": "finished", "AET": "finished", "PEN": "finished",
    "PST": "postponed",
    "CANC": "cancelled", "ABD": "cancelled", "AWD": "cancelled", "WO": "cancelled",
}


class ApiError(RuntimeError):
    """La API respondió con un error para esta petición (parámetros, partido inexistente...): se salta y se sigue."""


class BudgetExhausted(RuntimeError):
    """No quedan peticiones del día (reserva alcanzada o cuota agotada en la API): la recolección se detiene."""


class ApiUnavailable(RuntimeError):
    """La API no responde (red caída, timeout o error 5xx tras los reintentos): la recolección se detiene."""


RETRY_STATUS = (429, 500, 502, 503, 504)
RATE_LIMIT_WAIT = 10.0       # segundos de espera si la API avisa en el cuerpo que se superó el límite por minuto


def make_session(key: str) -> requests.Session:
    """Sesión HTTP con reintentos automáticos y backoff exponencial (1 s, 2 s, 4 s) ante fallas transitorias:
    errores de conexión, timeouts de lectura y respuestas 429/500/502/503/504 (respeta Retry-After)."""
    retry = Retry(total=3, connect=3, read=3, status=3, backoff_factor=1, status_forcelist=RETRY_STATUS,
                  allowed_methods=frozenset({"GET"}), respect_retry_after_header=True, raise_on_status=False)
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers["x-apisports-key"] = key
    return session


def _quota_error(errors) -> bool:
    """API-Football informa la cuota diaria agotada con HTTP 200 y errors = {"requests": "You have reached the
    request limit for the day..."}."""
    return isinstance(errors, dict) and "requests" in errors


class ApiFootball:
    def __init__(self, conn: sqlite3.Connection, key: str | None = None, session: requests.Session | None = None):
        cfg = config.settings()["api_football"]
        self.conn = conn
        self.session = session or make_session(key or config.api_football_key())
        self.reserve = cfg["reserve"]
        self.min_interval = cfg["min_seconds_between"]
        self.raw_dir = config.path("raw") / SOURCE
        self._last_call = 0.0
        self.unavailable: str | None = None
        try:
            reqs = self.status()["requests"]
            self.remaining = reqs["limit_day"] - reqs["current"]
        except (requests.RequestException, ValueError, KeyError, TypeError) as e:
            # Sin /status no se sabe cuánto queda: no se gasta nada y la tarea diaria sigue con los demás pasos.
            self.remaining = 0
            self.unavailable = f"/status no disponible: {e}"
            log.warning("API-Football no disponible, se omite la recolección: %s", e)

    def status(self) -> dict:
        """/status no consume cuota."""
        return self.session.get(f"{BASE_URL}/status", timeout=30).json()["response"]

    def get(self, endpoint: str, **params) -> dict:
        if self.unavailable:
            raise ApiUnavailable(self.unavailable)
        if self.remaining <= self.reserve:
            raise BudgetExhausted(f"Quedan {self.remaining} peticiones (reserva {self.reserve})")
        data = self._request(endpoint, params)
        if isinstance(data.get("errors"), dict) and "rateLimit" in data["errors"]:
            time.sleep(RATE_LIMIT_WAIT)                    # límite por minuto: se espera y se intenta una vez más
            data = self._request(endpoint, params)
        errors = data.get("errors") or None
        if _quota_error(errors):
            self.remaining = 0
            raise BudgetExhausted(f"Cuota diaria de API-Football agotada: {errors['requests']}")
        if errors:
            raise ApiError(f"{endpoint} {params}: {errors}")
        return data

    def _request(self, endpoint: str, params: dict) -> dict:
        """Una petición con los reintentos de la sesión; guarda la respuesta cruda y la registra en api_requests."""
        wait = self.min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()
        try:
            r = self.session.get(f"{BASE_URL}/{endpoint}", params=params, timeout=60)
        except requests.RequestException as e:
            raise ApiUnavailable(f"{endpoint} {params}: {e}") from e
        requested_at = repo.utc_now()
        try:
            data = r.json()
        except ValueError as e:                           # p. ej. página HTML de un 502 tras agotar los reintentos
            raise ApiUnavailable(f"{endpoint} {params}: HTTP {r.status_code} sin JSON") from e
        header = r.headers.get("x-ratelimit-requests-remaining")
        # El header a veces llega atrasado: se toma el valor más conservador entre él y la cuenta local.
        self.remaining = min(int(header), self.remaining - 1) if header is not None else self.remaining - 1

        self._save_raw(endpoint, params, requested_at, data)
        errors = data.get("errors") or None
        self.conn.execute(
            """INSERT INTO api_requests (source, endpoint, params, requested_at, http_status, results, errors)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (SOURCE, endpoint, json.dumps(params, sort_keys=True), requested_at,
             r.status_code, data.get("results"), json.dumps(errors) if errors else None),
        )
        self.conn.commit()
        if r.status_code >= 500:
            raise ApiUnavailable(f"{endpoint} {params}: HTTP {r.status_code}")
        return data

    def get_all_pages(self, endpoint: str, **params) -> list:
        data = self.get(endpoint, **params)
        items = list(data["response"])
        total = data.get("paging", {}).get("total", 1)
        for page in range(2, total + 1):
            items += self.get(endpoint, page=page, **params)["response"]
        return items

    def _save_raw(self, endpoint, params, requested_at, data) -> None:
        """Respuesta original para poder reprocesar sin gastar peticiones."""
        day_dir = self.raw_dir / requested_at[:10]
        day_dir.mkdir(parents=True, exist_ok=True)
        tag = "_".join(f"{k}-{v}" for k, v in sorted(params.items()))
        name = re.sub(r"[^A-Za-z0-9_.-]", "-", f"{requested_at[11:19]}_{endpoint}_{tag}")
        (day_dir / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


# --- Parsers ---------------------------------------------------------------

def competitions_by_api_id() -> dict[int, str]:
    return {
        c["api_football_id"]: code
        for code, c in config.settings()["competitions"].items()
        if "api_football_id" in c
    }


def store_fixture(conn: sqlite3.Connection, item: dict) -> int | None:
    """Guarda un fixture de /fixtures. Devuelve match_id, o None si no es de una competición seguida."""
    comp_code = competitions_by_api_id().get(item["league"]["id"])
    if comp_code is None:
        return None
    comp = config.settings()["competitions"][comp_code]
    country = comp["country"]
    fx = item["fixture"]
    status = STATUS_MAP.get(fx["status"]["short"], "scheduled")
    goals = item["score"].get("fulltime") or {}
    if goals.get("home") is None:
        goals = item["goals"]

    home = item["teams"]["home"]
    away = item["teams"]["away"]
    home_id = _resolve_api_team(conn, home, country, comp["type"], comp_code)
    away_id = _resolve_api_team(conn, away, country, comp["type"], comp_code)

    return repo.upsert_match(
        conn,
        source=SOURCE,
        source_match_id=str(fx["id"]),
        competition_id=repo.competition_id(conn, comp_code),
        season=str(item["league"]["season"]),
        kickoff_utc=repo.to_iso(datetime.fromisoformat(fx["date"])),
        home_team_id=home_id,
        away_team_id=away_id,
        status=status,
        home_goals=goals.get("home") if status == "finished" else None,
        away_goals=goals.get("away") if status == "finished" else None,
        round=item["league"].get("round"),
        venue=(fx.get("venue") or {}).get("name"),
    )


INTERNATIONAL_REGIONS = {"Europe", "South America", "World"}


def _country_league_codes(country: str) -> list[str]:
    """Ligas del país (de API-Football o de football-data), para enlazar equipos que aparecen en copas nacionales."""
    from footy.ingest.football_data import leagues as fd_leagues

    fd = fd_leagues()
    comps = config.settings()["competitions"]
    codes = [c for c, v in comps.items() if v["type"] == "league" and v["country"] == country]
    codes += [c for g in ("main", "extra") for c, v in fd[g].items() if v["country"] == country and c not in codes]
    return codes


def _resolve_api_team(conn, team: dict, country: str, comp_type: str, comp_code: str | None = None) -> int:
    alias = str(team["id"])
    known = conn.execute("SELECT 1 FROM team_aliases WHERE source = ? AND alias = ?", (SOURCE, alias)).fetchone()
    if not known and comp_type == "league" and comp_code:
        # Ligas con historial de football-data: enlazar al equipo existente aunque el nombre difiera un poco.
        canonical = repo._manual_aliases().get(SOURCE, {}).get(team["name"], team["name"])
        exact = any(repo.normalize_name(r["name"]) == repo.normalize_name(canonical)
                    for r in conn.execute("SELECT name FROM teams WHERE country = ?", (country,)))
        match = None if exact else repo.fuzzy_team_match(conn, canonical, comp_code)
        if match is not None:
            conn.execute("INSERT INTO team_aliases (source, alias, team_id) VALUES (?, ?, ?)", (SOURCE, alias, match))
            return match
    if comp_type == "international":
        # Selecciones nacionales: un equipo por nombre en el "país" World (no se mezclan con clubes).
        return repo.resolve_team(conn, SOURCE, alias, team["name"], "World")
    if comp_type == "cup" and country not in INTERNATIONAL_REGIONS:
        # Copa nacional: los equipos son del país. Se enlazan con los de sus ligas (alias conocido, emparejamiento
        # tolerante o mismo nombre) para no crear duplicados que después capturen los partidos de liga.
        if not known:
            canonical = repo._manual_aliases().get(SOURCE, {}).get(team["name"], team["name"])
            for code in _country_league_codes(country):
                match = repo.fuzzy_team_match(conn, canonical, code)
                if match is not None:
                    conn.execute("INSERT INTO team_aliases (source, alias, team_id) VALUES (?, ?, ?)",
                                 (SOURCE, alias, match))
                    return match
        return repo.resolve_team(conn, SOURCE, alias, team["name"], country)
    if comp_type == "cup":
        # En copas internacionales el país del equipo no viene en el fixture: solo enlazamos
        # por id ya conocido; si es nuevo, se crea con país 'unknown' para revisión manual.
        row = conn.execute(
            "SELECT team_id FROM team_aliases WHERE source = ? AND alias = ?", (SOURCE, alias)
        ).fetchone()
        if row:
            return row["team_id"]
        country = "unknown"
    return repo.resolve_team(conn, SOURCE, alias, team["name"], country)


def store_fixture_details(conn: sqlite3.Connection, item: dict) -> None:
    """Estadísticas, alineaciones y stats de jugadores de una respuesta de /fixtures?id=."""
    match_id = store_fixture(conn, item)
    if match_id is None:
        return
    captured_at = repo.utc_now()
    team_ids = {
        item["teams"][side]["id"]: _team_id_from_alias(conn, item["teams"][side]["id"])
        for side in ("home", "away")
    }

    def team_of(block: dict, kind: str) -> int | None:
        # La API a veces devuelve bloques con un id de equipo ajeno al partido: no adivinamos.
        team_id = team_ids.get(block["team"]["id"])
        if team_id is None:
            log.warning("fixture %s: bloque %s con equipo inesperado %s, se omite",
                        item["fixture"]["id"], kind, block["team"])
        return team_id

    for block in item.get("statistics", []):
        if (team_id := team_of(block, "statistics")) is None:
            continue
        for s in block["statistics"]:
            conn.execute(
                """INSERT OR REPLACE INTO team_match_stats
                   (match_id, team_id, stat, value, source, captured_at) VALUES (?, ?, ?, ?, ?, ?)""",
                (match_id, team_id, _snake(s["type"]), _number(s["value"]), SOURCE, captured_at),
            )

    for block in item.get("lineups", []):
        if (team_id := team_of(block, "lineups")) is None:
            continue
        for starter, key in ((1, "startXI"), (0, "substitutes")):
            for entry in block.get(key) or []:
                p = entry["player"]
                if p.get("id") is None:
                    continue
                player_id = repo.get_or_create_player(conn, SOURCE, str(p["id"]), p["name"])
                conn.execute(
                    """INSERT OR REPLACE INTO lineups (match_id, team_id, player_id, is_starter,
                           position, grid, formation, source, captured_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (match_id, team_id, player_id, starter, p.get("pos"), p.get("grid"),
                     block.get("formation"), SOURCE, captured_at),
                )

    for block in item.get("players", []):
        if (team_id := team_of(block, "players")) is None:
            continue
        for entry in block["players"]:
            p = entry["player"]
            player_id = repo.get_or_create_player(conn, SOURCE, str(p["id"]), p["name"])
            for stat, value in _flatten(entry["statistics"][0]).items():
                conn.execute(
                    """INSERT OR REPLACE INTO player_match_stats
                       (match_id, player_id, team_id, stat, value, source, captured_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (match_id, player_id, team_id, stat, value, SOURCE, captured_at),
                )

    conn.execute(
        "UPDATE match_sources SET details_fetched_at = ? WHERE source = ? AND source_match_id = ?",
        (captured_at, SOURCE, str(item["fixture"]["id"])),
    )


def odds_rows(match_id: int, item: dict, captured_at: str) -> list[dict]:
    """Convierte una respuesta de /odds a filas: 1X2, Over/Under (todas las líneas) y BTTS."""
    keep = set(config.settings()["api_football"]["bookmakers_keep"])
    rows = []
    for bm in item["bookmakers"]:
        if keep and bm["name"] not in keep:
            continue
        for bet in bm["bets"]:
            for v in bet["values"]:
                parsed = _parse_bet(bet["id"], str(v["value"]))
                price = _number(v["odd"])
                if parsed is None or price is None or price <= 1:
                    continue
                market, line, selection = parsed
                rows.append({
                    "match_id": match_id, "source": SOURCE, "bookmaker": bm["name"],
                    "market": market, "line": line, "selection": selection,
                    "price": price, "captured_at": captured_at, "is_closing": 0,
                })
    return rows


def _parse_bet(bet_id: int, value: str):
    if bet_id == 1:  # Match Winner
        sel = {"Home": "H", "Draw": "D", "Away": "A"}.get(value)
        return ("1X2", 0.0, sel) if sel else None
    if bet_id == 5:  # Goals Over/Under
        m = re.fullmatch(r"(Over|Under) (\d+(?:\.\d+)?)", value)
        return ("OU", float(m.group(2)), m.group(1).upper()) if m else None
    if bet_id == 8:  # Both Teams Score
        sel = {"Yes": "YES", "No": "NO"}.get(value)
        return ("BTTS", 0.0, sel) if sel else None
    return None


def _team_id_from_alias(conn, api_team_id: int) -> int:
    return conn.execute(
        "SELECT team_id FROM team_aliases WHERE source = ? AND alias = ?", (SOURCE, str(api_team_id))
    ).fetchone()["team_id"]


def _snake(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def _number(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).rstrip("%"))
    except ValueError:
        return None


def _flatten(d: dict, prefix: str = "") -> dict[str, float]:
    out = {}
    for k, v in d.items():
        key = f"{prefix}{_snake(k)}"
        if isinstance(v, dict):
            out.update(_flatten(v, f"{key}_"))
        else:
            num = _number(v)
            if num is not None:
                out[key] = num
    return out
