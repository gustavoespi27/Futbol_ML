"""Ejecuta el vigía sin LLM y muestra percepción, decisiones y acciones (solo tablas agent_*)."""

import argparse
import json
from contextlib import closing
from pathlib import Path

from footy.db.connection import connect
from footy_agents.watcher import run


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, help="Base aislada opcional; por defecto usa la base de la aplicación")
    parser.add_argument("--output", type=Path, help="Guardar bitácora JSON")
    args = parser.parse_args()
    with closing(connect(args.database)) as conn:
        result = run(conn)
    payload = result.model_dump()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Percepción: {result.perceived} partidos. Acciones: {result.actions}. Duración: {result.elapsed_ms:g} ms.")
    for state in result.perception.values():
        print(f"PERCIBIR · {state['match_id']} · {state['home']} vs {state['away']} · "
              f"Pinnacle={state['has_pinnacle']} · valor={state['value']} · edge={state['edge']:.4f} · "
              f"p={state['p_official']} · kickoff={state['kickoff']} · fuente={state['source']}")
    for d in result.decisions:
        print(f"{'ACTUAR' if d.selected else 'DESCARTAR'} · partido {d.match_id} · vigilancia {d.watch_id} · "
              f"{d.kind}: {d.reason}")


if __name__ == "__main__":
    main()
