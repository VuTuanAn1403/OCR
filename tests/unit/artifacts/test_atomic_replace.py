"""Bounded retry of atomic renames over transient Windows sharing locks."""
import pytest

from ocr_artifacts import atomic_io


def locked(winerror):
    error = PermissionError(13, "Access is denied")
    error.winerror = winerror
    return error


@pytest.fixture
def renames(monkeypatch):
    calls, plan = [], []

    def fake_replace(source, target):
        calls.append((source, target))
        if plan:
            raise plan.pop(0)

    monkeypatch.setattr(atomic_io.os, "replace", fake_replace)
    monkeypatch.setattr(atomic_io.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(atomic_io, "_WINDOWS", True)
    return calls, plan


@pytest.mark.parametrize("winerror", [5, 32])
def test_transient_lock_is_retried_until_the_rename_succeeds(renames, winerror):
    calls, plan = renames
    plan += [locked(winerror), locked(winerror)]
    atomic_io.replace("a", "b")
    assert calls == [("a", "b")] * 3


def test_a_lock_that_never_clears_still_fails(renames):
    calls, plan = renames
    plan += [locked(5)] * (len(atomic_io._RETRY_DELAYS) + 1)
    with pytest.raises(PermissionError):
        atomic_io.replace("a", "b")
    assert len(calls) == len(atomic_io._RETRY_DELAYS) + 1


def test_other_permission_errors_and_other_platforms_fail_at_once(renames, monkeypatch):
    calls, plan = renames
    plan.append(locked(1314))  # not a sharing lock
    with pytest.raises(PermissionError):
        atomic_io.replace("a", "b")
    monkeypatch.setattr(atomic_io, "_WINDOWS", False)
    plan.append(locked(5))
    with pytest.raises(PermissionError):
        atomic_io.replace("a", "b")
    assert len(calls) == 2


def test_atomic_writes_use_the_retrying_rename(tmp_path, monkeypatch):
    used = []
    real = atomic_io.replace
    monkeypatch.setattr(atomic_io, "replace", lambda source, target: used.append(target) or real(source, target))
    atomic_io.atomic_write_json(tmp_path / "x.json", {"a": 1})
    assert used == [tmp_path / "x.json"] and (tmp_path / "x.json").read_text(encoding="utf-8").strip().startswith("{")
