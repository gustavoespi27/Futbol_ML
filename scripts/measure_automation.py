"""Compara daily con revisión nueva y estable sobre una copia aislada, sin APIs deportivas.

Modelos, seguimiento local, recomendaciones, informe y artefacto web sí se ejecutan. La ingesta externa
se congela para que el segundo caso tenga exactamente los mismos datos; no representa una jornada con cuotas nuevas.
"""

import argparse
import json
import logging
import shutil
import subprocess
import sys
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def worker(root: Path, label: str) -> None:
    sys.path.insert(0, str(ROOT))
    from footy import config

    config.PROJECT_ROOT = root
    started, cpu = time.perf_counter(), time.process_time()
    import pandas as pd
    import requests
    from scripts import daily

    from footy.ingest import api_football, collect
    from footy.ingest import international as international_source
    from footy.prediction import tracking
    from footy_agents import automation

    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[logging.StreamHandler(sys.stderr)])
    fixtures = pd.DataFrame(columns=["kickoff_utc", "code"])
    with (patch.object(collect, "run_espn", lambda conn: {"congelado": True}),
          patch.object(collect, "run_daily", lambda *args: {"congelado": True}),
          patch.object(api_football, "ApiFootball", lambda conn: None),
          patch.object(daily, "update_current_season", lambda conn: None),
          patch.object(international_source, "refresh_results", lambda **kw: international_source.RAW),
          patch.object(tracking, "fetch_fixtures", lambda: fixtures),
          patch.object(requests, "post", lambda *args, **kwargs: None),
          patch.object(automation, "pc_usage", lambda: (0, 0))):
        result = automation.run_task("daily", daily.work)
    measured = {"caso": label, "resultado": result, "segundos": round(time.perf_counter() - started, 3),
                "cpu_s": round(time.process_time() - cpu, 3), "estado": automation.read_state("daily")}
    (root / f"{label}.json").write_text(json.dumps(measured, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(measured, ensure_ascii=False), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", type=Path)
    parser.add_argument("--label", default="con_cambios")
    args = parser.parse_args()
    if args.worker:
        root = args.worker.resolve()
        if not root.is_relative_to((ROOT / "reports").resolve()):
            parser.error("La copia de medición debe estar dentro de reports")
        worker(root, args.label)
        return
    from footy import config
    from footy.db.connection import connect

    root = ROOT / "reports" / ("automation-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    root.mkdir(parents=True)
    shutil.copytree(ROOT / "config", root / "config")
    shutil.copytree(ROOT / "artifacts", root / "artifacts")
    shutil.copytree(config.path("processed"), root / "data/processed")
    if (config.path("raw") / "international").exists():
        shutil.copytree(config.path("raw") / "international", root / "data/raw/international")
    (root / "docs").mkdir()
    database = root / "data/db/football.sqlite"
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect()) as source, closing(connect(database)) as destination:
        source.backup(destination)
    results = []
    for label in ("con_cambios", "sin_cambios"):
        subprocess.run([sys.executable, __file__, "--worker", str(root), "--label", label], check=True, cwd=ROOT)
        results.append(json.loads((root / f"{label}.json").read_text(encoding="utf-8")))
    (root / "resultado.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Resultado: {root / 'resultado.json'}", flush=True)


if __name__ == "__main__":
    main()
