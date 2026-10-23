"""ocr_contracts: wire round-trip and dependency-light import."""
import json
import os
from pathlib import Path
import subprocess
import sys

from ocr_contracts.document import ExtractedDocument
from ocr_contracts.page import ExtractedPage
from ocr_contracts.quality import DocumentQualityReport

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "tests/fixtures/migration/v63_sample"
HEAVY = ("numpy", "pymupdf", "fitz", "cv2", "PIL", "torch", "onnxruntime", "vietocr", "docling",
         "transformers", "openpyxl", "yaml", "psutil")


def test_real_v63_pages_round_trip_unchanged():
    for name in ("text_page-0001.json", "structure_page-0001.json"):
        data = json.loads((FIXTURE / name).read_text(encoding="utf-8"))
        assert ExtractedPage.model_validate(data).model_dump(mode="json") == data


def test_null_confidence_and_sources_survive():
    data = json.loads((FIXTURE / "structure_page-0001.json").read_text(encoding="utf-8"))
    page = ExtractedPage.model_validate(data)
    dumped = page.model_dump(mode="json")
    assert [b["source"] for b in dumped["blocks"]] == [b["source"] for b in data["blocks"]]
    nulls = lambda page: [i for i, item in enumerate(page["metadata"]["docling_structure"]["layout_items"])
                          if item.get("confidence") is None]
    assert nulls(data) and nulls(dumped) == nulls(data)  # unknown confidence stays null, never 0
    assert [b["bbox"] for b in dumped["blocks"]] == [b["bbox"] for b in data["blocks"]]


def test_document_model_accepts_page_fixture():
    page = json.loads((FIXTURE / "structure_page-0001.json").read_text(encoding="utf-8"))
    document = ExtractedDocument(document_id="sample", file_path="sample.pdf", file_hash="0" * 16,
                                 total_pages=1, selected_pages=[1], pages=[ExtractedPage.model_validate(page)],
                                 quality=DocumentQualityReport(document_id="sample", total_pages=1))
    assert ExtractedDocument.model_validate(document.model_dump(mode="json")) == document


def test_import_without_heavy_dependencies():
    modules = [p.stem for p in (ROOT / "src/ocr_contracts").glob("*.py") if p.stem != "__init__"]
    code = ("import importlib, json, sys\n"
            f"for m in {modules!r}: importlib.import_module('ocr_contracts.' + m)\n"
            f"print(json.dumps(sorted(m for m in {HEAVY!r} if m in sys.modules)))")
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT / "src", env=env,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == []
