"""Avisos del vigía fuera del chat: equipos favoritos, cuotas con valor o cerca de tenerlo y combinadas.

Todo se lee de lo que el motor ya calcula (`service.current_suggestions` y el calendario): aquí no hay matemática
nueva ni LLM. El valor solo existe frente al precio justo de Pinnacle; los avisos «cerca» son informativos y nunca
sugieren un monto. Cada texto se arma con plantillas y pasa por `verify_numbers` contra sus propios `facts`.
"""

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from itertools import combinations

from footy.betting import pro
from footy_agents.calendar import local_fields
from footy_agents.grounding import verify_numbers
from footy_agents.names import normalize_name
from footy_agents.schemas import (
    DEFAULT_ALERT_TYPES,  # noqa: E402 - contrato único con las preferencias
    ToolCallRecord,
)

ALERT_TYPES = ("favorite_plays", "value_bet", "near_value", "value_combo", "near_combo")
FAVORITE_HOURS = 24            # aviso cuando juega un favorito dentro de este plazo
REMINDER_HOURS = 2             # y un recordatorio cerca del inicio
NEAR_GAP = 0.03                # «cerca de valor»: ventaja de al menos MIN_EDGE − 3 pp
REALERT_GAIN = 0.02            # se vuelve a avisar solo si la ventaja mejora 2 pp o más
MIN_LEG_PROB = 0.25            # las piernas improbables no forman combinadas «cercanas»
MAX_NEAR_COMBOS = 3
HORIZON_DAYS = 7
PRIORITY = {"favorite_reminder": 400, "value_bet": 300, "value_combo": 250, "favorite_plays": 200,
            "near_value": 150, "near_combo": 100}


@dataclass
class Notice:
    kind: str
    match_ids: tuple[int, ...]
    selection: str
    facts: dict
    text: str
    expires_at: str
    priority: int
    edge: float | None = None
    stage: str = ""
    teams: set[str] = field(default_factory=set)
    leagues: set[str] = field(default_factory=set)

    @property
    def base_key(self) -> str:
        return f"{self.kind}|{','.join(map(str, self.match_ids))}|{self.selection}|{self.stage}"


def _odds(x: float) -> str:
    return f"{x:.2f}".replace(".", ",")


def _pct(x: float) -> str:
    return f"{x * 100:.1f} %".replace(".", ",")


def _parse(kickoff: str) -> datetime:
    return datetime.fromisoformat(kickoff.replace("Z", "+00:00"))


def _verified(text: str, facts: dict) -> str:
    record = ToolCallRecord(tool_name="notice_facts", arguments={}, result=facts, success=True, execution_time_ms=0)
    if not verify_numbers(text, [record]).verified:
        raise ValueError(f"El aviso contiene cifras fuera de facts: {text}")
    return text


def _selection(row: dict, key: str) -> str:
    return {"1": row["home"], "X": "Empate", "2": row["away"]}.get(key, key)


def _match_id(row: dict) -> int | None:
    ref = str(row.get("ref", ""))
    return int(ref[2:]) if ref.startswith("m:") else None


def _base_facts(row: dict) -> dict:
    return {"home": row["home"], "away": row["away"], "league": row.get("league"),
            "league_name": row.get("league_name"), "kickoff": row["kickoff"],
            "kickoff_local": local_fields(row["kickoff"])["kickoff_local"]}


def _leg(row: dict, opt: dict) -> dict:
    return {"match_id": _match_id(row), "home": row["home"], "away": row["away"],
            "selection": _selection(row, opt["key"]), "key": opt["key"], "odds": round(float(opt["odds"]), 2),
            "bookmaker": opt.get("book"), "pinnacle_fair_odds": round(float(opt["fair_odds"]), 2),
            "edge": round(float(opt["edge"]), 4), "kickoff": row["kickoff"],
            "kickoff_local": local_fields(row["kickoff"])["kickoff_local"]}


def _upcoming(rows: list[dict], now: datetime) -> dict[int, dict]:
    limit = now + timedelta(days=HORIZON_DAYS)
    out = {}
    for row in rows:
        id_ = _match_id(row)
        if id_ is None or not row.get("kickoff"):
            continue
        if now < _parse(row["kickoff"]) <= limit:
            out[id_] = row
    return out


def favorite_notices(rows: dict[int, dict], teams: set[str], leagues: set[str], now: datetime) -> list[Notice]:
    """Juega un equipo o liga favoritos en las próximas 24 h, con recordatorio a menos de 2 h."""
    out = []
    for id_, row in rows.items():
        names = {normalize_name(row["home"]), normalize_name(row["away"])}
        fav_teams = sorted(t for t in (row["home"], row["away"]) if normalize_name(t) in teams)
        fav_league = row.get("league") in leagues
        if not fav_teams and not fav_league:
            continue
        hours = (_parse(row["kickoff"]) - now).total_seconds() / 3600
        if hours > FAVORITE_HOURS:
            continue
        reminder = hours <= REMINDER_HOURS
        facts = {**_base_facts(row), "favorite": ", ".join(fav_teams) or row.get("league_name"),
                 "stage": "2h" if reminder else "24h"}
        who = f"juega {facts['favorite']}" if fav_teams else f"partido de {row.get('league_name')}"
        lead = "Comienza en menos de dos horas" if reminder else "Juega pronto"
        text = _verified(f"{lead}: {row['home']} vs {row['away']}, {who} · {facts['kickoff_local']}.", facts)
        out.append(Notice("favorite_plays", (id_,), "", facts, text, row["kickoff"],
                          PRIORITY["favorite_reminder" if reminder else "favorite_plays"],
                          stage=facts["stage"], teams=names, leagues={row.get("league")}))
    return out


def market_notices(rows: dict[int, dict], suggestions: dict) -> list[Notice]:
    """Avisos de precio para todos los usuarios; las preferencias se aplican después."""
    out: list[Notice] = []
    singles = [s for s in suggestions.get("singles", []) if s.get("match") in rows]
    for s in singles:
        row = rows[s["match"]]
        opt = {"key": s["key"], "odds": s["odds"], "book": s.get("book"), "fair_odds": s["fair_odds"],
               "edge": s["edge"]}
        leg = _leg(row, opt)
        facts = {**_base_facts(row), **leg}
        text = _verified(
            f"Cuota con valor: {leg['selection']} en {row['home']} vs {row['away']} paga {_odds(leg['odds'])} en "
            f"{leg['bookmaker']}, frente a {_odds(leg['pinnacle_fair_odds'])} justa de Pinnacle (ventaja "
            f"{_pct(leg['edge'])}) · {facts['kickoff_local']}. Seguimiento en papel; tope 2 % por apuesta.", facts)
        out.append(Notice("value_bet", (s["match"],), s["key"], facts, text, row["kickoff"],
                          PRIORITY["value_bet"] + round(leg["edge"] * 100), edge=leg["edge"],
                          teams=_names(row), leagues={row.get("league")}))

    for c in suggestions.get("closest", []):
        if c.get("match") not in rows or c["edge"] < pro.MIN_EDGE - NEAR_GAP:
            continue
        row = rows[c["match"]]
        leg = _leg(row, {"key": c["key"], "odds": c["odds"], "book": c.get("book"), "fair_odds": c["fair_odds"],
                         "edge": c["edge"]})
        facts = {**_base_facts(row), **leg, "min_odds": round(float(c["min_odds"]), 2)}
        text = _verified(
            f"Le falta poco: {leg['selection']} en {row['home']} vs {row['away']} valdría la pena desde cuota "
            f"{_odds(facts['min_odds'])}; hoy paga {_odds(leg['odds'])} en {leg['bookmaker']} · "
            f"{facts['kickoff_local']}. Informativo, sin monto sugerido.", facts)
        out.append(Notice("near_value", (c["match"],), c["key"], facts, text, row["kickoff"],
                          PRIORITY["near_value"], edge=leg["edge"], teams=_names(row), leagues={row.get("league")}))

    value_pairs = set()
    for d in suggestions.get("doubles", []):
        legs_in = d.get("legs", [])
        if len(legs_in) != 2 or any(leg.get("match") not in rows for leg in legs_in):
            continue
        legs = [_leg(rows[leg["match"]], {"key": leg["key"], "odds": leg["odds"], "book": leg.get("book"),
                                          "fair_odds": leg["fair_odds"], "edge": leg["edge"]}) for leg in legs_in]
        notice = _combo_notice("value_combo", legs, rows)
        value_pairs.add(notice.selection)
        out.append(notice)

    candidates = []
    for id_, row in rows.items():
        for opt in row.get("pro") or []:
            if opt.get("odds") and opt["odds"] <= pro.MAX_ODDS and opt.get("p_fair", 0) >= MIN_LEG_PROB:
                candidates.append(_leg(row, opt))
    near = []
    for a, b in combinations(candidates, 2):
        if a["match_id"] == b["match_id"]:
            continue                    # mismo partido: correlación, nunca se combina
        ev = (1 + a["edge"]) * (1 + b["edge"]) - 1
        if 0 <= ev < pro.MIN_EDGE:
            near.append((ev, sorted([a, b], key=lambda leg: (leg["kickoff"], leg["match_id"]))))
    for _, legs in sorted(near, key=lambda x: -x[0])[:MAX_NEAR_COMBOS]:
        notice = _combo_notice("near_combo", legs, rows)
        if notice.selection not in value_pairs:
            out.append(notice)
    return out


def _names(row: dict) -> set[str]:
    return {normalize_name(row["home"]), normalize_name(row["away"])}


def _combo_notice(kind: str, legs: list[dict], rows: dict[int, dict]) -> Notice:
    odds = round(legs[0]["odds"] * legs[1]["odds"], 2)
    edge = round((1 + legs[0]["edge"]) * (1 + legs[1]["edge"]) - 1, 4)
    facts = {"legs": legs, "combined_odds": odds, "edge": edge, "kickoff": min(leg["kickoff"] for leg in legs),
             "kickoff_local": min(legs, key=lambda leg: leg["kickoff"])["kickoff_local"]}
    parts = " y ".join(f"{leg['selection']} ({leg['home']} vs {leg['away']}, {_odds(leg['odds'])})" for leg in legs)
    if kind == "value_combo":
        text = (f"Combinada con valor: {parts}. Cuota combinada {_odds(odds)}, ventaja {_pct(edge)} frente a "
                "Pinnacle. Seguimiento en papel.")
    else:
        text = (f"Combinada cerca de tener valor: {parts}. Cuota combinada {_odds(odds)}, ventaja {_pct(edge)}; "
                "le falta para la regla. Informativa, sin monto sugerido.")
    selection = "+".join(f"{leg['match_id']}:{leg['key']}" for leg in legs)
    rows_in = [rows[leg["match_id"]] for leg in legs]
    return Notice(kind, tuple(leg["match_id"] for leg in legs), selection, facts, _verified(text, facts),
                  facts["kickoff"], PRIORITY[kind] + round(max(edge, 0) * 100), edge=edge,
                  teams=set().union(*(_names(r) for r in rows_in)), leagues={r.get("league") for r in rows_in})


def user_settings(conn: sqlite3.Connection) -> dict[str, dict]:
    """Preferencias de avisos por usuario, leídas sin confirmar transacciones (el vigía publica atómicamente)."""
    out = {}
    for user, teams, leagues, types, only in conn.execute(
            "SELECT user_id, favorite_teams, favorite_leagues, alert_types, alerts_only_favorites "
            "FROM agent_user_preferences"):
        out[user] = {"teams": {normalize_name(t) for t in json.loads(teams)}, "leagues": set(json.loads(leagues)),
                     "types": set(json.loads(types)), "only_favorites": bool(only)}
    return out


DEFAULT_SETTINGS = {"teams": set(), "leagues": set(), "types": set(DEFAULT_ALERT_TYPES), "only_favorites": False}


def for_user(notices: list[Notice], settings: dict) -> tuple[list[Notice], list[tuple[Notice, str]]]:
    """Aplica tipos activos y «solo mis equipos y ligas»; devuelve también lo descartado con su motivo."""
    keep, skipped = [], []
    for n in notices:
        if n.kind not in settings["types"]:
            skipped.append((n, "Tipo de aviso desactivado en Preferencias"))
        elif settings["only_favorites"] and n.kind != "favorite_plays" and not (
                n.teams & settings["teams"] or n.leagues & settings["leagues"]):
            skipped.append((n, "Fuera de tus equipos y ligas (filtro de Preferencias)"))
        else:
            keep.append(n)
    return keep, skipped


def publish(conn: sqlite3.Connection, user: str, notice: Notice, stamp: str) -> tuple[bool, str]:
    """Inserta el aviso si es nuevo o si su ventaja mejoró al menos 2 pp desde el último aviso equivalente."""
    base = f"{user}|{notice.base_key}#"
    rows = conn.execute("SELECT facts FROM agent_alerts WHERE user_id=? AND substr(dedup_key,1,?)=? ORDER BY id DESC",
                        (user, len(base), base)).fetchall()
    if rows:
        last = json.loads(rows[0][0]).get("edge")
        if notice.edge is None or last is None or notice.edge < last + REALERT_GAIN - 1e-9:
            return False, "Ya avisado; la ventaja no mejoró al menos 2 pp"
    cursor = conn.execute(
        "INSERT OR IGNORE INTO agent_alerts (user_id,created_at,match_id,watch_id,kind,priority,facts,text,"
        "dedup_key,expires_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (user, stamp, notice.match_ids[0], None, notice.kind, notice.priority, json.dumps(notice.facts),
         notice.text, f"{base}{len(rows) + 1}", notice.expires_at))
    if cursor.rowcount != 1:
        return False, "Alerta descartada: ya estaba registrada (deduplicación)"
    return True, "Mejoró la ventaja: se vuelve a avisar" if rows else "Aviso nuevo"


def run(conn: sqlite3.Connection, rows: list[dict], suggestions: dict, users: set[str],
        now: datetime | None = None) -> list[tuple[str, Notice, bool, str]]:
    """Evalúa y publica los avisos de todos los usuarios dentro de la transacción del vigía."""
    now = now or datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    upcoming = _upcoming(rows, now)
    market = market_notices(upcoming, suggestions)
    settings = user_settings(conn)
    results = []
    for user in sorted(users):
        conf = settings.get(user, DEFAULT_SETTINGS)
        notices = favorite_notices(upcoming, conf["teams"], conf["leagues"], now) + market
        keep, skipped = for_user(notices, conf)
        results.extend((user, n, False, reason) for n, reason in skipped)
        for n in sorted(keep, key=lambda n: (n.expires_at, -n.priority)):
            selected, reason = publish(conn, user, n, stamp)
            results.append((user, n, selected, reason))
    return results
