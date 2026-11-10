"""Vigía determinista: percibir, comparar, decidir, actuar y registrar, sin importar ni iniciar un LLM."""

import hashlib
import json
import logging
import math
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone

from footy.db.connection import connect
from footy_agents import watches
from footy_agents.preferences.repo import init_preferences_table
from footy_agents.schemas import ToolCallRecord
from footy_agents.watch_schemas import Decision, WatchRun

GLOBAL_RULES = ("value_appears", "value_disappears", "line_move", "coverage_lost")
LABELS = {
    "kickoff_soon": "el partido comienza pronto",
    "pinnacle_available": "hay precio de Pinnacle",
    "value_appears": "apareció una selección con ventaja evaluable frente a Pinnacle",
    "value_disappears": "dejó de haber una selección con ventaja evaluable",
    "line_move": "se movió la línea de Pinnacle",
    "probability_shift": "cambió la probabilidad oficial",
    "coverage_lost": "se perdió la referencia de Pinnacle",
}


def _valid(values: object, positive: bool = False) -> list[float] | None:
    if not isinstance(values, (list, tuple)) or len(values) != 3:
        return None
    if not all(
        isinstance(v, (float, int))
        and not isinstance(v, bool)
        and math.isfinite(v)
        and (v > 1 if positive else 0 <= v <= 1)
        for v in values
    ):
        return None
    return list(values)


def perceive(rows: list[dict]) -> dict[int, dict]:
    """Condensa el snapshot; una cuota blanda o edge alto sin bet no demuestra valor elegible."""
    result = {}
    for m in rows:
        if not str(m.get("ref", "")).startswith("m:"):
            continue
        id_ = int(m["ref"][2:])
        pinnacle = _valid((m.get("odds_1x2") or {}).get("Pinnacle"), positive=True)
        pro = m.get("pro") or []
        if pinnacle is None:
            by_key = {p.get("key"): p.get("pinnacle") for p in pro}
            pinnacle = _valid([by_key.get(k) for k in ("1", "X", "2")], positive=True)
        result[id_] = {
            "match_id": id_,
            "home": m["home"],
            "away": m["away"],
            "kickoff": m["kickoff"],
            "pinnacle": pinnacle,
            "has_pinnacle": pinnacle is not None,
            "edge": max((float(p.get("edge") or 0) for p in pro), default=0),
            "value": pinnacle is not None and any(p.get("bet") for p in pro),
            "p_official": _valid(m.get("p_official")),
            "source": m.get("source") or "sin fuente",
        }
    return result


def evaluate(
    kind: str, current: dict, previous: dict | None, now: datetime, global_rule: bool = False
) -> tuple[bool, str]:
    hours = (datetime.fromisoformat(current["kickoff"].replace("Z", "+00:00")) - now).total_seconds() / 3600
    if hours <= 0:
        return False, "Partido ya iniciado: no se emiten alertas previas"
    if kind == "kickoff_soon":
        return hours <= 24, "Dentro de las próximas 24 h" if hours <= 24 else "Aún faltan más de 24 h"
    if kind == "pinnacle_available":
        return current["has_pinnacle"], "Referencia Pinnacle disponible" if current["has_pinnacle"] else "Sin Pinnacle"
    if kind == "value_appears" and not global_rule:
        return current["value"], "Selección elegible con ventaja" if current[
            "value"
        ] else "Sin selección elegible con ventaja"
    if previous is None:
        return False, "Primera percepción: se guarda la línea base, sin inventar una transición"
    if kind == "value_appears":
        hit = not previous["value"] and current["value"]
    elif kind == "value_disappears":
        hit = previous["value"] and not current["value"]
    elif kind == "coverage_lost":
        hit = previous["has_pinnacle"] and not current["has_pinnacle"]
        if global_rule and hours >= 12:
            return False, "Pérdida de cobertura fuera de las últimas 12 h"
    elif kind == "line_move":
        if not previous.get("pinnacle") or not current.get("pinnacle"):
            return False, "Faltan dos líneas completas de Pinnacle para comparar"
        hit = max(abs(b / a - 1) for a, b in zip(previous["pinnacle"], current["pinnacle"])) >= 0.05 - 1e-12
    elif kind == "probability_shift":
        if not previous.get("p_official") or not current.get("p_official"):
            return False, "Faltan dos probabilidades oficiales para comparar"
        hit = max(abs(b - a) for a, b in zip(previous["p_official"], current["p_official"])) >= 0.03 - 1e-12
    else:
        raise ValueError(f"Condición desconocida: {kind}")
    return bool(hit), "Cambio cumple la regla" if hit else "Sin cambio que cumpla la regla"


def alert_facts(kind: str, current: dict, previous: dict | None, now: datetime) -> dict:
    facts = dict(current)
    facts["kind"] = kind
    facts["hours_to_kickoff"] = round(
        (datetime.fromisoformat(current["kickoff"].replace("Z", "+00:00")) - now).total_seconds() / 3600, 2
    )
    if kind == "line_move" and previous and current["pinnacle"] and previous["pinnacle"]:
        facts["change_pct"] = round(
            max(abs(b / a - 1) for a, b in zip(previous["pinnacle"], current["pinnacle"])) * 100, 2
        )
        facts["change_pct_text"] = f"{facts['change_pct']:g} %"
    if kind == "probability_shift" and previous and current["p_official"] and previous["p_official"]:
        facts["change_pp"] = round(
            max(abs(b - a) for a, b in zip(previous["p_official"], current["p_official"])) * 100, 2
        )
    return facts


def alert_text(facts: dict) -> str:
    """Las cifras se copian de facts y se verifican antes de guardar la alerta."""
    from footy_agents.grounding import verify_numbers
    text = f"{facts['home']} vs {facts['away']}: {LABELS[facts['kind']]}."
    if facts["kind"] == "kickoff_soon":
        text += f" Faltan {facts['hours_to_kickoff']:g} horas para el inicio."
    if "change_pct" in facts:
        text += f" Movimiento: {facts['change_pct_text']}."
    if "change_pp" in facts:
        text += f" Cambio: {facts['change_pp']:g} puntos porcentuales."
    record = ToolCallRecord(tool_name="watch_facts", arguments={}, result=facts, success=True, execution_time_ms=0)
    if not verify_numbers(text, [record]).verified:
        raise ValueError("La plantilla del vigía contiene cifras fuera de facts")
    return text


def run(conn: sqlite3.Connection, rows: list[dict] | None = None, now: datetime | None = None,
        suggestions: dict | None = None) -> WatchRun:
    """`suggestions` es la salida de service.current_suggestions; sin ella solo hay avisos de favoritos."""
    start = time.perf_counter()
    now = now or datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    if rows is None:
        from footy.web import service

        rows = service.upcoming()
        if suggestions is None:
            try:
                suggestions = service.current_suggestions(rows)
            except (KeyError, ValueError, TypeError):
                logging.getLogger(__name__).exception("Sin sugerencias del motor: solo avisos de favoritos")
    current = perceive(rows)
    watches.init_tables(conn)
    init_preferences_table(conn)
    decisions: list[Decision] = []
    actions = 0
    with conn:
        conn.execute("BEGIN IMMEDIATE")  # estado, alertas y fulfilled se publican juntos; serializa dos vigías
        previous = {
            r[0]: (json.loads(r[1]), r[2])
            for r in conn.execute("SELECT match_id,snapshot,updated_at FROM agent_watch_state")
        }
        active = [
            dict(zip(("id", "user_id", "match_id", "team", "condition"), r))
            for r in conn.execute("SELECT id,user_id,match_id,team,condition FROM agent_watches WHERE status='active'")
        ]
        users = (
            {"default"}
            | {r[0] for r in conn.execute("SELECT user_id FROM agent_user_preferences")}
            | {w["user_id"] for w in active}
        )
        candidates = []
        for id_, state in current.items():
            for user in sorted(users):
                candidates.extend((state, kind, None, user, True) for kind in GLOBAL_RULES)
        for watch in active:
            matches = [
                s
                for s in current.values()
                if (
                    watch["match_id"] == s["match_id"] if watch["match_id"] else watch["team"] in (s["home"], s["away"])
                )
            ]
            if not matches:
                decisions.append(
                    Decision(
                        match_id=watch["match_id"],
                        watch_id=watch["id"],
                        user_id=watch["user_id"],
                        kind=watch["condition"],
                        selected=False,
                        reason="Objetivo sin partido en el snapshot; vigilancia pendiente",
                    )
                )
            candidates.extend((s, watch["condition"], watch["id"], watch["user_id"], False) for s in matches)
        # Más cercano primero; la ventaja desempata. No hay recomendaciones ni registros de apuestas.
        candidates.sort(key=lambda c: (c[0]["kickoff"], -c[0]["edge"], c[1], c[2] or 0, c[3]))
        fulfilled: set[int] = set()
        for state, kind, watch_id, user, global_rule in candidates:
            id_ = state["match_id"]
            old, old_at = previous.get(id_, (None, "initial"))
            selected, reason = evaluate(kind, state, old, now, global_rule)
            if (
                selected
                and global_rule
                and any(
                    w["user_id"] == user
                    and w["condition"] == kind
                    and (w["match_id"] == id_ or w["team"] in (state["home"], state["away"]))
                    for w in active
                )
            ):
                selected, reason = False, "La vigilancia explícita del usuario tiene prioridad sobre la regla global"
            if watch_id in fulfilled:
                selected, reason = False, "La vigilancia ya se cumplió con un partido de mayor prioridad"
            if selected:
                facts = alert_facts(kind, state, old, now)
                text = alert_text(facts)
                fingerprint = json.dumps([user, watch_id, id_, kind, old_at, old, state], sort_keys=True)
                key = f"watch:{watch_id}" if watch_id else hashlib.sha256(fingerprint.encode()).hexdigest()
                hours = facts["hours_to_kickoff"]
                priority = (300 if hours <= 1 else 200 if hours <= 12 else 100) + round(max(0, state["edge"]) * 100)
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO agent_alerts "
                    "(user_id,created_at,match_id,watch_id,kind,priority,facts,text,dedup_key,expires_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (user, stamp, id_, watch_id, kind, priority, json.dumps(facts), text, key, state["kickoff"]),
                )
                selected = cursor.rowcount == 1
                if selected:
                    actions += 1
                else:
                    reason = "Alerta descartada: ya estaba registrada (deduplicación)"
                if watch_id:
                    conn.execute(
                        "UPDATE agent_watches SET status='fulfilled',fulfilled_at=? WHERE id=?", (stamp, watch_id)
                    )
                    fulfilled.add(watch_id)
            decisions.append(
                Decision(match_id=id_, watch_id=watch_id, user_id=user, kind=kind, selected=selected, reason=reason)
            )
        # Avisos fuera del chat: favoritos, valor, casi valor y combinadas (reglas deterministas, sin LLM).
        # Sin partidos no hay avisos: se omite la importación para que prekickoff no cargue numpy ni pandas.
        if rows:
            from footy_agents import notifications

            for user, notice, selected, reason in notifications.run(conn, rows, suggestions or {}, users, now):
                actions += int(selected)
                decisions.append(Decision(match_id=notice.match_ids[0], user_id=user, kind=notice.kind,
                                          selected=selected, reason=reason))
        for id_, state in current.items():
            if previous.get(id_, (None,))[0] != state:
                conn.execute(
                    "INSERT INTO agent_watch_state VALUES (?,?,?) ON CONFLICT(match_id) DO UPDATE "
                    "SET snapshot=excluded.snapshot,updated_at=excluded.updated_at",
                    (id_, json.dumps(state), stamp),
                )
        elapsed = round((time.perf_counter() - start) * 1000, 3)
        cursor = conn.execute(
            "INSERT INTO agent_watch_log (run_at,perceived,decisions,actions,elapsed_ms,perception) "
            "VALUES (?,?,?,?,?,?)",
            (stamp, len(current), json.dumps([d.model_dump() for d in decisions]),
             actions, elapsed, json.dumps(current)),
        )
        id_ = cursor.lastrowid
    return WatchRun(
        id=id_, run_at=stamp, perceived=len(current), perception={str(k): v for k, v in current.items()},
        decisions=decisions, actions=actions, elapsed_ms=elapsed
    )


def run_safely() -> None:
    """Integración de pipeline: un fallo del vigía no altera su resultado ni inicia Ollama."""
    try:
        with closing(connect()) as conn:
            any_matches = conn.execute(
                "SELECT 1 FROM matches WHERE status='scheduled' AND kickoff_utc>? LIMIT 1",
                (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),),
            ).fetchone()
            result = run(conn, rows=None if any_matches else [])
        logging.getLogger(__name__).info(
            "Vigía: %s partidos, %s alertas, %.1f ms", result.perceived, result.actions, result.elapsed_ms
        )
    except Exception:  # noqa: BLE001 - límite del pipeline: el vigía nunca debe romper recolección/predicción
        logging.getLogger(__name__).exception("El vigía falló; el pipeline continúa")
