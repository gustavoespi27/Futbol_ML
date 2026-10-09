"""Agrega las cuotas de cierre Over/Under 2,5 a partidos ya guardados, leyendo los CSV crudos de
football-data.co.uk en data/raw (sin volver a descargar). Idempotente.

Uso:  python scripts/backfill_ou_odds.py
"""

import re
import sys
from collections import defaultdict

from footy import config
from footy.db.connection import connect
from footy.ingest import football_data as fd


def main() -> int:
    raw = config.path("raw") / fd.SOURCE
    latest: dict[tuple[str, str], object] = {}
    for f in sorted(raw.glob("*.csv")):                     # nombre: <DIV>_<yyzz>_<timestamp>.csv
        m = re.match(r"([A-Z0-9]+)_(\d{4})_\d{8}T\d{6}Z\.csv$", f.name)
        if m and m.group(1) in fd.leagues()["main"]:
            latest[(m.group(1), m.group(2))] = f             # el último snapshot de cada temporada
    conn = connect()
    added = defaultdict(int)
    for (code, tag), f in sorted(latest.items()):
        season = f"20{tag[:2]}/20{tag[2:]}"
        df = fd.parse_main(f.read_text(encoding="utf-8"), code, season)
        for row in df.to_dict("records"):
            hit = conn.execute("SELECT match_id FROM match_sources WHERE source = ? AND source_match_id = ?",
                               (fd.SOURCE, f"{season}|{row['Date']}|{row['Home']}|{row['Away']}")).fetchone()
            if hit:
                added[code] += fd.repo.insert_odds(conn, fd.closing_ou_odds(hit["match_id"], row))
        conn.commit()
    print(dict(added), "filas O/U 2,5 agregadas en total:", sum(added.values()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
