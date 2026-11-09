"""No convertir la prioridad de I/O baja en un máximo duro de 32 MiB para pandas."""

from types import SimpleNamespace

import pytest

from footy_agents import automation


class Function:
    def __init__(self, callback):
        self.callback = callback
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        return self.callback(*args)


@pytest.mark.parametrize("prior_flags,restored,expected", [(0, True, 10), (4, True, 6), (0, False, 10)])
def test_background_restores_prior_memory_limits(monkeypatch, prior_flags, restored, expected):
    def limits(process, minimum, maximum, flags):
        minimum._obj.value = 204800
        maximum._obj.value = 1413120
        flags._obj.value = prior_flags
        return 1

    kernel = SimpleNamespace(GetCurrentProcess=Function(lambda: 123),
                             GetProcessWorkingSetSizeEx=Function(limits),
                             SetProcessWorkingSetSizeEx=Function(lambda *a: restored),
                             SetPriorityClass=Function(lambda *a: 1))
    monkeypatch.setattr(automation, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(automation.ctypes, "windll", SimpleNamespace(kernel32=kernel), raising=False)
    automation.lower_priority()
    assert kernel.SetProcessWorkingSetSizeEx.calls == [(123, 204800, 1413120, expected)]
    classes = [call[1] for call in kernel.SetPriorityClass.calls]
    assert classes == ([0x100000, 0x4000] if restored else [0x100000, 0x200000, 0x4000])
