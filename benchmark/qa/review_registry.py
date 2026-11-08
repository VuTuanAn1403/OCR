"""Import existing operator review packets, preserving signals rather than asserting defects."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from .evidence import EvidenceStore, require
from .error_registry import error_id, snapshot, validate_registry

REASON_CODES = {
    "O2O_020_source_check": "E04-TEXT",
    "repetition_noise_unverified": "E04-TEXT",
    "PULL_QUOTE_SEPARATED": "E05-ORDER",
    "TABLE_SOURCE_UNMAPPED": "E07-OWNERSHIP",
    "TABLE_FURNITURE_CONFLICT": "E07-OWNERSHIP",
    "UNRESOLVED_SOURCE": "E07-OWNERSHIP",
}


def _within(path, root):
    path = Path(path).resolve(strict=True)
    require(path.is_relative_to(root), "Packet origin escapes the evidence root")
    return path


def source_for(row):
    box = row["bbox"]
    return {"scope": "cell" if "row" in row["locator"] else "region",
            "document_id": row["document_id"], "pdf_sha256": row["pdf_sha256"], "page": row["page"],
            "source_id": row["source_id"], "locator": deepcopy(row["locator"]),
            "bbox": deepcopy(box) if box else None, "coordinate_space": row["coordinate_space"],
            "transforms": deepcopy(row["transforms"]), "geometry_reason": None if box else "unplaced_source"}


def _crop(row, packet_dir, files, store):
    crop = row["crop"]
    if crop["status"] == "UNAVAILABLE":
        require(not crop.get("assets"), "Unavailable crop cannot carry assets")
        return {"status": "UNAVAILABLE", "reason": crop["reason"], "assets": {}}
    require(crop["status"] in ("AVAILABLE", "AVAILABLE_WITH_WARNINGS") and crop.get("assets"), "Invalid packet crop")
    assets = {}
    for name, asset in crop["assets"].items():
        require(files.get(asset["path"]) == asset["sha256"], "Crop is not bound to the packet file manifest")
        # Let the root resolver reject traversal before constructing an absolute path.
        relative = packet_dir.relative_to(store.root).as_posix() + "/" + asset["path"]
        assets[name] = store.ref(store.path(relative), asset["sha256"])
    return {"status": crop["status"], "reason": None, "assets": assets}


def validate_operator_record(record, store):
    """Bind copied observations back to the exact packet bytes, including raw/source geometry."""
    evidence = record["evidence"]
    items = store.json(evidence["review_items"])
    require(items.get("schema_version") == "operator-review-items-v1", "Invalid review items schema")
    rows = [row for row in items["items"] if row["review_id"] == record["origin"]["id"]]
    require(len(rows) == 1 and rows[0] == record["observation"], "Observation differs from the original review row")
    row = rows[0]
    require(record["source"] == source_for(row) and record["actual"] == {
        "text_raw": row["text_raw"], "normalized": None, "prediction": row["text_corrected"]},
        "Registry changed raw text, prediction or source geometry")
    packet = store.json(evidence["review_packet"])
    require(packet.get("schema_version") == "operator-review-packet-v1"
            and packet.get("status") == "READY_FOR_OPERATOR_REVIEW"
            and packet.get("quality_acceptance") == "NOT_EVALUATED", "Incomplete operator packet")
    origin = packet["origins"][row["document_id"]]
    require(record["origin"]["source_snapshot_sha256"] == origin["extraction_sha256"], "Origin extraction identity differs")
    packet_dir = store.path(evidence["review_packet"]["path"]).parent
    for name, checksum in packet["files"].items():
        relative = packet_dir.relative_to(store.root).as_posix() + "/" + name
        store.verify({"path": relative, "sha256": checksum})
    require(evidence["review_items"] == store.ref(packet_dir / "review.json", packet["files"]["review.json"]),
            "Review items do not belong to the packet")
    require(evidence["origin_pdf"]["sha256"] == row["pdf_sha256"], "Review signal needs its original PDF")
    for name, field in (("extraction", "extraction_sha256"), ("receipt", "ocr_receipt_sha256"), ("completion", "completion_sha256")):
        require(evidence["origin_" + name]["sha256"] == origin[field], "Original observation artifact hash differs")
    extraction = store.json(evidence["origin_extraction"])
    require(extraction["doc_id"] == row["document_id"] and extraction["doc_sha16"] == row["pdf_sha256"][:16],
            "Original extraction document identity differs")
    require(record["crop"] == _crop(row, packet_dir, packet["files"], store), "Crop binding differs from the original review row")


def import_review_packet(packet_dir, evidence_root, *, created_at, creator, historical=False):
    """Read only: checksum original origins and packet files, create one snapshot of selected signals.

    This does not rerun the publication verifier or determine whether review
    signals are actual defects. Original code/model/runtime identity remains in
    the referenced manifests and receipts, not reconstructed from current HEAD.
    """
    require(type(historical) is bool, "Historical flag must be boolean")
    store = EvidenceStore(evidence_root)
    packet_dir = _within(packet_dir, store.root)
    require(packet_dir != store.root, "Packet must be a subdirectory of evidence root")
    packet_ref = store.ref(packet_dir / "packet.json")
    packet = store.json(packet_ref)
    require(packet.get("schema_version") == "operator-review-packet-v1"
            and packet.get("status") == "READY_FOR_OPERATOR_REVIEW"
            and packet.get("quality_acceptance") == "NOT_EVALUATED"
            and packet.get("usage") == "development_operator_review"
            and packet.get("contains_predictions") is True and packet.get("new_model_inference") is False,
            "Expected a complete development operator review packet")
    require(not (packet_dir / "failure.json").exists(), "Packet contains a failure marker")
    files = packet["files"]
    require(isinstance(files, dict) and "review.json" in files and "queue.jsonl" in files, "Incomplete packet file manifest")
    file_refs = {}
    for name, checksum in files.items():
        relative = packet_dir.relative_to(store.root).as_posix() + "/" + name
        file_refs[name] = store.ref(store.path(relative), checksum)
    items = store.json(file_refs["review.json"])
    require(items.get("schema_version") == "operator-review-items-v1" and isinstance(items.get("items"), list),
            "Invalid packet items")
    require(type(packet["selected_items"]) is int and packet["selected_items"] == len(items["items"]), "Selected coverage differs")
    origins, protected_directories = {}, [packet_dir]
    for document_id, origin in packet["origins"].items():
        directory = _within(origin["source_dir"], store.root)
        pdf = _within(origin["pdf_path"], store.root)
        artifacts = {name: store.ref(directory / filename, origin[key]) for name, filename, key in (
            ("extraction", "extraction.json", "extraction_sha256"),
            ("receipt", "ocr_receipt.json", "ocr_receipt_sha256"),
            ("completion", "COMPLETED.json", "completion_sha256"))}
        artifacts["manifest"] = store.ref(directory / "manifest.json")
        artifacts["pdf"] = store.ref(pdf, origin["pdf_sha256"])
        extraction = store.json(artifacts["extraction"])
        require(extraction["doc_id"] == document_id and extraction["doc_sha16"] == origin["pdf_sha256"][:16],
                "Packet origin document identity differs")
        origins[document_id] = {"run_id": directory.name, "identity_status": "REFERENCED_NOT_REPLAYED", "artifacts": artifacts}
        protected_directories.append(directory)
    records, seen, locations = [], set(), set()
    for row in items["items"]:
        require(row["review_id"] not in seen and row["document_id"] in origins, "Duplicate review ID or unknown origin")
        seen.add(row["review_id"])
        origin = packet["origins"][row["document_id"]]
        require(row["pdf_sha256"] == origin["pdf_sha256"], "Review row PDF differs from its origin")
        source = source_for(row)
        # Multiple cells can share a source ID; locator, not source text, defines multiplicity.
        location = (row["document_id"], row["page"], str(sorted(row["locator"].items())))
        require(location not in locations, "Duplicate review source locator")
        locations.add(location)
        record_origin = {"kind": "operator_review", "id": row["review_id"],
                         "source_snapshot_sha256": origin["extraction_sha256"], "observed_at": None,
                         "observed_at_reason": "Original operator packet does not record an observation timestamp"}
        reasons = row["reasons"]
        require(isinstance(reasons, list) and reasons and all(isinstance(r, str) and r.strip() for r in reasons), "Missing review reasons")
        record = {"error_id": error_id({"origin": record_origin, "source": source}),
            "taxonomy_version": "ocr-error-taxonomy-v1", "error_codes": sorted({REASON_CODES[r] for r in reasons if r in REASON_CODES}),
            "record_revision": 1, "recorded_at": created_at, "creator": creator,
            "finding_kind": "HISTORICAL_FINDING" if historical else "REVIEW_SIGNAL", "historical": historical,
            "origin": record_origin, "source": source, "runs": {"baseline": None, "candidate": origins[row["document_id"]]},
            "expected": {"kind": "UNRESOLVED", "value": None, "evidence": []},
            "actual": {"text_raw": row["text_raw"], "normalized": None, "prediction": row["text_corrected"]},
            "observation": deepcopy(row), "symptom": "; ".join(reasons), "suspected_modules": [], "root_cause": None,
            "reproduction": {"argv": None, "reason": "Source review signal only; defect not independently reproduced", "evidence": []},
            "severity": "UNASSESSED", "lifecycle": "NEEDS_REVIEW", "quality_status": "NOT_EVALUATED",
            "crop": _crop(row, packet_dir, files, store),
            "evidence": {"review_packet": packet_ref, "review_items": file_refs["review.json"],
                         **{"origin_" + name: ref for name, ref in origins[row["document_id"]]["artifacts"].items()}},
            "related_issue_ids": [],
            "verification": {"counterexample_before": [], "regression_after": [], "source_preservation": [],
                             "paired_report": None, "proposed_fix": None}}
        records.append(record)
    evidence = [{"path": path, "sha256": checksum} for path, checksum in sorted(store.references.items())]
    result = snapshot(records, created_at=created_at, creator=creator, evidence=evidence)
    validate_registry(result, store)
    return result, protected_directories
