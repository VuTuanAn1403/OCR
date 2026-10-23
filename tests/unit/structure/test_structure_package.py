"""ocr_structure (P07): phase B maps Docling output onto phase A text without
loading recognition code, and keeps the source policy of every structure."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "tests/fixtures/migration/v63_sample"

PHASE_B = r'''
import json, sys
from pathlib import Path
root, fixture, pdf = map(Path, sys.argv[1:4])
from ocr_structure import docling_client
from src.ocr.runtime import gpu_phase_worker
from src.ocr.runtime.atomic_io import atomic_write_json

class FakeDocling(docling_client.DoclingStructureExtractor):
    def extract_page(self, page, page_num):
        # Test double: an empty successful conversion, never model evidence.
        return {"tables": [], "formulas": [], "metadata": {"status": "success", "provenance": {"placement": {}}}}
    def close(self):
        pass
docling_client.DoclingStructureExtractor = FakeDocling
gpu_phase_worker_extractor = FakeDocling
page = json.loads((fixture / "text_page-0001.json").read_text(encoding="utf-8"))
atomic_write_json(root / "text" / "page-0001.json", page)
atomic_write_json(root / "text.done.json", {"files": {"text/page-0001.json": "fixture"}})
run = json.loads((fixture / "run.json").read_text(encoding="utf-8"))
from ocr_runtime.config import load_profiles
config = {**load_profiles()[1]["unified_gpu_full_ocr"], **run["config"]}
config["bridge_font"] = str(Path(sys.argv[4]))
gpu_phase_worker.run_structure({"job_dir": str(root), "pdf": str(pdf), "generation": "g", "config": config, "device": "cuda"})
out = json.loads((root / "structure" / "page-0001.json").read_text(encoding="utf-8"))
print(json.dumps({"loaded": sorted(m for m in ("vietocr", "ocr_recognition", "src.ocr.application.process_page",
                                                  "torch") if m in sys.modules),
                  "bridge": out["metadata"]["ocr_structure_bridge"], "status": out["metadata"]["docling_structure"]["status"],
                  "blocks": len(out["blocks"])}))
'''


def test_phase_b_does_not_load_recognition(tmp_path):
    import pymupdf

    page = json.loads((FIXTURE / "text_page-0001.json").read_text(encoding="utf-8"))
    sample = tmp_path / "source.pdf"
    with pymupdf.open() as pdf:
        pdf.new_page(width=page["width"], height=page["height"])
        pdf.save(sample)
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), str(ROOT)])}
    result = subprocess.run([sys.executable, "-c", PHASE_B, str(tmp_path / "job"), str(FIXTURE),
                             str(sample), str(ROOT / "assets/fonts/NotoSans-Regular.ttf")],
                            cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=300)
    assert result.returncode == 0, result.stderr[-3000:]
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["loaded"] == [], report["loaded"]
    assert report["bridge"]["policy"] == "raster-plus-gpu-text-v1" and report["bridge"]["native_text_layer_copied"] is False
    assert report["status"] == "success" and report["blocks"] > 0
