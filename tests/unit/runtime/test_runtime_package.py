"""ocr_runtime: root resolution, light imports and the worker runtimes (P05a)."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
SUFFIX = "Scripts/python.exe" if os.name == "nt" else "bin/python"
MODULES = ["paths", "config", "models", "fingerprint", "dependency_lock", "process_tree", "device",
           "torch_placement", "backend_probe", "structured_logging", "gpu_lease", "preflight"]


def probe(python, code, cwd, **env):
    environment = {**os.environ, "PYTHONPATH": str(ROOT / "src"), **env}
    return subprocess.run([str(python), "-c", code], cwd=cwd, env=environment, capture_output=True,
                          text=True, encoding="utf-8", timeout=120)


def test_project_root_does_not_depend_on_cwd_or_file_depth(tmp_path):
    result = probe(sys.executable, "from ocr_runtime import paths; print(paths.PROJECT_ROOT); print(paths.is_checkout())",
                   tmp_path)
    assert result.returncode == 0, result.stderr
    root, checkout = result.stdout.split()
    assert Path(root) == ROOT and checkout == "True"


def test_project_root_override(tmp_path):
    result = probe(sys.executable, "from ocr_runtime import paths; print(paths.PROJECT_ROOT); print(paths.is_checkout())",
                   tmp_path, OCR_PROJECT_ROOT=str(tmp_path))
    root, checkout = result.stdout.split()
    assert Path(root) == tmp_path and checkout == "False"


def test_supervisor_imports_runtime_without_gpu_libraries(tmp_path):
    code = (f"import importlib, json, sys\nfor m in {MODULES!r}: importlib.import_module('ocr_runtime.' + m)\n"
            "print(json.dumps(sorted(m for m in ('torch','onnxruntime','vietocr','docling','numpy','cv2','pymupdf') "
            "if m in sys.modules)))")
    result = probe(sys.executable, code, tmp_path)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == []


@pytest.mark.parametrize("role,modules", [("docling", ["dependency_lock", "torch_placement"]),
                                          ("text", MODULES)])
def test_worker_runtime_imports_ocr_runtime(tmp_path, role, modules):
    python = ROOT / ".venv-v62" / role / SUFFIX
    if not python.is_file():
        pytest.skip(f"NOT_RUN: {python} not present on this machine")
    code = f"import importlib\nfor m in {modules!r}: importlib.import_module('ocr_runtime.' + m)\nprint('OK')"
    result = probe(python, code, tmp_path)
    assert result.returncode == 0 and "OK" in result.stdout, result.stderr[-2000:]
