"""Read-only integrity/coverage/provenance audit of an existing PDF batch.

Writes only the explicitly selected report outside the batch. Never repairs
receipts, rewrites source PDFs, updates SQLite or starts OCR/model inference.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ocr_artifacts.hashing import sha256_file
from ocr_pipeline.artifact_validation import validate_document_artifacts
from ocr_pipeline.completion import verify_completed
from ocr_pipeline.document import validate_gpu_source


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def audit(output, *, validate=False):
    output = Path(output).resolve()
    records = read(output / "batch_input_manifest.json")["documents"]
    ledger, identity = {}, None
    database = output / "batch_state.sqlite"
    if database.is_file():
        connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
        try:
            connection.execute("PRAGMA query_only=ON")
            identity = json.loads(connection.execute("SELECT value FROM meta WHERE key='identity'").fetchone()[0])
            ledger = {row["id"]: row for (payload,) in connection.execute("SELECT payload FROM documents")
                      for row in [json.loads(payload)]}
        finally:
            connection.close()
    results = []
    for record in records:
        doc_id = record["id"]
        directory = output / doc_id
        if directory.parent != output:
            raise ValueError("Document ID escapes batch output")
        entry = {"id": doc_id, "expected_pages": record.get("total_pages"),
                 "snapshot_pdf_sha256": record.get("pdf_sha256"), "directory_exists": directory.is_dir(),
                 "ledger_outcome": ledger.get(doc_id, {}).get("outcome"),
                 "completion_valid": verify_completed(directory)}
        try:
            source = Path(record["path"])
            entry["current_pdf_sha256"] = sha256_file(source)
            entry["input_matches_batch_snapshot"] = entry["current_pdf_sha256"] == record.get("pdf_sha256")
            manifest = read(directory / "manifest.json")
            entry.update(selected_pages=manifest.get("selected_pages"), total_pages=manifest.get("total_pages"),
                         manifest_source=manifest.get("file_hash"), profile=manifest.get("profile"),
                         device=manifest.get("device"), backend_devices=manifest.get("backend_devices"),
                         source_fingerprint=manifest.get("source_fingerprint"),
                         gpu_runtime=manifest.get("gpu_runtime"))
            entry["manifest_matches_current_input"] = manifest.get("file_hash") == entry["current_pdf_sha256"][:16]
            entry["full_coverage"] = (manifest.get("selected_pages") == list(range(1, record["total_pages"] + 1))
                                      and manifest.get("total_pages") == record["total_pages"])
            stored = directory / "validation.json"
            if stored.is_file():
                validation = read(stored)
                entry["stored_validation"] = {"status": validation["status"], "errors": len(validation["errors"]),
                                              "warnings": len(validation["warnings"])}
            if validate:
                validation = validate_document_artifacts(directory)
                entry["validation"] = {"status": validation["status"], "errors": len(validation["errors"]),
                                       "warnings": len(validation["warnings"]), "first_errors": validation["errors"][:5]}
            else:
                entry["validation"] = {"status": "NOT_RERUN", "reason": "Use --validate for the full document validator; large legacy inline JSON can require several GB of memory."}
            try:
                validate_gpu_source(directory)
                entry["gpu_source_gate"] = "PASS"
            except (ValueError, KeyError, TypeError, OSError) as exc:
                entry["gpu_source_gate"] = f"REJECTED: {type(exc).__name__}: {exc}"
            marker = directory / "COMPLETED.json"
            if marker.is_file():
                files = read(marker)["files"]
                missing, changed = [], []
                for name, checksum in files.items():
                    target = directory / name
                    if not target.resolve().is_relative_to(directory):
                        changed.append(name)
                    elif not target.is_file():
                        missing.append(name)
                    elif sha256_file(target) != checksum:
                        changed.append(name)
                entry["completion_files"] = {"listed": len(files), "missing": missing, "changed": changed}
            receipt = directory / "ocr_receipt.json"
            if receipt.is_file():
                entry["ocr_identity"] = read(receipt).get("ocr_identity")
            request_path = output / "logs" / f"{doc_id}.request.json"
            if request_path.is_file():
                request = read(request_path)["request"]
                entry["last_request_identity"] = request.get("ocr_identity")
                entry["last_request_code_fingerprints"] = request.get("code_fingerprints")
        except (OSError, ValueError, TypeError, KeyError) as exc:
            entry["audit_error"] = f"{type(exc).__name__}: {exc}"
        results.append(entry)
        print(f"{doc_id}: completion={entry['completion_valid']}, validation={entry.get('validation', {}).get('status')}", flush=True)
    return {"scope": "READ_ONLY_NO_OCR", "batch": str(output), "batch_identity": identity,
            "documents_expected": len(records), "pages_expected": sum(r.get("total_pages") or 0 for r in records),
            "documents": results, "accuracy": "NOT_EVALUATED"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--validate", action="store_true", help="Run the full validator, in addition to hash/coverage checks")
    args = parser.parse_args(argv)
    if args.report.resolve().is_relative_to(args.output.resolve()):
        parser.error("--report must be outside the audited batch")
    result = audit(args.output, validate=args.validate)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
