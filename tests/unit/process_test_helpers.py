"""Observe OS reaping without killing a process or accepting a surviving PID."""
import psutil


def assert_reaped(pid, *, timeout=5):
    # A terminated orphan can briefly be a zombie before the system's child
    # reaper collects it. Still require the PID to disappear within a bound;
    # never kill it here, which would hide a production cleanup failure.
    try:
        psutil.Process(pid).wait(timeout=timeout)
    except psutil.NoSuchProcess:
        pass
    assert not psutil.pid_exists(pid)
def historical_profiles():
    """Explicit frozen input for historical algorithm tests, never runtime default."""
    from pathlib import Path
    return str(Path(__file__).resolve().parents[2] / "benchmark/baselines/profiles-v61.yaml")
