"""ocr_document (P08): an extracted page becomes a full document output
without loading any GPU model library or other processing package."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]

EXPORT = r'''
import hashlib, json, sys
from pathlib import Path
fixture, out, root = map(Path, sys.argv[1:4])
from ocr_contracts.document import ExtractedDocument
from ocr_contracts.page import ExtractedPage
from ocr_contracts.quality import DocumentQualityReport
from ocr_document.export import DocumentExporter
run = json.loads((fixture / "run.json").read_text(encoding="utf-8"))
page = ExtractedPage.model_validate(json.loads((fixture / "structure_page-0001.json").read_text(encoding="utf-8")))
quality = DocumentQualityReport(document_id="sample", total_pages=1, page_reports=[page.quality])
doc = ExtractedDocument(document_id="sample", file_path=str(root / run["source"]), file_hash=run["pdf_sha256"][:16],
                        total_pages=1, selected_pages=[1], profile=run["config"]["profile"], pages=[page], quality=quality)
doc.manifest = {"document_id": "sample", "file_hash": doc.file_hash, "total_pages": 1, "selected_pages": [1],
                "configuration": run["config"]}
directory = DocumentExporter.execute(doc, out, assets_mode="none", output_mode="compact")
heavy = ("torch", "vietocr", "onnxruntime", "transformers", "docling", "ocr_recognition", "ocr_layout",
         "ocr_structure", "ocr_keywords", "ocr_reporting", "src.ocr.application.process_page")
print(json.dumps({"loaded": sorted(m for m in heavy if m in sys.modules),
                  "validation": json.loads((directory / "validation.json").read_text(encoding="utf-8"))["status"],
                  "result_md": (directory / "result.md").is_file()}))
'''


def test_export_without_models_or_other_packages(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    result = subprocess.run([sys.executable, "-c", EXPORT, str(ROOT / "tests/fixtures/migration/v63_sample"),
                             str(tmp_path), str(ROOT)], cwd=tmp_path, env=env, capture_output=True, text=True,
                            encoding="utf-8", timeout=300)
    assert result.returncode == 0, result.stderr[-3000:]
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report == {"loaded": [], "validation": "NEEDS_REVIEW", "result_md": True}
