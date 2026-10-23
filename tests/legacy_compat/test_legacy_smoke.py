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
    ["run_ocr.py", "--backend", "legacy", "--help"],
    ["run_batch.py", "--backend", "legacy", "--help"],
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


def test_count_only_on_legacy_output(tmp_path):
    doc = tmp_path / "bao_cao"
    doc.mkdir()
    (doc / "result.md").write_text("Chuyển đổi số và CHUYỂN ĐỔI SỐ; Internet di động.\n", encoding="utf-8")
    result = run(["scripts/run_count_only.py", str(doc)])
    assert result.returncode == 0, result.stderr[-2000:]
    assert (doc / "count_keywords.xlsx").is_file()
    matches = int(result.stdout.rsplit("Exact matches:", 1)[1].split()[0])
    assert matches >= 2  # "chuyển đổi số" in both cases, plus "internet di động"


def test_legacy_fast_cpu_single_page(tmp_path):
    """Real CPU OCR on a temporary scanned page; skip without RapidOCR."""
    importlib.util.find_spec("rapidocr_onnxruntime") or pytest.skip("NOT_RUN: rapidocr-onnxruntime not installed")
    pymupdf = pytest.importorskip("pymupdf")
    sample = tmp_path / "source" / "sample.pdf"
    sample.parent.mkdir()
    with pymupdf.open() as source, pymupdf.open() as scanned:
        page = source.new_page()
        page.insert_text((72, 100), "OCR pipeline smoke test 2026", fontsize=24)
        pixels = page.get_pixmap(matrix=pymupdf.Matrix(2, 2))
        scanned.new_page(width=page.rect.width, height=page.rect.height).insert_image(page.rect, pixmap=pixels)
        scanned.save(sample)
    result = run(["run_ocr.py", str(sample), "--backend", "legacy", "--profile", "fast", "--device", "cpu",
                  "--pages", "1", "--assets", "none", "--output", str(tmp_path)], timeout=900,
                 # The page cache stays with the test, not in the checkout's .cache.
                 env={"OCR_CACHE_DIR": str(tmp_path / "cache")})
    assert result.returncode == 0, (result.stdout[-2000:], result.stderr[-2000:])
    out = tmp_path / "sample"
    for name in ("result.md", "result.json", "validation.json", "manifest.json", "COMPLETED.json"):
        assert (out / name).is_file(), name
    assert json.loads((out / "validation.json").read_text(encoding="utf-8"))["status"] in ("PASS", "NEEDS_REVIEW")
    assert "2026" in (out / "result.md").read_text(encoding="utf-8")
