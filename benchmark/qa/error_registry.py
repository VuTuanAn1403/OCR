"""Versioned, append-only error observations with explicitly limited evidence claims."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
import math

from .evidence import EvidenceStore, digest, is_sha, require

SCHEMA = "ocr-error-registry-v1"
TAXONOMY_VERSION = "ocr-error-taxonomy-v1"
ERROR_CODES = (
    "E01-PDF", "E02-IMAGE", "E03-DETECTION", "E04-TEXT", "E04-VI", "E05-ORDER", "E05-LAYOUT",
    "E06-TABLE", "E06-FORMULA", "E07-OWNERSHIP", "E08-POSTPROCESS", "E09-KEYWORD", "E10-EXPORT", "E10-RUNTIME",
)
STATES = ("OPEN", "NEEDS_REVIEW", "REPRODUCED", "CAUSE_VERIFIED", "FIX_VERIFIED_TECHNICAL")
KINDS = ("PROPOSED_CATEGORY", "REVIEW_SIGNAL", "OBSERVED_DEFECT", "HISTORICAL_FINDING")


def _keys(value, keys, name):
    require(isinstance(value, dict) and value.keys() == set(keys.split()), f"Invalid {name} fields")


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _timestamp(value):
    require(_text(value) and datetime.fromisoformat(value).utcoffset() is not None,
            "Timestamp must include a timezone")


def error_id(identity):
    return "ERR-" + digest(identity)


def _refs(refs, store, *, required=False):
    require(isinstance(refs, list) and (refs or not required), "Required evidence list is missing")
    for ref in refs:
        store.verify(ref)


def _source(source):
    _keys(source, "scope document_id pdf_sha256 page source_id locator bbox coordinate_space transforms geometry_reason", "source")
    require(source["scope"] in ("batch", "document", "page", "region", "cell"), "Unknown source scope")
    if source["scope"] != "batch":
        require(_text(source["document_id"]) and is_sha(source["pdf_sha256"]), "Document identity required")
    else:
        require(source["document_id"] is None and source["pdf_sha256"] is None, "Batch uses null document identity")
    if source["scope"] in ("batch", "document"):
        require(source["page"] is None, "Non-page scope must use null page")
        require(source["bbox"] is None, "Non-page scope must use null bbox")
    else:
        require(type(source["page"]) is int and source["page"] >= 1, "Physical page must be one-based")
    require(source["source_id"] is None or _text(source["source_id"]), "Invalid source ID")
    locator = source["locator"]
    if source["scope"] in ("region", "cell"):
        require(isinstance(locator, dict) and locator, "Region/cell source needs a locator")
        if "row" in locator or "col" in locator:
            require(locator.keys() == {"item_id", "row", "col"} and _text(locator["item_id"])
                    and all(type(locator[k]) is int and locator[k] >= 0 for k in ("row", "col")), "Invalid cell locator")
        else:
            require(locator.keys() in ({"item_id"}, {"frozen_source_id"}) and all(map(_text, locator.values())),
                    "Invalid source locator")
    else:
        require(locator is None, "Non-region scope must use null locator")
    box = source["bbox"]
    require(isinstance(source["transforms"], list), "Source transforms must be retained")
    if box is None:
        require(_text(source["geometry_reason"]), "Missing geometry requires a reason")
    else:
        require(isinstance(box, list) and len(box) == 4
                and all(type(v) in (int, float) and math.isfinite(v) for v in box)
                and box[0] < box[2] and box[1] < box[3] and _text(source["coordinate_space"]),
                "BBox requires finite xyxy values and a coordinate space")
        require(source["geometry_reason"] is None, "Placed geometry cannot claim to be missing")


def _record(record, store):
    _keys(record, "error_id taxonomy_version error_codes record_revision recorded_at creator finding_kind historical "
          "origin source runs expected actual observation symptom suspected_modules root_cause reproduction "
          "severity lifecycle quality_status crop evidence related_issue_ids verification", "record")
    require(record["taxonomy_version"] == TAXONOMY_VERSION, "Unsupported taxonomy version")
    codes = record["error_codes"]
    require(isinstance(codes, list) and len(set(codes)) == len(codes) and all(code in ERROR_CODES for code in codes),
            "Invalid or duplicate taxonomy code")
    require(type(record["record_revision"]) is int and record["record_revision"] >= 1, "Invalid revision")
    _timestamp(record["recorded_at"])
    require(_text(record["creator"]), "Creator is required")
    require(record["finding_kind"] in KINDS and type(record["historical"]) is bool, "Invalid finding kind")
    require(record["finding_kind"] != "HISTORICAL_FINDING" or record["historical"], "Historical finding must stay explicit")
    _source(record["source"])
    origin = record["origin"]
    _keys(origin, "kind id source_snapshot_sha256 observed_at observed_at_reason", "origin")
    require(_text(origin["kind"]) and _text(origin["id"]) and is_sha(origin["source_snapshot_sha256"]), "Invalid origin")
    if origin["observed_at"] is None:
        require(_text(origin["observed_at_reason"]), "Unknown original date needs a reason")
    else:
        _timestamp(origin["observed_at"])
        require(origin["observed_at_reason"] is None, "Original date reason must be null if date is known")
    identity = {"origin": origin, "source": record["source"]}
    require(record["error_id"] == error_id(identity), "Error ID does not match its immutable source identity")
    _keys(record["runs"], "baseline candidate", "runs")
    for run in record["runs"].values():
        if run is not None:
            _keys(run, "run_id identity_status artifacts", "run")
            require(_text(run["run_id"]) and run["identity_status"] == "REFERENCED_NOT_REPLAYED", "Invalid run identity")
            require(isinstance(run["artifacts"], dict) and run["artifacts"], "Run needs identity artifacts")
            for ref in run["artifacts"].values():
                store.verify(ref)
    expected = record["expected"]
    _keys(expected, "kind value evidence", "expected")
    require(expected["kind"] in ("UNRESOLVED", "CONTRACT_ORACLE", "INDEPENDENT_GT"), "Unknown oracle kind")
    require(expected["kind"] != "UNRESOLVED" or (expected["value"] is None and not expected["evidence"]),
            "Unresolved expected must remain null")
    _refs(expected["evidence"], store, required=expected["kind"] != "UNRESOLVED")
    require(expected["kind"] == "UNRESOLVED" or expected["value"] is not None, "Resolved oracle needs a value")
    actual = record["actual"]
    _keys(actual, "text_raw normalized prediction", "actual")
    require(all(value is None or isinstance(value, str) for value in actual.values()), "Text evidence must be string or null")
    require(isinstance(record["observation"], dict) and _text(record["symptom"]), "Raw observation and symptom required")
    require(isinstance(record["suspected_modules"], list) and all(map(_text, record["suspected_modules"])), "Invalid hypotheses")
    require(record["severity"] in ("UNASSESSED", "MEDIUM", "HIGH", "CRITICAL"), "Invalid severity")
    if record["severity"] != "UNASSESSED":
        require(record["finding_kind"] in ("OBSERVED_DEFECT", "HISTORICAL_FINDING") and expected["kind"] != "UNRESOLVED",
                "Assessed severity needs an observed impact and resolved oracle")
    state = record["lifecycle"]
    require(state in STATES, "Unsupported lifecycle; quality acceptance requires the independent release workflow")
    require(record["quality_status"] == "NOT_EVALUATED", "Registry cannot grant quality acceptance")
    _keys(record["reproduction"], "argv reason evidence", "reproduction")
    reproduction = record["reproduction"]
    require(reproduction["argv"] is None or (isinstance(reproduction["argv"], list)
            and reproduction["argv"] and all(map(_text, reproduction["argv"]))), "Invalid reproduction argv")
    require(reproduction["argv"] is not None or _text(reproduction["reason"]), "Missing reproduction needs a reason")
    _refs(reproduction["evidence"], store, required=state in STATES[2:])
    if state in STATES[2:]:
        require(record["finding_kind"] == "OBSERVED_DEFECT" and expected["kind"] != "UNRESOLVED",
                "Reproduced defects need an oracle and explicit observed status")
    cause = record["root_cause"]
    if cause is not None:
        require(state in STATES[3:], "Unverified cause must stay in hypotheses")
        _keys(cause, "summary isolation evidence", "root cause")
        require(_text(cause["summary"]) and _text(cause["isolation"]), "Root cause needs an isolation explanation")
        _refs(cause["evidence"], store, required=True)
    if state in STATES[3:]:
        require(cause is not None, "Verified cause needs isolation evidence")
    crop = record["crop"]
    _keys(crop, "status reason assets", "crop")
    require(isinstance(crop["assets"], dict), "Invalid crop assets")
    if crop["status"] == "UNAVAILABLE":
        require(_text(crop["reason"]) and not crop["assets"], "Missing crop needs an explicit reason")
    else:
        require(crop["status"] in ("AVAILABLE", "AVAILABLE_WITH_WARNINGS") and crop["assets"]
                and crop["reason"] is None, "Available crop needs assets")
        for ref in crop["assets"].values():
            store.verify(ref)
    require(isinstance(record["evidence"], dict) and record["evidence"], "Record evidence is required")
    for ref in record["evidence"].values():
        store.verify(ref)
    require(isinstance(record["related_issue_ids"], list) and all(map(_text, record["related_issue_ids"])), "Invalid issue links")
    verification = record["verification"]
    _keys(verification, "counterexample_before regression_after source_preservation paired_report proposed_fix", "verification")
    for field in ("counterexample_before", "regression_after", "source_preservation"):
        _refs(verification[field], store, required=state == "FIX_VERIFIED_TECHNICAL")
    if verification["paired_report"] is not None:
        store.verify(verification["paired_report"])
    require(verification["proposed_fix"] is None or _text(verification["proposed_fix"]), "Invalid proposed fix")
    if state == "FIX_VERIFIED_TECHNICAL":
        require(all(run is not None for run in record["runs"].values()), "Verified fix needs both run identities")
        baseline, candidate = (record["runs"][name] for name in ("baseline", "candidate"))
        require(baseline["run_id"] != candidate["run_id"] and baseline["artifacts"] != candidate["artifacts"],
                "Verified fix requires distinct baseline and candidate evidence")
    if origin["kind"] == "operator_review":
        from .review_registry import validate_operator_record
        validate_operator_record(record, store)


def snapshot(records, *, created_at, creator, previous_registry=None, evidence=None):
    value = {"schema_version": SCHEMA, "taxonomy_version": TAXONOMY_VERSION,
             "created_at": created_at, "creator": creator, "previous_registry": previous_registry,
             "quality_status": "NOT_EVALUATED", "evidence": evidence or [], "records": records}
    return {**value, "snapshot_sha256": digest(value)}


def validate_registry(value, evidence_root, *, _chain=None):
    """Validate metadata, referenced bytes and history; not OCR accuracy or truth of declarations."""
    store = evidence_root if isinstance(evidence_root, EvidenceStore) else EvidenceStore(evidence_root)
    _keys(value, "schema_version taxonomy_version created_at creator previous_registry quality_status evidence records snapshot_sha256", "registry")
    require(value["schema_version"] == SCHEMA and value["taxonomy_version"] == TAXONOMY_VERSION, "Unsupported registry version")
    require(value["snapshot_sha256"] == digest({k: v for k, v in value.items() if k != "snapshot_sha256"}), "Snapshot digest mismatch")
    _timestamp(value["created_at"])
    require(_text(value["creator"]) and value["quality_status"] == "NOT_EVALUATED", "Invalid registry creator or quality claim")
    _refs(value["evidence"], store)
    records = value["records"]
    require(isinstance(records, list), "Registry records must be an array")
    latest, identities = {}, set()
    for record in records:
        _record(record, store)
        key = record["error_id"]
        prior = latest.get(key)
        require(record["record_revision"] == (prior["record_revision"] + 1 if prior else 1), "Duplicate or noncontiguous record revision")
        identity = digest({"origin": record["origin"], "source": record["source"]})
        require(prior is not None or identity not in identities, "Duplicate source finding")
        if prior:
            require(record["origin"] == prior["origin"] and record["source"] == prior["source"]
                    and record["historical"] == prior["historical"], "Revision changed immutable identity or history")
            require(record["observation"] == prior["observation"] and record["actual"] == prior["actual"],
                    "Revision cannot overwrite the original observation or raw evidence")
            if record["origin"]["kind"] == "operator_review":
                require(record["evidence"] == prior["evidence"], "Revision cannot replace the original packet evidence")
        identities.add(identity)
        latest[key] = record
    previous = value["previous_registry"]
    if previous is not None:
        chain = set(_chain or ())
        require(previous["sha256"] not in chain and len(chain) < 32, "Cyclic or excessively deep registry history")
        chain.add(previous["sha256"])
        parent = store.json(previous)
        validate_registry(parent, store, _chain=chain)
        require(len(records) > len(parent["records"]) and records[:len(parent["records"])] == parent["records"],
                "A registry update must append without rewriting or deleting prior records")
        require(datetime.fromisoformat(value["created_at"]) >= datetime.fromisoformat(parent["created_at"]),
                "Registry update predates its parent")
    store.verify_all()
    return {"schema_version": "ocr-error-registry-validation-v1", "status": "VALID_METADATA_AND_HASHES",
            "quality_status": "NOT_EVALUATED", "snapshot_sha256": value["snapshot_sha256"],
            "record_revisions": len(records), "distinct_findings": len(latest),
            "finding_kinds": dict(Counter(row["finding_kind"] for row in latest.values())),
            "lifecycle_counts": dict(Counter(row["lifecycle"] for row in latest.values())),
            "evidence_files": len(store.references),
            "limits": "Hashes and declared metadata only; no independent GT, causal verification or release approval."}
