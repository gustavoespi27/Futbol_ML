"""Arranque perezoso, prioridades y propiedad; sin lanzar procesos reales."""

import asyncio
import subprocess

import pytest

from footy_agents import health, llm, ollama_runtime


@pytest.fixture
def setup(monkeypatch):
    cfg = {"agents": {"llm": {"autostart": True, "executable": "ollama"}}}
    monkeypatch.setattr(ollama_runtime.config, "settings", lambda: cfg)
    monkeypatch.setattr(ollama_runtime.shutil, "which", lambda _: "ollama.exe")
    return cfg, ollama_runtime.OllamaRuntime()


def test_external_server_is_never_owned_or_stopped(setup, monkeypatch):
    _, runtime = setup
    monkeypatch.setattr(runtime, "probe", lambda _: True)
    monkeypatch.setattr(ollama_runtime.subprocess, "Popen", lambda *a, **kw: pytest.fail("Ya está iniciado"))
    assert runtime.ensure_running()
    runtime.shutdown()
    assert runtime.process is None


def test_hidden_low_priority_environment_and_owned_shutdown(setup, monkeypatch):
    _, runtime = setup
    probes = iter([False, True])
    monkeypatch.setattr(runtime, "probe", lambda _: next(probes))
    created, stopped = [], []

    class Process:
        pid = 12345

        def poll(self):
            return None

        def wait(self, timeout):
            stopped.append(timeout)

        def terminate(self):
            stopped.append("terminate")

    def popen(*args, **kwargs):
        created.append((args, kwargs))
        return Process()

    monkeypatch.setattr(ollama_runtime.subprocess, "Popen", popen)
    monkeypatch.setattr(ollama_runtime.subprocess, "run", lambda *a, **kw: stopped.append(a[0]))
    assert runtime.ensure_running()
    args, kwargs = created[0]
    assert args[0] == ["ollama.exe", "serve"]
    assert kwargs["env"]["OLLAMA_KEEP_ALIVE"] == "5m"
    assert kwargs["env"]["OLLAMA_MAX_LOADED_MODELS"] == kwargs["env"]["OLLAMA_NUM_PARALLEL"] == "1"
    if ollama_runtime.os.name == "nt":
        assert kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW
        assert kwargs["creationflags"] & subprocess.BELOW_NORMAL_PRIORITY_CLASS
    runtime.shutdown()
    assert stopped and runtime.process is None


@pytest.mark.parametrize("base,enabled", [("http://remote:11434/v1", True), ("http://localhost:11434/v1", False)])
def test_remote_or_disabled_never_start(setup, monkeypatch, base, enabled):
    cfg, runtime = setup
    cfg["agents"]["llm"].update(base_url=base, autostart=enabled)
    monkeypatch.setattr(runtime, "probe", lambda _: False)
    monkeypatch.setattr(ollama_runtime.subprocess, "Popen", lambda *a, **kw: pytest.fail("No debe arrancar"))
    assert not runtime.ensure_running()


def test_failed_start_updates_health_without_starting_from_health(setup, monkeypatch):
    _, runtime = setup
    monkeypatch.setattr(runtime, "probe", lambda _: False)

    def missing(*args, **kwargs):
        raise FileNotFoundError("ollama")

    monkeypatch.setattr(ollama_runtime.subprocess, "Popen", missing)
    assert not runtime.ensure_running() and runtime.startup_failed
    monkeypatch.setattr(health, "runtime", runtime)
    monkeypatch.setattr(health, "_cache", None)
    monkeypatch.setattr(health.requests, "get", lambda *a, **kw: (_ for _ in ()).throw(
        ollama_runtime.requests.ConnectionError()))
    result = health.get_health()
    assert result.autostart and result.startup_failed and not result.llm_available


def test_client_initialization_is_lazy_and_start_failure_releases_slot(setup, monkeypatch):
    _, runtime = setup
    calls = []
    monkeypatch.setattr(ollama_runtime, "runtime", runtime)
    monkeypatch.setattr(runtime, "ensure_running", lambda: calls.append(True) or False)
    client = llm.OpenAICompatibleClient.from_settings()
    assert calls == []
    with pytest.raises(llm.LLMUnavailable):
        list(client.stream_chat([]))
    assert calls == [True]
    client.ensure_available = lambda: True
    monkeypatch.setattr(client, "_stream_chat", lambda *_: iter([llm.TextDelta("Hola")]))
    assert list(client.stream_chat([]))[0].text == "Hola"


def test_probe_is_bounded_and_does_not_infer(monkeypatch):
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def raise_for_status(self):
            pass

    monkeypatch.setattr(ollama_runtime.requests, "get", lambda url, **kw: calls.append((url, kw)) or Response())
    assert ollama_runtime.OllamaRuntime.probe("http://localhost:11434/v1")
    assert calls == [("http://localhost:11434/v1/models", {"timeout": 1})]

    def down(*a, **kw):
        raise ollama_runtime.requests.Timeout()

    monkeypatch.setattr(ollama_runtime.requests, "get", down)
    assert not ollama_runtime.OllamaRuntime.probe("http://localhost:11434/v1")


def test_process_exiting_before_ready_is_failure(setup, monkeypatch):
    _, runtime = setup
    monkeypatch.setattr(runtime, "probe", lambda _: False)
    monkeypatch.setattr(ollama_runtime.time, "sleep", lambda _: pytest.fail("No esperar un proceso muerto"))

    class Exited:
        def poll(self):
            return 1

    monkeypatch.setattr(ollama_runtime.subprocess, "Popen", lambda *a, **kw: Exited())
    assert not runtime.ensure_running()
    assert runtime.startup_failed and runtime.process is None


def test_web_shutdown_calls_owned_runtime_cleanup(monkeypatch):
    from footy.web import app

    calls = []

    class Thread:
        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

    monkeypatch.setattr(app.threading, "Thread", Thread)
    monkeypatch.setattr(ollama_runtime.runtime, "shutdown", lambda: calls.append("shutdown"))

    async def cycle():
        async with app.lifespan(None):
            assert not calls
        assert calls == ["shutdown"]

    asyncio.run(cycle())
