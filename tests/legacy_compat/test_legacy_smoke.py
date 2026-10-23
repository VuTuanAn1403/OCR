"""Legacy compatibility smoke tests (D2: legacy is frozen behind its facade).

They detect breakage caused by moving shared modules. They do not certify
that legacy output is byte-identical or accurate.
"""
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


def run(args, cwd=ROOT, timeout=300, env=None):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1", **(env or {})}
    return subprocess.run([sys.executable, *args], cwd=cwd, env=env, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=timeout)


@pytest.mark.parametrize("args", [
    ["run_ocr.py", "--help"],
    ["run_batch.py", "--help"],
    ["-m", "src.ocr.cli.gpu_runner", "--help"],
    ["-m", "src.ocr.cli.collect", "--help"],
])
def test_cli_help(args):
    result = run(args)
    assert result.returncode == 0, result.stderr[-2000:]
    assert "usage" in result.stdout.lower()


def test_legacy_modules_import_in_fresh_interpreter():
    modules = ["src.ocr.cli.batch_runner", "src.ocr.cli.run_ocr", "src.ocr.cli.gpu_runner",
               "src.ocr.application.convert_document", "src.ocr.runtime.document_pool",
               # kaggle/ocr_pdf_kaggle.ipynb
               "src.ocr.infrastructure.export.completion", "src.ocr.infrastructure.postprocessing.keyword_counter",
               "src.ocr.runtime.atomic_io"]
    code = "import importlib,sys\nfor m in sys.argv[1:]: importlib.import_module(m)"
    result = run(["-c", code, *modules])
    assert result.returncode == 0, result.stderr[-2000:]


@pytest.mark.parametrize("args", [
    ["run_ocr.py", "fixture.pdf", "--backend", "legacy"],
    ["run_batch.py", "--profile", "fast"],
    ["-m", "src.ocr.cli.gpu_runner", "fixture.pdf", "--device", "cpu"],
])
def test_historical_execution_policies_are_rejected(args):
    result = run(args)
    assert result.returncode == 2
    assert "error:" in result.stderr


def test_count_only_requires_verified_extraction(tmp_path):
    doc = tmp_path / "bao_cao"
    doc.mkdir()
    (doc / "result.md").write_text("Chuyển đổi số", encoding="utf-8")
    result = run(["scripts/run_count_only.py", str(doc)])
    assert result.returncode != 0
    assert not (doc / "count_keywords.xlsx").exists()
