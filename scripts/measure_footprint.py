"""Medición reproducible sin dependencias nuevas; cada muestra fría usa un proceso nuevo.

Frío significa memoria del proceso vacía, no borrar artefactos ni cachés de disco.
El arranque mide disponibilidad HTTP, no la finalización del precalentamiento.
"""

import argparse
import ctypes
import gc
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]


def ram_mb() -> float | None:
    if os.name != "nt":
        return None

    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("faults", ctypes.c_ulong),
                    *[(name, ctypes.c_size_t) for name in
                      ("peak", "working", "peak_pool", "pool", "peak_nonpaged", "nonpaged", "page", "peak_page")]]

    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    kernel = ctypes.windll.kernel32
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    get_memory = ctypes.windll.psapi.GetProcessMemoryInfo
    get_memory.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_ulong]
    if not get_memory(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        return None
    return round(counters.working / 1024**2, 2)


def worker(live_check: bool = False) -> None:
    if live_check:
        from footy import config
        from footy.db.connection import connect
        from footy.web.services import snapshots

        # La jornada es real; las escrituras de regresión se hacen sobre una copia, nunca sobre marcadores reales.
        with tempfile.TemporaryDirectory(prefix="footy-footprint-") as directory:
            original_path = config.path
            target = Path(directory) / "football.sqlite"
            with closing(connect()) as source, closing(connect(target)) as destination:
                source.backup(destination)
            config.path = lambda key: target if key == "database" else original_path(key)
            snapshots.DIRECTORY = Path(directory) / "upcoming"
            try:
                _worker(True)
            finally:
                config.path = original_path
                gc.collect()
        return
    _worker(False)


def _worker(live_check: bool) -> None:
    started = time.perf_counter()
    from footy.web import service

    imported = time.perf_counter() - started
    rows = []
    for name in ("frio", "caliente"):
        start = time.perf_counter()
        matches = service.upcoming()
        rows.append({"muestra": name, "segundos": round(time.perf_counter() - start, 4),
                     "ram_mb": ram_mb(), "partidos": len(matches)})
    result = {"importacion_s": imported, "upcoming": rows}
    if live_check:
        from footy.db.connection import connect
        from footy.web.services import context, snapshots

        calls = []
        original = context._upcoming

        def count(days):
            calls.append(days)
            return original(days)

        context._upcoming = count
        baseline = snapshots.signature()
        samples = []
        if matches:
            mid = int(matches[0]["ref"][2:])
            conn = connect()
            for i in range(3):
                conn.execute("INSERT OR REPLACE INTO live_scores VALUES (?, ?, 0, '45', ?)",
                             (mid, i, str(i)))
                conn.commit()
                if i == 2:
                    context._upcoming_cache.clear()  # forzar lectura desde disco en la última muestra
                start = time.perf_counter()
                found = service.upcoming()
                samples.append({"lectura": "disco" if i == 2 else "memoria",
                                "segundos": round(time.perf_counter() - start, 4), "partidos": len(found),
                                "firma_estable": snapshots.signature() == baseline})
            conn.close()
        result["live_scores"] = {"base": "copia aislada de datos reales", "muestras": samples,
                                 "recalculos_tras_escrituras": len(calls),
                                 "nota": "Sin jornada medible" if not matches else "Marcadores de prueba solo en copia"}
    print(json.dumps(result))


def endpoint(base: str, path: str, body: dict | None = None) -> dict:
    start = time.perf_counter()
    first = None
    chars = 0
    events = []
    try:
        with requests.request("POST" if body else "GET", base + path, json=body,
                              stream=True, timeout=(5, 150)) as response:
            response.raise_for_status()
            response.encoding = "utf-8"
            for line in response.iter_lines(decode_unicode=True):
                if line.startswith("event:"):
                    events.append(line[6:].strip())
                if line.startswith("data:"):
                    data = json.loads(line[5:])
                    if "delta" in data:
                        first = first if first is not None else time.perf_counter() - start
                        chars += len(data["delta"])
        return {"ruta": path, "segundos": round(time.perf_counter() - start, 3),
                "primer_texto_s": first, "caracteres": chars, "eventos": events,
                "tokens_s": None, "nota": "SSE no publica tokens del proveedor; caracteres no son tokens."}
    except (requests.RequestException, ValueError) as exc:
        return {"ruta": path, "error": type(exc).__name__}


def runtime_cycle(output: Path) -> None:
    """Experimento explícito de cinco minutos; nunca se ejecuta en la medición habitual."""
    from footy_agents.ollama_runtime import runtime

    if os.name != "nt":
        raise RuntimeError("--runtime-cycle mide árboles de procesos en Windows")
    base_llm = "http://localhost:11434/v1"
    if runtime.probe(base_llm):
        raise RuntimeError("El experimento requiere Ollama apagado; no detiene servidores ajenos")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    process = subprocess.Popen([sys.executable, "-m", "uvicorn", "footy.web.app:app", "--host", "127.0.0.1",
                                "--port", str(port), "--log-level", "error"], cwd=ROOT,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    rows = []

    def snapshot(label: str) -> None:
        roots = f"{process.pid}" + (f",{runtime.process.pid}" if runtime.process else "")
        command = (f"$taskPids = @({roots}); $taskProcesses = @(Get-CimInstance Win32_Process); "
                   "do { $taskBefore = $taskPids.Count; foreach ($taskProcess in $taskProcesses) { "
                   "$taskParent = $taskProcesses | Where-Object ProcessId -eq $taskProcess.ParentProcessId; "
                   "if ($taskPids -contains $taskProcess.ParentProcessId -and "
                   "$taskPids -notcontains $taskProcess.ProcessId -and "
                   "$taskProcess.CreationDate -ge $taskParent.CreationDate) { "
                   "$taskPids += $taskProcess.ProcessId } } "
                   "} while ($taskBefore -ne $taskPids.Count); "
                   "Get-Process | Where-Object { $taskPids -contains $_.Id } | "
                   "Select-Object Id,ProcessName,@{Name='ram_mb';Expression={[math]::Round($_.WorkingSet64/1MB,2)}} | "
                   "ConvertTo-Json -Compress")
        processes = json.loads(subprocess.check_output(["powershell", "-NoProfile", "-Command", command], text=True))
        resident = requests.get("http://localhost:11434/api/ps", timeout=3).json() if runtime.process else {}
        gpu = None
        try:
            gpu = subprocess.check_output(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                          text=True, timeout=5).strip()
        except (OSError, subprocess.SubprocessError):
            pass
        rows.append({"estado": label, "procesos": processes, "modelos": resident.get("models", []),
                     "vram_total_gpu_mib": gpu})
        output.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(label, flush=True)

    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                requests.get(base + "/api/docs", timeout=1).raise_for_status()
                break
            except requests.RequestException:
                time.sleep(.2)
        else:
            raise TimeoutError("Servidor sin respuesta")
        snapshot("servidor_solo")
        if not runtime.ensure_running():
            raise RuntimeError("No arrancó Ollama")
        snapshot("ollama_en_reposo")
        result = endpoint(base, "/api/agent/chat", {"message": "Hola, salúdame brevemente"})
        snapshot("modelo_cargado")
        rows[-1]["chat"] = result
        deadline = time.monotonic() + 330
        while time.monotonic() < deadline:
            if not requests.get("http://localhost:11434/api/ps", timeout=3).json().get("models"):
                snapshot("despues_keep_alive")
                break
            time.sleep(1)
        else:
            snapshot("modelo_no_descargado_en_330s")
    finally:
        runtime.shutdown()
        process.terminate()
        process.wait(timeout=15)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--runtime-cycle", action="store_true", help="Medir cuatro estados y esperar el keep_alive")
    parser.add_argument("--label", default="linea_base")
    parser.add_argument("--llm", action="store_true", help="Consultar chat y resumen: consume inferencia real")
    parser.add_argument("--live-check", action="store_true", help="Medir escrituras live_scores en copia aislada")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/analisis/09_consumo.md")
    args = parser.parse_args()
    if args.runtime_cycle:
        if args.output.suffix.lower() != ".json":
            parser.error("--runtime-cycle requiere --output con extensión .json; no sobrescribe informes Markdown")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        runtime_cycle(args.output)
        return
    if args.worker:
        worker(args.live_check)
        return
    command = [sys.executable, __file__, "--worker", *(["--live-check"] if args.live_check else [])]
    result = json.loads(subprocess.check_output(command, cwd=ROOT, text=True))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    start = time.perf_counter()
    process = subprocess.Popen([sys.executable, "-m", "uvicorn", "footy.web.app:app", "--host", "127.0.0.1",
                                "--port", str(port), "--log-level", "error"], cwd=ROOT,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        while time.perf_counter() - start < 120:
            try:
                response = requests.get(base + "/api/docs", timeout=1)
                response.raise_for_status()
                break
            except requests.RequestException:
                if process.poll() is not None:
                    raise RuntimeError("El servidor terminó antes de estar disponible")
                time.sleep(0.1)
        else:
            raise TimeoutError("Servidor no disponible en 120 segundos")
        result["arranque_http_s"] = round(time.perf_counter() - start, 3)
        result["endpoints"] = ([endpoint(base, "/api/agent/chat", {"message": "¿Cómo está rindiendo el sistema?"}),
                                endpoint(base, "/api/agent/briefing")] if args.llm else [])
    finally:
        process.terminate()
        process.wait(timeout=15)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    from footy.db.repository import utc_now

    section = (f"\n## {args.label} — {utc_now()}\n\n"
               "Frío: proceso nuevo, con artefactos de disco existentes. RAM: working set del proceso de cálculo; "
               "no incluye Ollama, GPU ni el proceso web. Arranque: disponibilidad HTTP, no fin del prewarm. "
               "No equivale a un benchmark con datos actualizados.\n\n```json\n" +
               json.dumps(result, ensure_ascii=False, indent=2) + "\n```\n")
    with args.output.open("a", encoding="utf-8") as handle:
        handle.write(section)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
