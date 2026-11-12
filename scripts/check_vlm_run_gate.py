#!/usr/bin/env python3
"""Check the V8-090 exit gate on a real VLM run: diagnostic pages only, raw never overwritten, review required.

CPU only, read-only. For every page_text record of an experiment:

* the page is in the selection report the run wrote (pages chosen by diagnostic, with reasons);
* ``review_required`` is true;
* the production ``extraction.json`` still has the sha256 its ``ocr_receipt.json`` records, and the
  production page text equals the text the run hashed (``product_text_sha256``), so nothing
  replaced the product text.

Exit 0 when every check holds, 1 otherwise. Quality is not assessed here.

  python scripts/check_vlm_run_gate.py --experiment scratch/benchmarks/<EXP> --selection <run report>.json \
      --output output/<run> --report scratch/v8/<new>.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for entry in (ROOT / "src", ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from scripts.run_vlm_challenger import product_texts  # noqa: E402


def check(experiment: Path, selection: dict, output: Path) -> dict:
    records = [json.loads(line) for path in sorted((experiment / "predictions").glob("*.jsonl"))
               for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    selected = {(d["document"], p["page"]) for d in selection["documents"] for p in d["selected"]}
    production_ok = True
    for document in sorted({r["document_id"] for r in records}):
        raw = (output / document / "extraction.json").read_bytes()
        receipt = json.loads((output / document / "ocr_receipt.json").read_bytes())
        production_ok &= hashlib.sha256(raw).hexdigest() == receipt["files"]["extraction.json"]
        texts = product_texts(json.loads(raw))
        production_ok &= all(hashlib.sha256(texts[r["physical_page"]].encode("utf-8")).hexdigest() == r["product_text_sha256"]
                             for r in records if r["document_id"] == document)
    checks = {"records": len(records),
              "all_pages_in_selection": all((r["document_id"], r["physical_page"]) in selected for r in records),
              "all_have_selection_reasons": all(bool(r.get("selection_reasons")) for r in records),
              "all_review_required": all(r.get("review_required") is True for r in records),
              "production_untouched": production_ok}
    checks["gate"] = "PASS" if records and all(v for k, v in checks.items() if k != "records") else "FAIL"
    return {"schema_version": "ocr-v8-vlm-run-gate-v1", "experiment": experiment.as_posix(),
            "output": output.as_posix(), "quality_acceptance": "NOT_EVALUATED", **checks}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.report.exists():
        parser.error(f"{args.report} exists; reports are never overwritten")
    report = check(args.experiment, json.loads(args.selection.read_bytes()), args.output)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["gate"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
