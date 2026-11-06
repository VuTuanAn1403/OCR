from types import SimpleNamespace

import pytest

from benchmark.scientific_evaluation import awake


def test_temporary_execution_state_restores_previous_flags_even_on_failure(monkeypatch):
    calls = []

    class Function:
        def __call__(self, flags):
            calls.append(flags)
            return 0x80000000

    kernel = SimpleNamespace(SetThreadExecutionState=Function())
    monkeypatch.setattr(awake, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(awake.ctypes, "WinDLL", lambda *args, **kwargs: kernel, raising=False)
    with pytest.raises(RuntimeError, match="operation failed"):
        with awake.keep_system_awake() as state:
            assert state["system_required"] is True
            raise RuntimeError("operation failed")
    assert calls == [0x80000001, 0x80000000]
