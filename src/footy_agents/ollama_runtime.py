"""Arranque local bajo demanda y propiedad explícita del proceso de Ollama."""

import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import requests

from footy import config


class OllamaRuntime:
    def __init__(self) -> None:
        self.process: subprocess.Popen | None = None
        self.startup_failed = False
        self.lock = threading.Lock()

    @staticmethod
    def probe(base: str) -> bool:
        try:
            with requests.get(base.rstrip("/") + "/models", timeout=1) as response:
                response.raise_for_status()
            return True
        except requests.RequestException:
            return False

    def ensure_running(self) -> bool:
        cfg = config.settings().get("agents", {}).get("llm", {})
        base = cfg.get("base_url", "http://localhost:11434/v1")
        with self.lock:
            if self.probe(base):
                self.startup_failed = False
                return True
            address = urlsplit(base)
            if not cfg.get("autostart", False) or address.hostname not in {"localhost", "127.0.0.1", "::1"}:
                return False
            executable = cfg.get("executable", "ollama")
            resolved = shutil.which(executable)
            if not resolved:
                fallback = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Ollama/ollama.exe"
                resolved = str(fallback) if executable == "ollama" and fallback.is_file() else executable
            env = dict(os.environ, OLLAMA_KEEP_ALIVE="5m", OLLAMA_MAX_LOADED_MODELS="1", OLLAMA_NUM_PARALLEL="1",
                       OLLAMA_HOST=f"{address.hostname}:{address.port or 11434}")
            flags = (subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS) if os.name == "nt" else 0
            try:
                if self.process is None or self.process.poll() is not None:
                    self.process = subprocess.Popen([resolved, "serve"], env=env, creationflags=flags,
                                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                                    stderr=subprocess.DEVNULL)
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    if self.probe(base):
                        self.startup_failed = False
                        return True
                    if self.process.poll() is not None:
                        break
                    time.sleep(.2)
            except OSError:
                pass
            self.startup_failed = True
            self._stop_owned()
            return False

    def _stop_owned(self) -> None:
        process, self.process = self.process, None
        if process is None or process.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], check=False,
                           creationflags=subprocess.CREATE_NO_WINDOW, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
        else:
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    def shutdown(self) -> None:
        with self.lock:
            self._stop_owned()


runtime = OllamaRuntime()
