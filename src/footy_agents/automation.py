"""Coordinación ligera de tareas: pausa, presión del PC, exclusión e incrementalidad."""

import ctypes
import hashlib
import json
import logging
import os
import sqlite3
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("automation")


def directory() -> Path:
    from footy import config
    path = config.PROJECT_ROOT / "data/cache/automation"
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_state(name: str) -> dict:
    try:
        state = json.loads((directory() / f"{name}.json").read_text(encoding="utf-8"))
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def write_state(name: str, state: dict) -> None:
    target = directory() / f"{name}.json"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(state, handle, ensure_ascii=False, indent=2)
        os.replace(temporary, target)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def pause(seconds: float) -> dict:
    state = {"paused_until": time.time() + seconds}
    write_state("control", state)
    return state


def paused(now: float | None = None) -> bool:
    return read_state("control").get("paused_until", 0) > (time.time() if now is None else now)


def should_defer(cpu_percent: float, notification_state: int, *, urgent: bool = False) -> bool:
    """Función pura: estados Shell 2=D3D, 3=pantalla completa, 4=presentación."""
    return not urgent and (cpu_percent > 60 or notification_state in {2, 3, 4})


def pc_usage(sample_seconds: float = 5) -> tuple[float, int]:
    if os.name != "nt":
        return 0.0, 0

    def times() -> tuple[int, int]:
        idle, kernel, user = ctypes.c_ulonglong(), ctypes.c_ulonglong(), ctypes.c_ulonglong()
        if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            return 0, 0
        return idle.value, kernel.value + user.value

    before_idle, before_total = times()
    time.sleep(sample_seconds)
    after_idle, after_total = times()
    total = after_total - before_total
    cpu = 100 * (1 - (after_idle - before_idle) / total) if total > 0 else 0
    state = ctypes.c_int()
    result = ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state))
    return max(0.0, min(cpu, 100.0)), state.value if result == 0 else 0


def lower_priority() -> None:
    if os.name == "nt":
        kernel = ctypes.windll.kernel32
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        kernel.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        process = kernel.GetCurrentProcess()
        minimum, maximum, flags = ctypes.c_size_t(), ctypes.c_size_t(), ctypes.c_ulong()
        kernel.GetProcessWorkingSetSizeEx.argtypes = [ctypes.c_void_p] * 4
        kernel.SetProcessWorkingSetSizeEx.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_ulong]
        queried = kernel.GetProcessWorkingSetSizeEx(process, ctypes.byref(minimum), ctypes.byref(maximum),
                                                   ctypes.byref(flags))
        # Background baja I/O, pero puede imponer un máximo duro de 32 MiB: provoca paginación masiva con pandas.
        background = bool(kernel.SetPriorityClass(process, 0x00100000))
        restored = False
        if background and queried:
            prior_limits = (1 if flags.value & 1 else 2) | (4 if flags.value & 4 else 8)
            restored = bool(kernel.SetProcessWorkingSetSizeEx(process, minimum.value, maximum.value, prior_limits))
        if background and not restored:
            kernel.SetPriorityClass(process, 0x00200000)
            background = False
            log.warning("No se pudieron restaurar los límites de memoria; se conserva solo CPU de baja prioridad")
        below_normal = bool(kernel.SetPriorityClass(process, 0x00004000))
        log.info("Prioridad CPU/I/O: background=%s below_normal=%s límites_memoria_restaurados=%s",
                 background, below_normal, restored)


@contextmanager
def instance_lock(name: str = "instance") -> Iterator[bool]:
    with (directory() / f"{name}.lock").open("a+b") as handle:
        if not os.fstat(handle.fileno()).st_size:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        acquired = False
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except OSError:
            pass
        try:
            yield acquired
        finally:
            if acquired:
                handle.seek(0)
                if os.name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def run_task(kind: str, work: Callable[[], int], *, urgent: Callable[[], bool] = lambda: False) -> int:
    lower_priority()
    with instance_lock(kind) as acquired:
        if not acquired:
            log.info("%s omitida: otra tarea está ejecutándose", kind)
            return 0
        state = {"started_at": datetime.now(timezone.utc).isoformat(), "steps": []}
        deadline = time.time() + 3 * 3600
        while True:
            if paused():
                state.update(status="omitida", reason="pausa vigente")
                break
            cpu, notification = pc_usage()
            decision = should_defer(cpu, notification, urgent=kind == "prekickoff" and urgent())
            log.info("%s: CPU %.1f%%, estado Shell %s, diferir=%s", kind, cpu, notification, decision)
            if not decision:
                # La espera de daily no bloquea una actualización pre-partido urgente.
                with instance_lock() as working:
                    if not working:
                        state.update(status="omitida", reason="otra tarea está trabajando")
                        break
                    state.pop("next_retry", None)
                    write_state(kind, dict(state, status="ejecutando", pid=os.getpid()))
                    try:
                        result = work()
                    except Exception:  # noqa: BLE001 - persistir el fallo y volver a propagarlo
                        write_state(kind, dict(read_state(kind), status="falló",
                                              finished_at=datetime.now(timezone.utc).isoformat()))
                        raise
                current = read_state(kind)
                state.update(steps=current.get("steps", []), status="completa" if result == 0 else "con errores",
                             finished_at=datetime.now(timezone.utc).isoformat())
                write_state(kind, state)
                return result
            retry = time.time() + (30 if kind == "prekickoff" else 15) * 60
            state.update(status="diferida", reason="PC ocupado", cpu_percent=cpu, notification_state=notification,
                         next_retry=retry)
            write_state(kind, state)
            if kind == "prekickoff":
                break
            if retry > deadline:
                state.update(next_retry=None, reason="límite de tres horas alcanzado")
                break
            time.sleep(15 * 60)
        write_state(kind, state)
        return 0


def record_step(kind: str, name: str, status: str) -> None:
    state = read_state(kind)
    state.setdefault("steps", []).append({"step": name, "status": status})
    write_state(kind, state)
    log.info("%s: %s %s", kind, name, status)


def data_revision(conn: sqlite3.Connection) -> str:
    """Hash semántico: ignora updated_at, marcadores live y accesos; detecta correcciones históricas."""
    digest = hashlib.sha256()
    tables = [
        ("matches", "id", "id,competition_id,season,kickoff_utc,home_team_id,away_team_id,status,home_goals,away_goals",
         "id"),
        ("team_match_stats", "match_id", "match_id,team_id,stat,value,source,captured_at",
         "match_id,team_id,stat,source"),
    ]
    # SQLite serializa en C por bloques acotados: evita millones de json.dumps de Python y un JSON gigante en RAM.
    for table, key, columns, order in tables:
        maximum = conn.execute(f"SELECT MAX({key}) FROM {table}").fetchone()[0] or 0
        digest.update(table.encode())
        for start in range(0, maximum + 1, 1000):
            payload = conn.execute(
                f"SELECT json_group_array(json_array({columns})) FROM "
                f"(SELECT {columns} FROM {table} WHERE {key} >= ? AND {key} < ? ORDER BY {order})",
                (start, start + 1000)).fetchone()[0]
            digest.update(payload.encode())
            digest.update(b"\n")
    queries = [
        "SELECT COUNT(*), MAX(id), MAX(captured_at), SUM(price), SUM(price * match_id) FROM odds",
        "SELECT COUNT(*), MAX(p.id) FROM predictions p JOIN matches m ON m.id=p.match_id WHERE m.status='finished'",
    ]
    for query in queries:
        for row in conn.execute(query):
            digest.update(json.dumps(tuple(row), separators=(",", ":")).encode())
            digest.update(b"\n")
    return digest.hexdigest()


def incremental(name: str, revision: str, work: Callable[[], object], *, required: tuple[Path, ...] = ()) -> bool:
    state = read_state("incremental")
    if state.get(name) == revision and all(path.is_file() for path in required):
        record_step("daily", name, "omitido: revisión sin cambios")
        return False
    work()
    state[name] = revision
    write_state("incremental", state)
    record_step("daily", name, "ejecutado")
    return True
