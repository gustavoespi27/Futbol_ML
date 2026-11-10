"""Ojeador sin LLM: PERCIBIR, DECIDIR y ACTUAR; --dry-run no escribe ni consulta ESPN."""

import argparse
import json
from contextlib import closing
from pathlib import Path

from footy.db.connection import connect
from footy_agents.odds_scout import MAX_ESPN_REQUESTS, run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--database", type=Path)
    parser.add_argument("--budget", type=int, default=MAX_ESPN_REQUESTS)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    with closing(connect(args.database)) as conn:
        result = run(conn, budget=args.budget, dry_run=args.dry_run)
    print(f"PERCIBIR: {result.perceived} partidos; simulación={args.dry_run}.")
    for p in result.perception:
        print(
            f"PERCIBIR · {p.match_id} · {p.home} vs {p.away} · cuotas={p.has_odds} · "
            f"Pinnacle={p.has_pinnacle} · inicio en {p.hours_to_kickoff:.1f} h · favorito={p.favorite}"
        )
    for d in result.decisions:
        print(f"DECIDIR · {d.match_id} · {d.source} · {'SELECCIONADO' if d.selected else 'DESCARTADO'} · {d.reason}")
    print(f"ACTUAR: {result.actions} scoreboards; {result.inserted} filas insertadas; {result.elapsed_ms:g} ms.")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
