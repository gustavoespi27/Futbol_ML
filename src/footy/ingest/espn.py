"""Calendario, horarios, marcadores (también en vivo) y tiros desde el endpoint público de ESPN.

No pide clave ni tiene cuota diaria, así que API-Football queda para lo que solo él entrega: cuotas pre-partido.
El endpoint no está documentado oficialmente: si deja de responder, la tarea diaria sigue con el calendario por
fecha de API-Football y nada se cae. Se consulta con moderación (un pedido por liga y mes en la sincronización, y en
vivo solo las ligas con partidos en juego).

- Calendario: `/{liga}/scoreboard?dates=AAAAMM` trae el mes completo de una liga (el rango "AAAAMMDD-AAAAMMDD" no
  funciona). Cubre fechas futuras, a diferencia del plan gratuito de API-Football (solo hasta mañana).
- En vivo: `/{liga}/scoreboard?dates=AAAAMMDD` con marcador y minuto de juego.
- Tiros: `/{liga}/summary?event=ID` (boxscore) con tiros y tiros al arco de cada equipo.

Los equipos se enlazan por id de ESPN (alias `espn`). Un id nuevo se enlaza con el partido que ya existe a la misma
hora en la misma competición (verificado: 300 de 300 partidos de una semana) o, si el partido aún no existe, por
nombre entre los equipos de esa competición.
"""

import difflib
import logging
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from footy import config
from footy.db import repository as repo
from footy.ingest.api_football import INTERNATIONAL_REGIONS

SOURCE = "espn"
BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer"
ESPN_TZ = ZoneInfo("America/New_York")      # `dates=AAAAMMDD` agrupa por día de la costa este de EE. UU.
SAME_TIME = timedelta(minutes=15)           # mismo partido en otra fuente: inicio a menos de esto
LIVE_BEFORE, LIVE_AFTER = timedelta(minutes=5), timedelta(hours=3)

log = logging.getLogger(__name__)


class EspnUnavailable(RuntimeError):
    """ESPN no responde (red, timeout, 5xx o respuesta que no es JSON)."""


def slugs() -> dict[str, str]:
    """Competiciones con liga de ESPN configurada (`espn:` en settings.yaml) -> slug. Primero las ligas, después las
    copas y al final las selecciones: así un club ya tiene su id de ESPN (de su liga) cuando aparece en una copa."""
    order = {"league": 0, "cup": 1, "international": 2}
    comps = config.settings()["competitions"]
    return {c: v["espn"] for c, v in sorted(comps.items(), key=lambda kv: order.get(kv[1]["type"], 3)) if v.get("espn")}


class Espn:
    def __init__(self, session: requests.Session | None = None, min_interval: float = 0.25):
        if session is None:
            retry = Retry(total=2, backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504),
                          allowed_methods=frozenset({"GET"}), raise_on_status=False)
            session = requests.Session()
            session.mount("https://", HTTPAdapter(max_retries=retry))
            session.headers["User-Agent"] = "Futbol_ML/1.0 (uso personal)"
        self.session, self.min_interval, self._last = session, min_interval, 0.0

    def _get(self, path: str, **params) -> dict:
        wait = self.min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        try:
            r = self.session.get(f"{BASE_URL}/{path}", params=params, timeout=30)
            if r.status_code >= 500:
                raise EspnUnavailable(f"{path} {params}: HTTP {r.status_code}")
            if r.status_code >= 400:                         # liga o fecha inválida: no hay nada que traer
                return {}
            return r.json()
        except (requests.RequestException, ValueError) as e:
            raise EspnUnavailable(f"{path} {params}: {e}") from e

    def scoreboard(self, slug: str, dates: str) -> list[dict]:
        return self._get(f"{slug}/scoreboard", dates=dates, limit=500).get("events", [])

    def summary(self, slug: str, event_id: str) -> dict:
        return self._get(f"{slug}/summary", event=event_id)


# --- parseo -----------------------------------------------------------------

def map_status(status: dict) -> str:
    t = status["type"]
    name = t.get("name", "")
    if "POSTPONED" in name:
        return "postponed"
    if any(w in name for w in ("CANCELED", "CANCELLED", "ABANDONED", "FORFEIT")):
        return "cancelled"
    if t.get("state") == "post":
        return "finished" if t.get("completed") else "postponed"
    return "live" if t.get("state") == "in" else "scheduled"


def _sides(ev: dict) -> tuple[dict, dict]:
    comp = ev["competitions"][0]["competitors"]
    return (next(c for c in comp if c["homeAway"] == "home"), next(c for c in comp if c["homeAway"] == "away"))


def _goals(side: dict) -> int | None:
    try:
        return int(side["score"])
    except (KeyError, TypeError, ValueError):
        return None


def final_goals(ev: dict) -> tuple[int | None, int | None]:
    """Resultado a los 90' (como guarda la base). Con alargue o penales ESPN entrega el marcador final: se usan los
    dos primeros tiempos si vienen; si no, se deja vacío y lo completa API-Football."""
    home, away = _sides(ev)
    if any(w in ev["status"]["type"].get("name", "") for w in ("AET", "PEN", "EXTRA", "SHOOTOUT")):
        def ninety(side):
            ls = side.get("linescores") or []
            return int(sum(float(p["value"]) for p in ls[:2])) if len(ls) >= 2 else None
        return ninety(home), ninety(away)
    return _goals(home), _goals(away)


def kickoff_iso(ev: dict) -> str:
    return repo.to_iso(datetime.fromisoformat(ev["date"].replace("Z", "+00:00")))


# --- equipos ----------------------------------------------------------------

def _similar(a: str, b: str) -> float:
    ca, cb = repo._core(a), repo._core(b)
    if ca and cb and (ca <= cb or cb <= ca):
        return 1.0
    return difflib.SequenceMatcher(None, repo.normalize_name(a), repo.normalize_name(b)).ratio()


def _variants(team: dict, short: bool = True) -> list[str]:
    """Formas del nombre que entrega ESPN ("Atlético Tucumán", "Atl Tucumán", "CAT"), pasadas por los alias
    manuales de ESPN y, si no hay, por los de API-Football (los dos usan nombres reales parecidos). Sin `short`, solo
    los nombres completos: el corto de "Red Star Belgrade" es "Red Star", que es otro club (Francia)."""
    manual = repo._manual_aliases()
    names = [team.get(k) for k in ("displayName", "name", "location")]
    if short:
        names.append(team.get("shortDisplayName"))
        if len(team.get("abbreviation") or "") >= 3:
            names.append(team["abbreviation"])
    out = []
    for n in filter(None, names):
        for v in (manual.get(SOURCE, {}).get(n), manual.get("api_football", {}).get(n), n):
            if v and v not in out:
                out.append(v)
    return out


def _flat(name: str) -> str:
    return repo.normalize_name(name).replace(" ", "")


# Niveles de confianza para enlazar por nombre, del más estricto al más tolerante. En cada nivel se exige un único
# candidato; si hay varios, no se adivina ("Gimnasia" calza con Gimnasia L.P. y con Gimnasia Mendoza).
TIERS = (
    lambda v, n: repo.normalize_name(v) == repo.normalize_name(n),
    lambda v, n: _flat(v) == _flat(n),                                   # "Gimnasia LP" ~ "Gimnasia L.P."
    lambda v, n: bool(repo._core(v)) and repo._core(v) == repo._core(n),  # "Estudiantes de Río Cuarto"
    lambda v, n: _similar(v, n) >= 0.85,
)


def _without_espn_id(conn, cands) -> list:
    """ESPN usa un id por club: un equipo que ya tiene id de ESPN es otro club aunque el nombre sea idéntico
    ("River Plate" de Uruguay en la Libertadores no es el River Plate argentino, "Liverpool" de Montevideo no es el
    inglés)."""
    taken = {r[0] for r in conn.execute("SELECT DISTINCT team_id FROM team_aliases WHERE source = ?", (SOURCE,))}
    return [r for r in cands if r["id"] not in taken]


def _pick(cands, variants: list[str], tiers=TIERS) -> int | None:
    for test in tiers:
        hits = {r["id"] for r in cands for v in variants if test(v, r["name"])}
        if hits:
            return hits.pop() if len(hits) == 1 else None
    return None


def _known(conn, team: dict) -> int | None:
    row = conn.execute("SELECT team_id FROM team_aliases WHERE source = ? AND alias = ?",
                       (SOURCE, str(team["id"]))).fetchone()
    return row["team_id"] if row else None


def _alias(conn, team: dict, team_id: int) -> int:
    conn.execute("INSERT OR IGNORE INTO team_aliases (source, alias, team_id) VALUES (?, ?, ?)",
                 (SOURCE, str(team["id"]), team_id))
    return team_id


def _same_time_match(conn, comp_id: int, kickoff: str, home: dict, away: dict, hid, aid):
    """El partido que otra fuente ya guardó a la misma hora en la misma competición. Se elige el de nombres más
    parecidos (los dos equipos), solo si se distingue con claridad del segundo mejor."""
    k = repo.from_iso(kickoff)
    rows = conn.execute(
        """SELECT m.id, m.home_team_id, m.away_team_id, th.name AS h, ta.name AS a FROM matches m
           JOIN teams th ON th.id = m.home_team_id JOIN teams ta ON ta.id = m.away_team_id
           WHERE m.competition_id = ? AND m.kickoff_utc BETWEEN ? AND ?
             AND NOT EXISTS (SELECT 1 FROM match_sources s WHERE s.match_id = m.id AND s.source = ?)""",
        (comp_id, repo.to_iso(k - SAME_TIME), repo.to_iso(k + SAME_TIME), SOURCE)).fetchall()
    scored = []
    for r in rows:
        if (hid and hid != r["home_team_id"]) or (aid and aid != r["away_team_id"]):
            continue
        sh = 1.0 if hid else max(_similar(v, r["h"]) for v in _variants(home))
        sa = 1.0 if aid else max(_similar(v, r["a"]) for v in _variants(away))
        scored.append((min(sh, sa), r))
    scored.sort(key=lambda x: -x[0])
    if scored and scored[0][0] >= 0.4 and (len(scored) == 1 or scored[1][0] < scored[0][0] - 0.1):
        return scored[0][1]
    return None


def _competition_teams(conn, codes: list[str]) -> list[sqlite3.Row]:
    since = repo.to_iso(datetime.now(timezone.utc) - timedelta(days=730))
    marks = ",".join("?" * len(codes))
    return conn.execute(
        f"""WITH ids AS (
              SELECT m.home_team_id AS id FROM matches m JOIN competitions c ON c.id = m.competition_id
              WHERE c.code IN ({marks}) AND m.kickoff_utc >= ?
              UNION
              SELECT m.away_team_id FROM matches m JOIN competitions c ON c.id = m.competition_id
              WHERE c.code IN ({marks}) AND m.kickoff_utc >= ?)
            SELECT t.id, t.name FROM ids JOIN teams t ON t.id = ids.id""",
        (*codes, since, *codes, since)).fetchall()


def _link_team(conn, code: str, comp: dict, team: dict) -> int:
    """Equipo con id de ESPN nuevo y sin partido de otra fuente a la misma hora."""
    variants = _variants(team)
    name = variants[0]
    country = comp.get("country") or "unknown"
    if comp["type"] == "international":
        return repo.resolve_team(conn, SOURCE, str(team["id"]), name, "World")
    if comp["type"] == "cup" and country in INTERNATIONAL_REGIONS:
        # Copa internacional: las ligas se sincronizan antes, así que un club de liga seguida ya tiene su id de
        # ESPN. Un id nuevo es casi siempre de una liga que no seguimos: nombres completos y, como máximo, las mismas
        # palabras clave ("Braga" ~ "Sp Braga"); nada de subconjuntos ("Lincoln Red Imps" no es Lincoln City).
        cands = conn.execute("SELECT id, name FROM teams WHERE country NOT IN ('World', 'unknown')").fetchall()
        match = _pick(_without_espn_id(conn, cands), _variants(team, short=False), TIERS[:3])
        if match is not None:
            return _alias(conn, team, match)
        return repo.resolve_team(conn, SOURCE, str(team["id"]), name, "unknown")
    codes = [code]
    if comp["type"] == "cup":                       # copa nacional: equipos de las ligas del país
        codes += [c for c, v in config.settings()["competitions"].items()
                  if v["type"] == "league" and v.get("country") == country]
    match = _pick(_without_espn_id(conn, _competition_teams(conn, codes)), variants)
    if match is not None:
        return _alias(conn, team, match)
    return repo.resolve_team(conn, SOURCE, str(team["id"]), name, country)


# --- guardado ---------------------------------------------------------------

def _season(conn, comp_id: int, ev: dict) -> str:
    """Temporada para un partido nuevo, con el mismo formato que los partidos de football-data de la competición
    ("2026/2027" o "2026"), para que los modelos agrupen bien; si no hay, el año de ESPN."""
    row = conn.execute(
        """SELECT m.season FROM matches m JOIN match_sources s ON s.match_id = m.id
           WHERE m.competition_id = ? AND s.source LIKE 'football_data%' ORDER BY m.kickoff_utc DESC LIMIT 1""",
        (comp_id,)).fetchone() or conn.execute(
        "SELECT season FROM matches WHERE competition_id = ? ORDER BY kickoff_utc DESC LIMIT 1", (comp_id,)).fetchone()
    return row[0] if row else str(ev.get("season", {}).get("year", ""))


def store_event(conn: sqlite3.Connection, code: str, ev: dict) -> int:
    """Guarda (o actualiza) un partido de ESPN y su marcador en vivo. Devuelve el match_id."""
    comp = config.settings()["competitions"][code]
    comp_id = repo.competition_id(conn, code)
    home, away = _sides(ev)
    kickoff = kickoff_iso(ev)
    hid, aid = _known(conn, home["team"]), _known(conn, away["team"])
    if hid is None or aid is None:
        m = _same_time_match(conn, comp_id, kickoff, home["team"], away["team"], hid, aid)
        if m is not None:
            hid = hid or _alias(conn, home["team"], m["home_team_id"])
            aid = aid or _alias(conn, away["team"], m["away_team_id"])
    hid = hid or _link_team(conn, code, comp, home["team"])
    aid = aid or _link_team(conn, code, comp, away["team"])

    status = map_status(ev["status"])
    hg, ag = final_goals(ev) if status == "finished" else (None, None)
    mid = repo.upsert_match(conn, source=SOURCE, source_match_id=str(ev["id"]), competition_id=comp_id,
                            season=_season(conn, comp_id, ev), kickoff_utc=kickoff, home_team_id=hid,
                            away_team_id=aid, status=status, home_goals=hg, away_goals=ag)
    if status == "live" and _goals(home) is not None:
        st = ev["status"]
        clock = st["type"].get("shortDetail") if st["type"].get("name") == "STATUS_HALFTIME" else st.get("displayClock")
        conn.execute(
            """INSERT INTO live_scores (match_id, home_goals, away_goals, clock, updated_at) VALUES (?, ?, ?, ?, ?)
               ON CONFLICT (match_id) DO UPDATE SET home_goals = excluded.home_goals,
                   away_goals = excluded.away_goals, clock = excluded.clock, updated_at = excluded.updated_at""",
            (mid, _goals(home), _goals(away), clock, repo.utc_now()))
    else:
        conn.execute("DELETE FROM live_scores WHERE match_id = ?", (mid,))
    return mid


def mark_synced(conn, name: str) -> None:
    conn.execute("INSERT INTO sync_log (name, synced_at) VALUES (?, ?) "
                 "ON CONFLICT (name) DO UPDATE SET synced_at = excluded.synced_at", (name, repo.utc_now()))


# --- tareas -----------------------------------------------------------------

def sync_calendar(conn: sqlite3.Connection, client: Espn, days_back: int = 2, days_ahead: int = 7) -> dict:
    """Partidos de las ligas con slug de ESPN entre hace `days_back` días y dentro de `days_ahead`: calendario nuevo,
    horarios cambiados y resultados. Un pedido por liga y mes."""
    now = datetime.now(timezone.utc)
    lo, hi = now - timedelta(days=days_back), now + timedelta(days=days_ahead)
    months = sorted({d.strftime("%Y%m") for d in (lo.astimezone(ESPN_TZ), hi.astimezone(ESPN_TZ))})
    out = {"leagues": 0, "matches": 0, "failed": []}
    for code, slug in slugs().items():
        try:
            events = [e for m in months for e in client.scoreboard(slug, m)]
        except EspnUnavailable as e:
            log.warning("ESPN %s: %s", slug, e)
            out["failed"].append(code)
            if len(out["failed"]) >= 3 and not out["leagues"]:
                raise                                          # ESPN caído: no seguir golpeando
            continue
        n = 0
        for ev in events:
            if lo <= repo.from_iso(kickoff_iso(ev)) <= hi:
                try:
                    store_event(conn, code, ev)
                    n += 1
                except (KeyError, StopIteration, ValueError):
                    log.exception("ESPN %s: evento %s con datos inesperados, se omite", slug, ev.get("id"))
        conn.commit()
        out["leagues"] += 1
        out["matches"] += n
    mark_synced(conn, "espn_calendar")
    conn.commit()
    return out


def backfill_months(conn: sqlite3.Connection, client: Espn, code: str, months: list[str]) -> int:
    """Historial de una competición mes a mes (`AAAAMM`): partidos terminados y sus equipos. Un pedido por mes."""
    slug, n = slugs()[code], 0
    for month in months:
        for ev in client.scoreboard(slug, month):
            try:
                store_event(conn, code, ev)
                n += 1
            except (KeyError, StopIteration, ValueError):
                log.exception("ESPN %s: evento %s con datos inesperados, se omite", slug, ev.get("id"))
        conn.commit()
    return n


def refresh_live(conn: sqlite3.Connection, client: Espn) -> int:
    """Marcadores de los partidos en juego o por empezar (ligas con slug). Sin partidos así no pide nada."""
    now = datetime.now(timezone.utc)
    codes = slugs()
    if not codes:
        return 0
    rows = conn.execute(
        f"""SELECT DISTINCT c.code, m.kickoff_utc FROM matches m JOIN competitions c ON c.id = m.competition_id
            WHERE m.status IN ('scheduled', 'live') AND m.kickoff_utc BETWEEN ? AND ?
              AND c.code IN ({",".join("?" * len(codes))})""",
        (repo.to_iso(now - LIVE_AFTER), repo.to_iso(now + LIVE_BEFORE), *codes)).fetchall()
    days = {(r["code"], repo.from_iso(r["kickoff_utc"]).astimezone(ESPN_TZ).strftime("%Y%m%d")) for r in rows}
    n = 0
    for code, day in sorted(days):
        for ev in client.scoreboard(codes[code], day):
            k = repo.from_iso(kickoff_iso(ev))
            if now - LIVE_AFTER <= k <= now + LIVE_BEFORE:
                store_event(conn, code, ev)
                n += 1
        conn.commit()
    if days:
        mark_synced(conn, "espn_live")
        conn.commit()
    return n


SHOT_STATS = {"totalShots": "total_shots", "shotsOnTarget": "shots_on_goal"}   # mismos nombres que usan los modelos


def fetch_stats(conn: sqlite3.Connection, client: Espn, codes: list[str], days: int = 10, limit: int = 200) -> int:
    """Tiros de los partidos terminados de `codes` (ligas cuyos tiros no vienen en el CSV de football-data)."""
    if not codes:
        return 0
    since = repo.to_iso(datetime.now(timezone.utc) - timedelta(days=days))
    rows = conn.execute(
        f"""SELECT s.source_match_id, s.match_id, c.code FROM match_sources s
            JOIN matches m ON m.id = s.match_id JOIN competitions c ON c.id = m.competition_id
            WHERE s.source = ? AND s.details_fetched_at IS NULL AND m.status = 'finished' AND m.kickoff_utc >= ?
              AND c.code IN ({",".join("?" * len(codes))})
            ORDER BY m.kickoff_utc DESC LIMIT ?""", (SOURCE, since, *codes, limit)).fetchall()
    sl, n = slugs(), 0
    for r in rows:
        data = client.summary(sl[r["code"]], r["source_match_id"])
        now = repo.utc_now()
        for t in (data.get("boxscore") or {}).get("teams", []):
            team_id = _known(conn, t["team"])
            if team_id is None:
                continue
            for s in t.get("statistics", []):
                if s.get("name") in SHOT_STATS:
                    try:
                        value = float(s["displayValue"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    conn.execute("""INSERT OR REPLACE INTO team_match_stats (match_id, team_id, stat, value, source,
                                    captured_at) VALUES (?, ?, ?, ?, ?, ?)""",
                                 (r["match_id"], team_id, SHOT_STATS[s["name"]], value, SOURCE, now))
        conn.execute("UPDATE match_sources SET details_fetched_at = ? WHERE source = ? AND source_match_id = ?",
                     (now, SOURCE, r["source_match_id"]))
        conn.commit()
        n += 1
    return n
