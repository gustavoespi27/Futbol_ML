"""Artefactos de próximos partidos: lectura web y publicación atómica desde tareas."""

import hashlib
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from footy import config
from footy.db.repository import utc_now
from footy.web.services.common import to_json

DIRECTORY = config.PROJECT_ROOT / "data/cache/upcoming"
MAX_AGE = 26 * 3600
FORMAT_VERSION = 2
log = logging.getLogger(__name__)


def signature() -> str:
    revision = DIRECTORY / "revision.json"
    try:
        version = revision.read_text(encoding="utf-8")
    except FileNotFoundError:
        version = "sin_revision"
    paths = [config.SETTINGS_PATH,
             config.PROJECT_ROOT / "config/league_models.json",
             config.path("processed") / "calibration.json",
             config.path("processed") / "ml/upcoming.pkl",
             config.PROJECT_ROOT / "data/cache/cross_league.pkl",
             config.PROJECT_ROOT / "data/cache/international.pkl",
             config.PROJECT_ROOT / "config/team_aliases.yaml",
             config.PROJECT_ROOT / "config/international_teams.json",
             config.PROJECT_ROOT / "artifacts/ml/model.joblib",
             config.PROJECT_ROOT / "artifacts/ml/meta.json"]
    stamps = [(str(config.path("database").resolve()), version)]
    for path in paths:
        try:
            stat = path.stat()
            stamps.append((str(path), stat.st_mtime_ns, stat.st_size))
        except FileNotFoundError:
            stamps.append((str(path), None, None))
    return hashlib.sha256(json.dumps(stamps).encode()).hexdigest()


def advance_revision() -> None:
    """Solo las tareas de ingestión publican revisiones; live_scores no participa.

    Cada ciclo marca inicio y fin: una lectura durante la ingestión tampoco permanece válida al terminarla.
    UUID evita perder invalidaciones por dos escritores simultáneos o marcas de tiempo de baja resolución.
    """
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=DIRECTORY, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump({"revision": uuid4().hex, "updated_at": utc_now()}, handle)
        os.replace(temporary, DIRECTORY / "revision.json")
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def future_matches(matches: list[dict]) -> list[dict]:
    from datetime import datetime

    now = time.time()
    return [m for m in matches if datetime.fromisoformat(m["kickoff"].replace("Z", "+00:00")).timestamp() > now]


def read(days: int) -> list[dict] | None:
    try:
        saved = json.loads((DIRECTORY / f"{days}.json").read_text(encoding="utf-8"))
        if (saved["version"] != FORMAT_VERSION or saved["signature"] != signature()
                or not 0 <= time.time() - saved["created"] < MAX_AGE):
            return None
        if saved["expires"] <= time.time():
            return None
        return future_matches(saved["matches"])
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
    saved = {"version": FORMAT_VERSION, "created": now, "expires": min(now + MAX_AGE, midnight),
             "signature": expected_signature, "matches": to_json(matches)}
    temporary = None
    try:
        DIRECTORY.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=DIRECTORY, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(saved, handle, ensure_ascii=False, allow_nan=False)
        os.replace(temporary, DIRECTORY / f"{days}.json")
    except OSError as exc:
        # La web puede servir el cálculo de respaldo aunque el almacenamiento de caché no sea escribible.
        log.warning("No se pudo publicar el precalculado web: %s", exc)
    finally:
        if temporary:
            try:
                temporary.unlink(missing_ok=True)
            except OSError as exc:
                log.warning("No se pudo retirar el archivo temporal del precalculado: %s", exc)
