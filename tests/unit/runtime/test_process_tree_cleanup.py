"""Resource errors in inspection must not bypass process-tree termination."""
from types import SimpleNamespace
from unittest.mock import Mock

import psutil
import pytest

from ocr_runtime import process_tree


def owned_tree(error):
    events = []
    tree = process_tree.ProcessTree.__new__(process_tree.ProcessTree)
    tree.process = SimpleNamespace(pid=123, wait=Mock(side_effect=lambda **kw: events.append("wait")))
    tree.seen = {}
    tree.job = 42
    tree.kernel = SimpleNamespace(
        TerminateJobObject=Mock(side_effect=lambda *args: events.append("terminate") or True),
        CloseHandle=Mock(side_effect=lambda *args: events.append("close_handle") or True),
    )
    tree.observe = Mock(side_effect=error)
    tree.survivors = Mock(return_value=[])
    return tree, events


@pytest.mark.parametrize("error", [OSError(1455, "Paging file is too small"), psutil.AccessDenied(123), MemoryError(), KeyboardInterrupt()])
def test_owned_job_is_terminated_before_inspection_error_is_reraised(error):
    tree, events = owned_tree(error)
    with pytest.raises(type(error)) as result:
        tree.close()
    assert result.value is error
    assert events == ["terminate", "close_handle", "wait"]
    assert tree.job is None
    tree.process.wait.assert_called_once_with(timeout=15)


def test_group_is_killed_even_when_final_inspection_fails(monkeypatch):
    error = OSError(1455, "Paging file is too small")
    tree, events = owned_tree(error)
    tree.job = None
    killpg = Mock(side_effect=lambda *args: events.append("kill_group"))
    monkeypatch.setattr(process_tree, "os", SimpleNamespace(name="posix", killpg=killpg))
    monkeypatch.setattr(process_tree, "signal", SimpleNamespace(SIGKILL=9))
    with pytest.raises(OSError) as result:
        tree.close()
    assert result.value is error
    assert events == ["kill_group", "wait"]
    killpg.assert_called_once_with(123, process_tree.signal.SIGKILL)


def test_survivors_still_prevent_exit_acceptance_after_inspection_error(monkeypatch):
    tree, events = owned_tree(OSError(1455, "Paging file is too small"))
    tree.survivors.return_value = [777]
    monkeypatch.setattr(process_tree.time, "monotonic", Mock(side_effect=[1, 17]))
    with pytest.raises(process_tree.ProcessTreeSurvived) as result:
        tree.close()
    assert result.value.pids == [777]
    assert events == ["terminate", "close_handle", "wait"]


def test_initial_inspection_error_also_tears_down_the_group(monkeypatch):
    error = OSError(1455, "Paging file is too small")
    killpg = Mock()
    monkeypatch.setattr(process_tree, "os", SimpleNamespace(name="posix", killpg=killpg))
    monkeypatch.setattr(process_tree, "signal", SimpleNamespace(SIGKILL=9))
    monkeypatch.setattr(process_tree.ProcessTree, "observe", Mock(side_effect=error))
    monkeypatch.setattr(process_tree.ProcessTree, "survivors", Mock(return_value=[]))
    process = SimpleNamespace(pid=123, wait=Mock())
    with pytest.raises(OSError) as result:
        process_tree.ProcessTree(process)
    assert result.value is error
    killpg.assert_called_once_with(123, process_tree.signal.SIGKILL)
    process.wait.assert_called_once_with(timeout=15)
