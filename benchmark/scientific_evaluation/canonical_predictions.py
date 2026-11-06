"""Read-only benchmark inventory for acknowledged canonical GPU predictions."""
from __future__ import annotations

import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from ocr_artifacts.atomic_io import atomic_write_json
from ocr_artifacts.digest import sha256_json_compact
from ocr_artifacts.hashing import sha256_file
from ocr_pipeline.analysis_run import read, verify_extraction_source
from ocr_pipeline.backend import ocr_identity
from ocr_pipeline.scheduler import PHASES
from ocr_runtime.pipeline_policy import PROFILE, SOURCE_POLICY, validate_profile


def _require(condition, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _publication(root: Path) -> tuple[dict, int, list[dict]]:
    database = root / "batch_state.sqlite"
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
        connection.execute("BEGIN")
        meta = {key: json.loads(value) for key, value in connection.execute("SELECT key,value FROM meta")}
        revision = meta["published_revision"]
        _require(type(revision) is int and revision >= 0 and revision == meta["prepared_revision"],
                 f"Unacknowledged batch revision: {root}")
        projection, checksum = connection.execute(
            "SELECT projection,workbook_sha256 FROM revisions WHERE revision=?", (revision,)
        ).fetchone() or (None, None)
        records = json.loads(projection) if projection else []
        current = [json.loads(row[0]) for row in connection.execute("SELECT payload FROM documents ORDER BY ordinal")]
        _require(records and records == current, f"Acknowledged projection differs from the ledger: {root}")
    _require(checksum and checksum == sha256_file(root / f"MA_TRAN_DEM_TU_KHOA_{len(records)}_FILES.xlsx"),
             f"Acknowledged workbook differs from disk: {root}")
    return meta["identity"], revision, records


def _scheduler_evidence(directory: Path) -> dict:
    scheduler = read(directory / "gpu_scheduler.json")
    _require(scheduler.get("status") == "COMPLETED" and scheduler.get("device") == "cuda"
             and scheduler.get("schema_version") == "document-two-phase-v1",
             f"Missing completed CUDA scheduler evidence: {directory}")
    events, reused = [], []
    for phase in PHASES:
        detail = scheduler["phases"][phase]
        if detail.get("resumed") is True and phase != "export":
            _require(detail.get("key") and detail.get("generation"), f"Unidentified reused stage: {phase}")
            reused.append(phase)
        else:
            events.extend([(phase, "START"), (phase, "TREE_EXITED")])
    _require([(event["phase"], event["event"]) for event in scheduler["events"]] == events,
             f"Missing or out-of-order process exits: {directory}")
    return {"generation": scheduler["generation"], "gpu": scheduler["initial_vram"],
            "reused_phases": reused, "scheduler_sha256": sha256_file(directory / "gpu_scheduler.json")}


def _document(root: Path, snapshot: dict, record: dict, config: dict) -> dict:
    doc_id = snapshot["id"]
    directory = root / doc_id
    _require(directory.resolve().parent == root and directory.name == doc_id
             and Path(record["output"]).resolve() == directory.resolve()
             and record["outcome"] == "SUCCEEDED", f"Missing successful prediction for {doc_id}")
    pdf = Path(snapshot["path"])
    checksum = sha256_file(pdf)
    _require(pdf.stem == doc_id and checksum == snapshot["pdf_sha256"], f"PDF changed for {doc_id}")
    proof = verify_extraction_source(directory)
    backend = config["backend"]
    identity = ocr_identity({**backend, "pdf_sha256": checksum, "assets": config["assets"],
                             "output_mode": config["output_mode"]})
    manifest = read(directory / "manifest.json")
    _require(proof["completion_sha256"] == record["completion_sha256"]
             and proof["ocr_identity"] == identity and manifest.get("profile") == PROFILE
             and manifest.get("document_id") == doc_id and manifest.get("file_hash") == checksum[:16]
             and type(snapshot["total_pages"]) is int and snapshot["total_pages"] > 0
             and proof["total_pages"] == snapshot["total_pages"],
             f"Prediction identity or coverage mismatch for {doc_id}")
    return {"id": doc_id, "pdf_sha256": checksum, "pdf_path": str(pdf),
            "export_source_fingerprint": manifest["source_fingerprint"],
            "export_model_hashes": manifest["model_hashes"],
            **proof, "scheduler": _scheduler_evidence(directory)}


def collect_predictions(roots: list[Path]) -> dict:
    documents, batches, seen_ids, seen_hashes = [], [], set(), set()
    for root in roots:
        root = root.resolve()
        identity, revision, records = _publication(root)
        config = read(root / "batch_config.json")
        backend = config.get("backend")
        _require(isinstance(backend, dict), f"Expected an original canonical CUDA batch: {root}")
        validate_profile(backend["config"])
        snapshots = read(root / "batch_input_manifest.json")["documents"]
        fields = ("id", "path", "pdf_sha256", "size")
        inputs = [{key: item[key] for key in fields} for item in snapshots]
        _require(config == identity["config"] and inputs == identity["inputs"]
                 and inputs == [{key: item[key] for key in fields} for item in records]
                 and identity["batch_id"] == sha256_json_compact(
                     {key: value for key, value in identity.items() if key != "batch_id"}),
                 f"Batch configuration or input identity changed: {root}")
        _require(backend["device"] == "cuda" and all(backend.get(key) for key in (
            "model_hashes", "lock_hashes", "text_python", "docling_python", "source_fingerprint",
        )), f"Missing CUDA runtime identity: {root}")
        for snapshot, record in zip(snapshots, records, strict=True):
            key, checksum = snapshot["id"].casefold(), snapshot["pdf_sha256"]
            _require(key not in seen_ids and checksum not in seen_hashes,
                     f"Duplicate benchmark prediction: {snapshot['id']}")
            documents.append({**_document(root, snapshot, record, config), "batch_id": identity["batch_id"]})
            seen_ids.add(key)
            seen_hashes.add(checksum)
        batches.append({"path": str(root), "batch_id": identity["batch_id"], "published_revision": revision,
                        "configuration_sha256": sha256_file(root / "batch_config.json"),
                        "runtime": {key: backend[key] for key in ("model_hashes", "lock_hashes",
                                    "text_python", "docling_python", "source_fingerprint")}})
    _require(documents, "No benchmark predictions supplied")
    return {"batches": batches, "documents": sorted(documents, key=lambda doc: doc["id"])}


def pair_predictions(baseline: dict, candidate: dict) -> list[dict]:
    references = {doc["id"]: doc for doc in baseline["documents"]}
    proposed = {doc["id"]: doc for doc in candidate["documents"]}
    _require(references.keys() == proposed.keys(), "Baseline and candidate document membership differs")
    pairs = []
    for doc_id, old in references.items():
        new = proposed[doc_id]
        _require((old["pdf_sha256"], old["total_pages"]) == (new["pdf_sha256"], new["total_pages"]),
                 f"Baseline and candidate input differs for {doc_id}")
        _require(old["source_dir"] != new["source_dir"], f"Baseline and candidate reuse the same prediction: {doc_id}")
        pairs.append({"id": doc_id, "pdf_sha256": old["pdf_sha256"], "total_pages": old["total_pages"],
                      "baseline_completion_sha256": old["completion_sha256"],
                      "candidate_completion_sha256": new["completion_sha256"]})
    return pairs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, nargs="+", required=True)
    parser.add_argument("--baseline", type=Path, nargs="+")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report_path = args.report.resolve()
    if report_path.exists() or any(
        report_path.is_relative_to(path.resolve()) for path in [*args.candidate, *(args.baseline or [])]
    ):
        parser.error("Report must be a new path outside the source batches")
    try:
        candidate = collect_predictions(args.candidate)
        baseline = collect_predictions(args.baseline) if args.baseline else None
        pairs = pair_predictions(baseline, candidate) if baseline else None
        report = {"status": "PREDICTIONS_VERIFIED", "candidate": candidate, "baseline": baseline, "pairs": pairs}
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        report = {"status": "PREDICTIONS_REJECTED", "reason": f"{type(exc).__name__}: {exc}"}
    atomic_write_json(report_path, {"schema_version": "canonical-benchmark-predictions-v1",
                      "profile": PROFILE, "source_policy": SOURCE_POLICY, "accuracy": "NOT_EVALUATED", **report})
    return int(report["status"] != "PREDICTIONS_VERIFIED")


if __name__ == "__main__":
    raise SystemExit(main())
