"""Notebook handoff checks that do not require a Google account or Colab VM."""
import ast
import datetime
import json
from pathlib import Path
import signal
import subprocess
import sys
import textwrap

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _sources():
    notebook = json.loads((ROOT / "notebooks/colab_v6.ipynb").read_text(encoding="utf-8"))
    return notebook, ["".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "code"]


def test_notebook_cells_are_python_and_have_no_stale_outputs():
    notebook, sources = _sources()
    assert notebook["nbformat"] == 4 and notebook["metadata"]["accelerator"] == "GPU"
    for source in sources:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "gpu_probe" for t in node.targets):
                ast.parse(textwrap.dedent(ast.literal_eval(node.value)))
    assert all(not cell.get("outputs") and cell.get("execution_count") is None
               for cell in notebook["cells"] if cell["cell_type"] == "code")


@pytest.mark.parametrize("exit_code", [0, 3])
def test_notebook_process_log_propagates_command_failure(tmp_path, exit_code):
    _, sources = _sources()
    tree = ast.parse(next(source for source in sources if "def run_logged" in source))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef))
    namespace = {"Path": Path, "subprocess": subprocess, "REPO_DIR": tmp_path,
                 "os": __import__("os"), "signal": signal}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "colab_run_logged", "exec"), namespace)
    command = [sys.executable, "-c", f"print('colab-check'); raise SystemExit({exit_code})"]
    log = tmp_path / "logs/run.log"
    if exit_code:
        with pytest.raises(subprocess.CalledProcessError) as error:
            namespace["run_logged"](command, log)
        assert error.value.returncode == exit_code
    else:
        namespace["run_logged"](command, log)
    assert "colab-check" in log.read_text(encoding="utf-8")


@pytest.mark.parametrize("shards, index, limit", [(1, 0, None), (3, 1, 2)])
def test_notebook_batch_commands_are_accepted_by_real_cli(tmp_path, monkeypatch, shards, index, limit):
    from src.ocr.cli import batch_runner
    _, sources = _sources()
    cell = next(source for source in sources if source.startswith("if RUN_FULL_BATCH:"))
    calls = []
    namespace = {"RUN_FULL_BATCH": True, "OCR_PYTHON": sys.executable, "PROFILE": "balanced",
                 "INPUT_DIR": tmp_path / "input", "BATCH_OUTPUT": tmp_path / "output",
                 "DRIVE_ROOT": tmp_path, "SHARD": index, "SHARDS": shards, "FILE_LIMIT": limit,
                 "ASSETS": "none", "OUTPUT_MODE": "compact", "os": __import__("os"),
                 "run_logged": lambda command, log: calls.append(command)}
    monkeypatch.setenv("OCR_CACHE_DIR", str(tmp_path / "cache"))
    exec(compile(cell, "colab_batch", "exec"), namespace)
    command = calls[0]
    assert ("--shard" in command) == (shards > 1)
    captured = {}
    class Runner:
        def __init__(self, **kwargs):
            captured.update(kwargs)
        def execute_batch(self, limit=None):
            captured["limit"] = limit
    monkeypatch.setattr(batch_runner, "preparse_hardware", lambda: None)
    monkeypatch.setattr(batch_runner, "BatchOCRRunner", Runner)
    monkeypatch.setattr(sys, "argv", command[1:])
    batch_runner.main()
    assert captured["device"] == "cuda" and captured["profile"] == "balanced"
    assert captured["workers"] == 1 and captured["threads_per_worker"] == 2
    assert captured["limit"] == limit and captured["output_mode"] == "compact"
    assert captured["shard"] == ((index, shards) if shards > 1 else None)
