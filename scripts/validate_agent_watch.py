"""Valida Pinnacle/valor con el snapshot real y tablas aisladas; publicación opcional de objetivos de demo."""

import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from footy.db.connection import connect
from footy.web import service
from footy_agents import watcher, watches
from footy_agents.watch_schemas import WatchArgs


def validate(output: Path, publish: bool = False) -> dict:
    rows = service.upcoming()
    states = watcher.perceive(rows)
    with sqlite3.connect(":memory:") as conn:
        # Copia únicamente identidades del snapshot REAL para validar targets; no hay cuotas simuladas.
        conn.executescript("CREATE TABLE matches(id INTEGER PRIMARY KEY); CREATE TABLE teams(name TEXT);")
        conn.executemany("INSERT INTO matches VALUES (?)", [(id_,) for id_ in states])
        for id_ in states:
            for condition in ("pinnacle_available", "value_appears"):
                watches.create_watch(conn, "default", WatchArgs(match_id=id_, condition=condition))
        first = watcher.run(conn, rows)
        second = watcher.run(conn, rows)
        result = {
            "source": "service.upcoming() real, sin alterar cuotas ni predicciones",
            "matches": len(states),
            "with_pinnacle": sum(s["has_pinnacle"] for s in states.values()),
            "with_eligible_value": sum(s["value"] for s in states.values()),
            "first": first.model_dump(),
            "second": second.model_dump(),
            "alerts": [a.model_dump() for a in watches.alerts(conn, "default")],
        }
    if publish:
        priced = next((s for s in states.values() if s["has_pinnacle"]), None)
        if priced is None:
            raise ValueError("No hay un precio real de Pinnacle; no se publicará una alerta ficticia")
        with closing(connect()) as conn:
            result["published_targets"] = [
                watches.create_watch(conn, "default", WatchArgs(match_id=priced["match_id"], condition=condition))
                for condition in ("pinnacle_available", "value_appears")
            ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("matches", "with_pinnacle", "with_eligible_value")}))
    print(
        f"Primera ejecución: {first.actions} alertas; segunda: {second.actions}; "
        f"tiempos: {first.elapsed_ms:g} / {second.elapsed_ms:g} ms"
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--publish", action="store_true", help="Crear dos objetivos de demo para un partido real con Pinnacle"
    )
    args = parser.parse_args()
    validate(args.output, args.publish)
