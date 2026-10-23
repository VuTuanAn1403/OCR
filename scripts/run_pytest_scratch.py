"""Run pytest with every file it generates under scratch/runs/<run_id>/.

Layout and rules: docs/architecture/KE_HOACH_GON_WORKSPACE.md, section 3. Each
call creates a new run directory and refuses an existing one, because pytest
clears an existing --basetemp. The cache provider and bytecode are off, and
TMP/TEMP point into the run for the pytest process only. pytest runs from the
repository root, so test paths are relative to it whatever the caller's working
directory is. The exit code is pytest's own.

    .venv/Scripts/python.exe scripts/run_pytest_scratch.py tests/unit/contracts -q

Output: tmp/, pytest/ (basetemp), logs/pytest.log, evidence/junit.xml, run.json.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).absolute().parents[1]


def new_run_id(now: dt.datetime | None = None) -> str:
    return (now or dt.datetime.now()).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]


def prepare_run(runs_root: Path, run_id: str) -> Path:
    run = Path(runs_root).absolute() / run_id
    run.mkdir(parents=True)  # FileExistsError: a run directory is never reused
    for name in ("tmp", "logs", "evidence"):
        (run / name).mkdir()
    return run


def pytest_command(python: str, run: Path, pytest_args: list[str]) -> list[str]:
    return [python, "-B", "-m", "pytest", *pytest_args, "-p", "no:cacheprovider",
            f"--basetemp={run / 'pytest'}", f"--junitxml={run / 'evidence' / 'junit.xml'}"]


def child_env(run: Path, base: dict | None = None) -> dict:
    """Environment of the pytest process; the caller's environment is not modified."""
    env = dict(os.environ if base is None else base)
    tmp = str(run / "tmp")
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8", TMP=tmp, TEMP=tmp, TMPDIR=tmp)
    return env


def _echo(data: bytes) -> None:
    stream = getattr(sys.stdout, "buffer", None)
    if stream is None:
        sys.stdout.write(data.decode("utf-8", "replace"))
    else:
        stream.write(data)
        stream.flush()


def _git_head() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                     allow_abbrev=False, usage="%(prog)s [options] [pytest arguments]")
    parser.add_argument("--runs-root", type=Path, default=ROOT / "scratch" / "runs")
    parser.add_argument("--run-id", help="new run id; default <yyyyMMdd-HHmmss>-<8 hex>")
    parser.add_argument("--python", default=sys.executable, help="interpreter that runs pytest")
    args, pytest_args = parser.parse_known_args(argv)
    run = prepare_run(args.runs_root, args.run_id or new_run_id())
    command = pytest_command(args.python, run, pytest_args)
    record = {"schema_version": "pytest-run-v1", "run_id": run.name, "run_directory": str(run),
              "cwd": str(ROOT), "command": command, "git_head": _git_head(),
              "started_at": dt.datetime.now().astimezone().isoformat(), "status": "RUNNING", "exit_code": None}
    (run / "run.json").write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    exit_code = None
    try:
        with open(run / "logs" / "pytest.log", "wb") as log, \
                subprocess.Popen(command, cwd=ROOT, env=child_env(run), stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT) as process:
            for line in process.stdout:
                log.write(line)
                _echo(line)
            exit_code = process.wait()
    finally:
        record.update(finished_at=dt.datetime.now().astimezone().isoformat(), exit_code=exit_code,
                      status="FINISHED" if exit_code is not None else "INTERRUPTED")
        (run / "run.json").write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    _echo(f"pytest exit code: {exit_code}; evidence: {run}\n".encode("utf-8"))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
