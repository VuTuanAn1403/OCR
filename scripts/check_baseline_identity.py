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
import hashlib
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


def check_new_inputs(lock: dict, output: Path, *, root=ROOT, valid_ocr=None) -> dict:
    """Bind new PDF receipts to the frozen runtime, without changing the baseline lock."""
    from ocr_artifacts.hashing import sha256_file
    from ocr_pipeline.backend import ocr_identity

    def digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                         separators=(",", ":")).encode("utf-8")).hexdigest()

    def relative(value):
        path = Path(value).resolve()
        return path.relative_to(Path(root).resolve()).as_posix() if path.is_relative_to(Path(root).resolve()) else str(path)

    output = Path(output).resolve()
    paths = {name: output / name for name in ("batch_config.json", "batch_input_manifest.json")}
    hashes = {name: sha256_file(path) for name, path in paths.items()}
    batch = _read(paths["batch_config.json"])
    backend = batch["backend"]
    records = _read(paths["batch_input_manifest.json"])["documents"]
    checks = {
        "baseline_locked": lock.get("status") == "LOCKED",
        "code": backend.get("code_fingerprints") == lock["code"]["code_fingerprints"]
                and backend["source_fingerprint"] == lock["code"]["source_fingerprint"],
        "resolved_profile": digest(backend["config"]) == lock["config"]["profile_digest"],
        "model_hashes": {relative(p): h for p, h in backend["model_hashes"].items()} == lock["models"]["sha256"],
        "dependency_locks": {relative(p): h for p, h in backend["lock_hashes"].items()}
                            == {p: row["sha256"] for p, row in lock["locks"].items()},
        "interpreters": {role: relative(backend[role + "_python"]) for role in ("text", "docling")}
                        == lock["interpreters"],
        "request_defaults": {k: batch.get(k) for k in ("assets", "output_mode")} == lock["request_defaults"],
    }
    if not records or len({r["id"].casefold() for r in records}) != len(records):
        raise ValueError("New-input manifest must contain distinct PDF IDs")
    if len({r["pdf_sha256"] for r in records}) != len(records):
        raise ValueError("New-input manifest repeats identical PDF bytes")
    locked_hashes = {r["pdf_sha256"] for r in lock["inputs"]}
    projected, input_hashes = [], {}
    for record in records:
        folder = (output / record["id"]).resolve()
        if folder.parent != output or record.get("source_error") or record.get("duplicate_of"):
            raise ValueError("Invalid or duplicate new-input record")
        if type(record.get("total_pages")) is not int or record["total_pages"] <= 0:
            raise ValueError("New-input PDF must declare its full physical page count")
        pdf_hash = sha256_file(record["path"])
        input_hashes[record["id"]] = pdf_hash
        checks[f"input:{record['id']}"] = pdf_hash == record["pdf_sha256"] and pdf_hash not in locked_hashes
        request = {**backend, "pdf_sha256": record["pdf_sha256"],
                   "assets": batch["assets"], "output_mode": batch["output_mode"]}
        projected.append({**record, "ocr_identity": ocr_identity(request)})
    report = check_run({"lock_id": lock.get("lock_id"), "inputs": projected}, output, valid_ocr=valid_ocr)
    checks["batch_snapshot_unchanged"] = all(sha256_file(paths[n]) == h for n, h in hashes.items())
    report.update(scope="NEW_INPUTS_FROZEN_BASELINE_RUNTIME", baseline_checks=checks,
                  batch_snapshot_sha256=hashes, current_input_sha256=input_hashes,
                  note="Per-PDF identities are recomputed with new input hashes only after comparing every locked runtime component; baseline lock is unchanged.")
    if not all(checks.values()):
        report["status"] = "MISMATCH"
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare OCR receipts of a run with a baseline lock",
                                     allow_abbrev=False)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="Batch output folder of the baseline run")
    parser.add_argument("--report", type=Path, required=True, help="New JSON report (never overwritten)")
    parser.add_argument("--new-inputs", action="store_true",
                        help="Check a disjoint input batch against the baseline's frozen runtime/config/model identity")
    args = parser.parse_args(argv)
    try:
        if args.report.exists():
            raise FileExistsError(f"Report exists: {args.report}")
        if args.report.resolve().is_relative_to(args.output.resolve()):
            raise ValueError("Write the identity report outside the batch output")
        checker = check_new_inputs if args.new_inputs else check_run
        report = checker(_read(args.lock), args.output)
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
