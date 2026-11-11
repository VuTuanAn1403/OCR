"""Check that a baseline OCR run matches a locked baseline identity (V8-006 exit gate).

Read-only. For every PDF in the lock, the run must hold ``<output>/<id>/ocr_receipt.json``
whose ``ocr_identity`` equals the locked value, and ``valid_ocr`` (the product's own
receipt check: identity, manifest hash, file list) must accept the folder. The pages
of the manifest must cover the whole PDF. Quality stays NOT_EVALUATED.

Exit codes: 0 = every PDF matches, 1 = a mismatch or a missing receipt, 2 = could not run.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for entry in (ROOT / "src", ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

SCHEMA = "ocr-v8-baseline-identity-check-v1"


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def check_run(lock: dict, output: Path, valid_ocr=None) -> dict:
    if valid_ocr is None:
        from ocr_pipeline.document import valid_ocr  # imported lazily: it pulls the product runtime
    rows = []
    for item in lock["inputs"]:
        folder = output / item["id"]
        row = {"id": item["id"], "pdf_sha256": item["pdf_sha256"], "locked_ocr_identity": item["ocr_identity"],
               "receipt_ocr_identity": None, "receipt_valid": False, "full_pages": False, "status": "MISSING"}
        receipt_path = folder / "ocr_receipt.json"
        if receipt_path.is_file():
            receipt = _read(receipt_path)
            row["receipt_ocr_identity"] = receipt.get("ocr_identity")
            row["receipt_valid"] = bool(valid_ocr(folder, item["ocr_identity"]))
            manifest_path = folder / "manifest.json"
            if manifest_path.is_file():
                manifest = _read(manifest_path)
                row["full_pages"] = manifest.get("selected_pages") == list(range(1, int(item["total_pages"]) + 1))
            matches = row["receipt_ocr_identity"] == item["ocr_identity"]
            row["status"] = "MATCH" if matches and row["receipt_valid"] and row["full_pages"] else "MISMATCH"
        rows.append(row)
    status = "MATCH" if rows and all(row["status"] == "MATCH" for row in rows) else "MISMATCH"
    return {"schema_version": SCHEMA, "lock_id": lock.get("lock_id"), "status": status,
            "documents": rows, "pages": sum(int(item["total_pages"]) for item in lock["inputs"]),
            "quality_acceptance": "NOT_EVALUATED"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare OCR receipts of a run with a baseline lock",
                                     allow_abbrev=False)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="Batch output folder of the baseline run")
    parser.add_argument("--report", type=Path, required=True, help="New JSON report (never overwritten)")
    args = parser.parse_args(argv)
    try:
        if args.report.exists():
            raise FileExistsError(f"Report exists: {args.report}")
        report = check_run(_read(args.lock), args.output)
        report.update(created_at=dt.datetime.now(dt.timezone.utc).isoformat(), lock_path=str(args.lock),
                      output=str(args.output))
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
    except (OSError, ValueError, KeyError) as exc:
        print(f"check_baseline_identity: {exc}", file=sys.stderr)
        return 2
    matched = sum(row["status"] == "MATCH" for row in report["documents"])
    print(f"{report['lock_id']}: {matched}/{len(report['documents'])} PDF match; {report['status']} -> {args.report}")
    return 0 if report["status"] == "MATCH" else 1


if __name__ == "__main__":
    raise SystemExit(main())
