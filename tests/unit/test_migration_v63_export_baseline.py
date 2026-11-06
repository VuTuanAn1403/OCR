"""Export-stage regression on a real V6.3 page (P01 baseline).

The fixture holds the page JSON written by phase B of a real GPU run on
examples/sample.pdf. CPU export must preserve the recorded artifact bytes
apart from the explicit pipeline version field. This is a software regression
check, not an accuracy measurement.
"""
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from src.ocr.runtime import gpu_phase_worker
from src.ocr.runtime.paths import PROJECT_ROOT

FIXTURE = PROJECT_ROOT / "tests/fixtures/migration/v63_sample"
EXPECTED = json.loads((FIXTURE / "expected_export.json").read_text(encoding="utf-8"))
STABLE = ("result.md", "document.md", "structure.json", "document.json", "extraction.json",
          "pages/page-0001.md", "pages/page-0001.json", "furniture.json", "layout_order.json")


def export(tmp_path, assets):
    run = json.loads((FIXTURE / "run.json").read_text(encoding="utf-8"))
    job = tmp_path / "job"
    (job / "structure").mkdir(parents=True)
    shutil.copyfile(FIXTURE / "structure_page-0001.json", job / "structure/page-0001.json")
    for phase, receipt in (("text", run["text_receipt"]), ("structure", run["structure_receipt"])):
        files = {"structure/page-0001.json": "fixture"} if phase == "structure" else {}
        (job / f"{phase}.done.json").write_text(json.dumps({**receipt, "files": files}), encoding="utf-8")
    request = {"job_dir": str(job), "pdf": str(PROJECT_ROOT / run["source"]), "config": {**__import__("ocr_runtime.config", fromlist=["load_profiles"]).load_profiles()[1]["unified_gpu_full_ocr"], **run["config"]}, "device": "cuda",
               "config_path": str(PROJECT_ROOT / "config/profiles-v63.yaml"), "generation": run["generation"],
               "identity": {"pdf": run["pdf_sha256"]}, "model_hashes": {}, "lock_hashes": {},
               "output": str(tmp_path / "out"), "assets": assets, "output_mode": "compact",
               "keywords_file": str(PROJECT_ROOT / "config/keywords.txt"), "finalize_document": False}
    gpu_phase_worker.run_export(request)
    return tmp_path / "out" / "sample"


def digests(output):
    result = {}
    for name in STABLE:
        raw = (output / name).read_bytes()
        if name == "extraction.json":
            assert json.loads(raw)["pipeline_version"] == "7.0.0"
            version_field = b'"pipeline_version": "7.0.0"'
            assert raw.count(version_field) == 1
            raw = raw.replace(version_field, b'"pipeline_version": "6.3.0.dev1"', 1)
        result[name] = hashlib.sha256(raw).hexdigest()
    return result


@pytest.mark.parametrize("assets", ["none", "png"])
def test_export_reproduces_baseline(tmp_path, assets):
    output = export(tmp_path, assets)
    assert digests(output) == EXPECTED[assets]
    assert json.loads((output / "manifest.json").read_text(encoding="utf-8"))["pipeline_version"] == "7.0.0"
    assert json.loads((output / "validation.json").read_text(encoding="utf-8"))["status"] == "NEEDS_REVIEW"
