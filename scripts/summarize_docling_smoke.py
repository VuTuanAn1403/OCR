"""Package the controlled fixture check, not a publication accuracy score."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import sys
import xml.etree.ElementTree as ET

import psutil

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from src.ocr.infrastructure.export.result_reader import load_document_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", default="output/docling_structure_smoke_20261011_verified")
    parser.add_argument("--evidence-dir", default="docs/integrations/docling_20261011")
    args = parser.parse_args()
    run = ROOT / args.run_dir
    evidence = ROOT / args.evidence_dir
    evidence.mkdir(parents=True, exist_ok=True)
    doc = run / "hybrid_final/table_formula_fixture"
    result = load_document_json(doc / "result.json")
    backend = json.loads((run / "backend_smoke.json").read_text(encoding="utf-8"))
    expected_cells = {(0, 0): ("Sample measurements", 1, 3),
        (1, 0): ("Sample", 1, 1), (1, 1): ("x", 1, 1), (1, 2): ("Squared value", 1, 1),
        (2, 0): ("A", 1, 1), (2, 1): ("0.0", 1, 1), (2, 2): ("0.00", 1, 1),
        (3, 0): ("B", 1, 1), (3, 1): ("0.5", 1, 1), (3, 2): ("0.25", 1, 1),
        (4, 0): ("C", 1, 1), (4, 1): ("1.0", 1, 1), (4, 2): ("1.00", 1, 1)}
    expected_latex = r"\int_{0}^{1}x^{2}\,dx=\frac{1}{3}"
    pages = []
    for p in result["pages"]:
        assert len(p["tables"]) == 1 and len(p["formulas"]) == 1
        table = p["tables"][0]
        observed = {(c["row_idx"], c["col_idx"]): (c["text"], c["row_span"], c["col_span"]) for c in table["cells"]}
        differences = [{"row": key[0], "col": key[1], "expected": list(value),
            "observed": list(observed[key]) if key in observed else None}
            for key, value in expected_cells.items() if observed.get(key) != value]
        latex = p["formulas"][0]["latex"]
        matches = re.sub(r"\s+", "", latex) == expected_latex
        assert matches, "Controlled fixture integral does not match after whitespace normalization"
        assert table["engine"] == "docling_tableformer" and table["num_rows"] == 5 and table["num_cols"] == 3
        assert p["metadata"]["docling_structure"]["status"] == "success"
        pages.append({"page": p["page_num"], "page_type": p["page_type"],
            "latex": latex, "latex_matches_fixture_after_whitespace_normalization": matches,
            "table_shape": [table["num_rows"], table["num_cols"]], "expected_cells": len(expected_cells),
            "exact_cell_matches_fixture": len(expected_cells)-len(differences), "cell_differences": differences,
            "docling_stage_seconds": p["quality"]["stage_seconds"]["docling_structure"],
            "reported_page_seconds": p["quality"]["time_taken_seconds"]})
    suites = ET.parse(evidence / "pytest_results.xml").getroot()
    counts = {key: sum(int(s.attrib.get(key, 0)) for s in suites.iter("testsuite"))
              for key in ("tests", "failures", "errors", "skipped")}
    assert counts["failures"] == 0 and counts["errors"] == 0
    report = {"scientific_benchmark": False, "fixture_annotation_source": "fixture generator; no independent annotation",
        "latex_check": "Remove whitespace only; exact string comparison, not general mathematical equivalence",
        "hardware": {"platform": platform.platform(), "cpu": platform.processor(),
            "physical_cores": psutil.cpu_count(logical=False), "logical_cores": psutil.cpu_count(),
            "ram_gb": round(psutil.virtual_memory().total/1024**3, 2)},
        "device": "cpu", "docling_threads": 4, "test_results": counts,
        "passed_tests": counts["tests"]-counts["skipped"], "pages": pages,
        "backend_elapsed_seconds": backend["elapsed_seconds"],
        "reported_pipeline_seconds": result["quality"]["total_time_seconds"],
        "pipeline_timer_limit": "Existing quality timer excludes final artifact export; not end-to-end",
        "validation": json.loads((doc / "validation.json").read_text(encoding="utf-8")),
        "cpu_targets_achieved_on_fixture": False,
        "fixture_sha256": hashlib.sha256((run / "table_formula_fixture.pdf").read_bytes()).hexdigest(),
        "model_artifacts": "model_artifacts.json"}
    (evidence / "smoke_summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.copyfile(run / "backend_smoke.json", evidence / "backend_smoke.json")
    shutil.copyfile(run / "table_formula_fixture.pdf", evidence / "table_formula_fixture.pdf")
    shutil.copyfile(run / "pipeline_final_stdout.txt", evidence / "pipeline_stdout.txt")
    shutil.copytree(doc, evidence / "hybrid_output", dirs_exist_ok=True)
    print(json.dumps({"passed_tests": report["passed_tests"], "skipped": counts["skipped"], "pages": pages,
                      "reported_pipeline_seconds": report["reported_pipeline_seconds"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
