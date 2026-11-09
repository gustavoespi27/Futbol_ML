"""Artefactos de próximos partidos: lectura web y publicación atómica desde tareas."""

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

from footy import config
from footy.web.services.common import to_json

DIRECTORY = config.PROJECT_ROOT / "data/cache/upcoming"
MAX_AGE = 26 * 3600
FORMAT_VERSION = 1


def signature() -> str:
    db = config.path("database")
    paths = [db, Path(str(db) + "-wal"), config.SETTINGS_PATH,
             config.PROJECT_ROOT / "config/league_models.json",
             config.path("processed") / "calibration.json",
             config.path("processed") / "ml/upcoming.pkl",
             config.PROJECT_ROOT / "data/cache/cross_league.pkl"]
    stamps = []
    for path in paths:
        try:
            stat = path.stat()
            stamps.append((str(path), stat.st_mtime_ns, stat.st_size))
        except FileNotFoundError:
            stamps.append((str(path), None, None))
    return hashlib.sha256(json.dumps(stamps).encode()).hexdigest()


def read(days: int) -> list[dict] | None:
    try:
        saved = json.loads((DIRECTORY / f"{days}.json").read_text(encoding="utf-8"))
        if (saved["version"] != FORMAT_VERSION or saved["signature"] != signature()
                or not 0 <= time.time() - saved["created"] < MAX_AGE):
            return None
        if saved["expires"] <= time.time():
            return None
        return saved["matches"]
    except (OSError, ValueError, KeyError, TypeError):
        # Un artefacto ausente, corrupto o de otra versión activa el cálculo de respaldo.
        return None


def write(days: int, matches: list[dict], expected_signature: str) -> None:
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    if signature() != expected_signature:
        return  # datos modificados durante el cálculo: no publicar un resultado incoherente
    now = time.time()
    local = datetime.now(ZoneInfo("America/Santiago"))
    midnight = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    starts = [datetime.fromisoformat(m["kickoff"].replace("Z", "+00:00")).timestamp() for m in matches]
    saved = {"version": FORMAT_VERSION, "created": now, "expires": min([now + MAX_AGE, midnight, *starts]),
             "signature": expected_signature, "matches": to_json(matches)}
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=DIRECTORY, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(saved, handle, ensure_ascii=False, allow_nan=False)
        os.replace(temporary, DIRECTORY / f"{days}.json")
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
