"""Audit and seal human formula labels for development or a reviewed holdout sample."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ocr_artifacts.hashing import sha256_file
from ocr_runtime.paths import PROJECT_ROOT

from benchmark.scientific_evaluation.formula_alignment import ANNOTATION_SCHEMA, _frame, _reference_regions
from benchmark.scientific_evaluation.formula_policy import SAMPLE_SCHEMA, _sample
from src.ocr.collect.catalog import SOURCE_USE_AUDIT, read_sources, verify_company_splits
from .human_annotations import _identity, _nonempty, _read, _require, _resolve, _time, _write_new

SOURCE_SCHEMA = "ocr-formula-development-source-v1"
HOLDOUT_SOURCE_SCHEMA = "ocr-formula-holdout-source-v1"
INTAKE_SCHEMA = "ocr-formula-holdout-intake-v1"
SEAL_SCHEMA = "ocr-formula-ab-seal-v1"
ADJUDICATION_SCHEMA = "ocr-benchmark-adjudication-manifest-v1"
FRAME_FIELDS = ("page", "coordinate_space", "transforms", "width", "height")
DOC_FIELDS = ("document_id", "pdf_sha256", "total_pages")
LABEL_FIELDS = ("id", "bbox", "placement", "format", "content_raw", "equation_label")
IGNORE_FIELDS = ("id", "bbox", "reason")
INTAKE_FILES = ("sample", "sources", "splits", "source_use_audit")
PROTOCOL_PINS = {"sample": "formula_holdout_sample_sha256", "sources": "input_manifest_sha256",
                 "splits": "split_manifest_sha256", "source_use_audit": "near_duplicate_audit_sha256"}


@dataclass
class Source:
    documents: dict
    pages: dict
    sha256: str
    identities: list[tuple[Path, str]]
    partition: str
    intake: dict | None

    @property
    def intake_pin(self):
        return {"holdout_intake_sha256": self.intake["sha256"]} if self.intake is not None else {}


def _index(rows, key):
    _require(isinstance(rows, list), f"Expected list indexed by {key}")
    result = {}
    for row in rows:
        value = row.get(key) if isinstance(row, dict) else None
        valid = type(value) is int and value > 0 if key == "page" else _nonempty(value)
        _require(valid and value not in result, f"Invalid or duplicate {key}")
        result[value] = row
    return result


def _pick(row, fields):
    return {key: row[key] for key in fields}


def _pinned_files(path, manifest, names):
    result = {}
    for name in names:
        relative, expected = manifest.get(f"{name}_path"), manifest.get(f"{name}_sha256")
        _require(_nonempty(relative) and not Path(relative).anchor, f"{name} requires a relative path")
        target = _resolve(path.resolve().parent, relative)
        _require(sha256_file(target) == expected, f"{name} SHA-256 differs")
        result[name] = (target, expected)
    return result


def _holdout_intake(path, source_hash, guideline_hash, documents):
    value, digest = _read(path)
    reviewed_at = _time(value.get("reviewed_at"))
    _require(value.get("schema_version") == INTAKE_SCHEMA and value.get("status") == "REVIEWED"
             and value.get("source_manifest_sha256") == source_hash and value.get("guideline_sha256") == guideline_hash
             and reviewed_at is not None and reviewed_at <= datetime.now(timezone.utc),
             "Holdout intake requires reviewed source, guideline, and review time")
    files = _pinned_files(path, value, INTAKE_FILES)
    split = verify_company_splits(files["sources"][0], files["splits"][0], audit=files["source_use_audit"][0])
    _require(split.get("leakage_audit_schema") == SOURCE_USE_AUDIT and value.get("reviewed_by") == split["holdout_custodian"],
             "Holdout intake must be reviewed by the custodian of a source-use audited split")
    audit, audit_hash = _read(files["source_use_audit"][0])
    audited_at = _time(audit.get("reviewed_at"))
    _require(audit_hash == files["source_use_audit"][1] and audited_at is not None and audited_at <= reviewed_at,
             "Source-use audit must precede holdout intake review")
    sample, sample_hash = _read(files["sample"][0])
    _require(sample_hash == files["sample"][1] and sample.get("schema_version") == SAMPLE_SCHEMA,
             "Holdout intake requires the pinned formula sample")
    sources = read_sources(files["sources"][0])
    _sample(sample, split, sources)
    sample_docs = _index(sample["documents"], "document_id")
    _require(sample_docs.keys() == documents.keys(), "Holdout intake documents must equal the sampled documents")
    catalog = {row["document_id"]: row for row in sources if row["document_id"] in documents}
    for doc_id, doc in documents.items():
        expected = sample_docs[doc_id]
        _require(doc.get("pdf_sha256") == expected["pdf_sha256"] and doc.get("total_pages") == int(catalog[doc_id]["pages"])
                 and _index(doc.get("pages"), "page").keys() == set(expected["pages"]),
                 f"Holdout intake PDF or pages differ from the sample: {doc_id}")
    return {"sha256": digest, "custodian": split["holdout_custodian"], "reviewed_at": reviewed_at,
            "identities": [(path, digest), *files.values()], "catalog": catalog,
            "protocol_pins": {key: files[name][1] for name, key in PROTOCOL_PINS.items()}}


def _source(manifest_path, pdf_root, guideline_hash, intake_path):
    manifest, digest = _read(manifest_path)
    partition = manifest.get("partition")
    schema = HOLDOUT_SOURCE_SCHEMA if intake_path is not None else SOURCE_SCHEMA
    _require(manifest.get("schema_version") == schema and partition == ("holdout" if intake_path else "development"),
             "Use a development source manifest or a holdout source manifest with reviewed intake")
    documents = _index(manifest.get("documents"), "document_id")
    _require(documents, "Formula source must contain at least one document")
    intake = _holdout_intake(intake_path, digest, guideline_hash, documents) if intake_path is not None else None
    pages, identities = {}, [(manifest_path, digest)]
    if intake is not None:
        identities.extend(intake["identities"])
    for doc_id, doc in documents.items():
        _require(Path(doc_id).name == doc_id and not any(char in doc_id for char in "/\\:"), "Invalid source document ID")
        pdf_name = intake["catalog"][doc_id]["relative_path"] if intake is not None else f"{doc_id}.pdf"
        pdf = _resolve(Path(pdf_root), pdf_name)
        _require(sha256_file(pdf) == doc.get("pdf_sha256"), f"Source PDF hash differs: {doc_id}")
        identities.append((pdf, doc["pdf_sha256"]))
        total = doc.get("total_pages")
        selected = _index(doc.get("pages"), "page")
        _require(type(total) is int and total > 0 and selected and max(selected) <= total,
                 f"Invalid formula page universe for {doc_id}")
        for number, page in selected.items():
            _frame(page)
            image = _resolve(Path(manifest_path).parent, page.get("image"))
            _require(sha256_file(image) == page.get("image_sha256"), f"Source image hash differs: {doc_id} page {number}")
            identities.append((image, page["image_sha256"]))
            pages[doc_id, number] = page
    return Source(documents, pages, digest, identities, partition, intake)


def _packet(path, role, source, guideline_hash):
    documents, pages = source.documents, source.pages
    raw, digest = _read(path)
    _require(raw.get("schema_version") == ANNOTATION_SCHEMA and raw.get("role") == role
             and raw.get("intended_partition") == source.partition and raw.get("source_manifest_sha256") == source.sha256
             and raw.get("holdout_intake_sha256") == source.intake_pin.get("holdout_intake_sha256"),
             f"{role}: formula packet schema, role, source or partition differs")
    _require(raw.get("status") == "SUBMITTED", f"{role}: submitted formula packet required")
    actor, completed = _identity(raw.get("annotator")), _time(raw.get("completed_at"))
    required = ("source_images_checked", "no_model_or_native_text")
    if role in ("A", "B"):
        required += ("no_peer_before_submission",)
    _require(actor is not None and completed is not None and raw.get("actor_type") == "HUMAN"
             and raw.get("guideline_sha256") == guideline_hash and all(raw.get(key) is True for key in required),
             f"{role}: human source declarations and timezone-aware completion are required")
    if source.intake is not None:
        _require(source.intake["reviewed_at"] <= completed <= datetime.now(timezone.utc),
                 f"{role}: holdout submission must follow intake review and precede processing")
    labelled = _index(raw.get("documents"), "document_id")
    _require(labelled.keys() == documents.keys(), f"{role}: document coverage differs from source")
    records = {}
    for doc_id, document in labelled.items():
        _require(_pick(document, DOC_FIELDS) == _pick(documents[doc_id], DOC_FIELDS), f"{role}: source PDF identity differs")
        for number, page in _index(document.get("pages"), "page").items():
            key = doc_id, number
            _require(key in pages, f"{role}: page outside selected source")
            formulas, ignores, annotated = _reference_regions(page, pages[key])
            _require(annotated, f"{role}: unfinished page {doc_id}/{number}")
            _require(not (formulas.keys() & ignores.keys()), f"{role}: formula and ignore IDs must be disjoint")
            _require(all(row.get("bbox_format", "xyxy") == "xyxy" for row in (*formulas.values(), *ignores.values())),
                     f"{role}: boxes must be xyxy")
            records[key] = (page, formulas, ignores)
    _require(records.keys() == pages.keys(), f"{role}: page coverage differs from source")
    return {"raw": raw, "hash": digest, "actor": actor, "completed": completed, "pages": records}


def _sealed(path, a, b, source, guideline_hash):
    value, digest = _read(path)
    timestamp = _time(value.get("sealed_at"))
    _require(value.get("schema_version") == SEAL_SCHEMA and value.get("source_manifest_sha256") == source.sha256
             and value.get("guideline_sha256") == guideline_hash and value.get("annotation_sha256") == {"A": a["hash"], "B": b["hash"]}
             and _nonempty(value.get("received_by")) and timestamp is not None and timestamp >= max(a["completed"], b["completed"]),
             "A/B seal differs from submitted formula packets or completion times")
    _require(value.get("holdout_intake_sha256") == source.intake_pin.get("holdout_intake_sha256")
             and (source.intake is None or (value["received_by"] == source.intake["custodian"]
                                           and timestamp <= datetime.now(timezone.utc))),
             "A/B seal differs from holdout intake or custodian")
    return digest, timestamp


def _entries(formulas, ignores):
    return {**{key: ("formula", _pick(value, LABEL_FIELDS[1:])) for key, value in formulas.items()},
            **{key: ("ignore", _pick(value, IGNORE_FIELDS[1:])) for key, value in ignores.items()}}


def _decisions(a, b, c):
    page, formulas, ignores = c
    _require(_nonempty(page.get("page_reason")), "Adjudication requires a coverage reason for every page")
    available = {"A": _entries(*a[1:]), "B": _entries(*b[1:]), "final": _entries(formulas, ignores)}
    used = {side: set() for side in available}
    groups = Counter()
    for decision in _index(page.get("decisions"), "id").values():
        _require(_nonempty(decision.get("reason")), "Every adjudication group requires a reason")
        for side, entries in available.items():
            ids = decision.get(side)
            _require(isinstance(ids, list) and all(isinstance(key, str) for key in ids)
                     and len(set(ids)) == len(ids) and set(ids) <= entries.keys() and not (set(ids) & used[side]),
                     f"Adjudication {side} entries must exist and occur exactly once")
            used[side].update(ids)
        ai, bi, final = (decision[key] for key in ("A", "B", "final"))
        _require(ai or bi or final, "Adjudication group must account for at least one entry")
        if not ai and not bi:
            groups["found_by_C"] += 1
        elif not ai or not bi:
            groups["only_A" if ai else "only_B"] += 1
        elif len(ai) == len(bi) == 1 and available["A"][ai[0]] == available["B"][bi[0]]:
            groups["same_A_B"] += 1
        else:
            groups["different_A_B"] += 1
    _require(all(used[side] == entries.keys() for side, entries in available.items()),
             "Adjudication must account for every A, B and final entry")
    return groups


def _finish(seal, adjudication, source, guideline_hash, a, b, audit, *, before=None):
    _require(seal is not None and adjudication is not None, "Sealed A/B and completed C are required")
    seal_hash, sealed_at = _sealed(seal, a, b, source, guideline_hash)
    c = _packet(adjudication, "C", source, guideline_hash)
    _require(c["actor"] not in {a["actor"], b["actor"]} and sealed_at <= c["completed"] <= datetime.now(timezone.utc)
             and c["raw"].get("ab_seal_sha256") == seal_hash,
             "C must declare a distinct human identity and complete after the matching A/B seal")
    _require(before is None or c["completed"] <= before, "Adjudication must be completed before custodian review")
    groups = Counter()
    final = {key: {**_pick(doc, DOC_FIELDS), "pages": []} for key, doc in source.documents.items()}
    for key, page in c["pages"].items():
        groups.update(_decisions(a["pages"][key], b["pages"][key], page))
        metadata, formulas, ignores = page
        final[key[0]]["pages"].append({**_pick(metadata, FRAME_FIELDS),
            "formulas": [_pick(row, LABEL_FIELDS) for row in formulas.values()],
            "ignore_regions": [_pick(row, IGNORE_FIELDS) for row in ignores.values()]})
    status = "DECLARED_CUSTODY_COMPLETE_FOR_" + source.partition.upper()
    audit.update(status=status, adjudication_sha256=c["hash"],
                 ab_seal_sha256=seal_hash, adjudication_groups=dict(groups))
    result = {"schema_version": ANNOTATION_SCHEMA, "intended_partition": source.partition,
              "documents": list(final.values()), "custody": audit}
    return result, [(seal, seal_hash), (adjudication, c["hash"])]


def _audit(source, guideline_hash, issues, a=None, b=None):
    result = {"schema_version": "ocr-formula-human-audit-v1", "status": "NOT_EVALUATED",
              "acceptance_status": "NOT_EVALUATED", "independent_ground_truth_verified": False,
              "intended_partition": source.partition, "source_manifest_sha256": source.sha256,
              "guideline_sha256": guideline_hash, "source_pages": len(source.pages),
              "paired_declared_pages": 0, "issues": issues, **source.intake_pin}
    if a is not None and b is not None:
        _require(a["actor"] != b["actor"], "A and B must have distinct declared identities")
        result.update(annotation_sha256={"A": a["hash"], "B": b["hash"]}, paired_declared_pages=len(source.pages))
    return result


def _verify_unchanged(identities):
    _require(all(sha256_file(path) == expected for path, expected in identities), "Formula custody inputs changed while processing")


def _blank_packet(role, source, guideline_hash, **pins):
    result = {"schema_version": ANNOTATION_SCHEMA, "intended_partition": source.partition, "role": role, "status": "BLANK",
              "source_manifest_sha256": source.sha256, "guideline_sha256": guideline_hash, **source.intake_pin, **pins,
              "annotator": None, "actor_type": None, "completed_at": None, "source_images_checked": None,
              "no_model_or_native_text": None, "documents": []}
    if role != "C":
        result["no_peer_before_submission"] = None
    for doc in source.documents.values():
        pages = [{**_pick(page, FRAME_FIELDS), "formulas": None, "ignore_regions": []} for page in doc["pages"]]
        if role == "C":
            for page in pages:
                page.update(page_reason=None, decisions=[])
        result["documents"].append({**_pick(doc, DOC_FIELDS), "pages": pages})
    return result


def replay_holdout_references(path, protocol, pdf_root):
    """Reconstruct references from locked A/B/C bytes after the caller runs preflight."""
    data = protocol["data"]
    locked_at = _time(protocol.get("locked_at"))
    _require(protocol.get("status") == "LOCKED" and locked_at is not None and locked_at <= datetime.now(timezone.utc)
             and protocol["scope"]["formula_scope_decision"]["decision"] == "IN_SCOPE", "A locked in-scope protocol is required")
    manifest, digest = _read(path)
    _require(manifest.get("schema_version") == ADJUDICATION_SCHEMA and digest == data["adjudication_manifest_sha256"],
             "Adjudication manifest differs from the locked protocol")
    review = manifest.get("formula_custody")
    reviewed_at = _time(review.get("reviewed_at")) if isinstance(review, dict) else None
    _require(reviewed_at is not None and reviewed_at <= locked_at and review.get("status") == "REVIEWED"
             and review.get("reviewed_by") == data["holdout_custodian"] and _nonempty(review.get("review_evidence")),
             "Formula custody requires recorded custodian review before protocol lock")
    files = _pinned_files(path, review, ("source", "intake", "guideline"))
    guideline_hash = files["guideline"][1]
    _require(guideline_hash == data["annotation_guideline_sha256"], "Formula guideline differs from the locked protocol")
    source = _source(files["source"][0], pdf_root, guideline_hash, files["intake"][0])
    _require(source.sha256 == files["source"][1] and source.intake["sha256"] == files["intake"][1]
             and source.intake["custodian"] == data["holdout_custodian"]
             and all(data.get(key) == expected for key, expected in source.intake["protocol_pins"].items()),
             "Formula intake differs from the locked sample, sources, split, audit or custodian")
    files.update(_pinned_files(path, review, ("a", "b", "seal", "c")))
    a, b = (_packet(files[role.lower()][0], role, source, guideline_hash) for role in ("A", "B"))
    audit = _audit(source, guideline_hash, [], a, b)
    result, final = _finish(files["seal"][0], files["c"][0], source, guideline_hash, a, b, audit, before=reviewed_at)
    _require(a["hash"] == files["a"][1] and b["hash"] == files["b"][1] and final == [files["seal"], files["c"]],
             "Formula custody inputs differ from the locked adjudication manifest")
    _verify_unchanged([(path, digest), *files.values(), *source.identities])
    audit["review_manifest_sha256"] = digest
    return result


def process(args):
    _require(not any((parent / marker).is_file() for parent in args.output.resolve().parents
                     for marker in ("COMPLETED.json", "batch_input_manifest.json")),
             "Formula custody output must be outside canonical publications")
    guideline_hash = sha256_file(args.guideline)
    intake_path = getattr(args, "holdout_intake", None)
    source = _source(args.source, args.pdf_root, guideline_hash, intake_path)
    protected = (args.source.parent, args.guideline, args.pdf_root, args.a, args.b, args.seal, args.c,
                 *(path for path, _ in source.identities))
    identities = [*source.identities, (args.guideline, guideline_hash)]
    if args.action in ("template-a", "template-b"):
        result = _blank_packet(args.action[-1].upper(), source, guideline_hash)
        _verify_unchanged(identities)
        _write_new(args.output, result, protected)
        return result

    _require(args.a is not None and args.b is not None, "A and B packet paths are required")
    packets, issues = {}, []
    for role, path in (("A", args.a), ("B", args.b)):
        try:
            packets[role] = _packet(path, role, source, guideline_hash)
        except (OSError, ValueError, KeyError, TypeError) as error:
            issues.append(f"{role}: {error}")
    if not issues and packets["A"]["actor"] == packets["B"]["actor"]:
        issues.append("A and B must have distinct declared identities")
    if issues:
        _require(args.action == "audit", " | ".join(issues))
        audit = _audit(source, guideline_hash, issues)
        _verify_unchanged(identities)
        _write_new(args.output, audit, protected)
        return audit

    a, b = packets["A"], packets["B"]
    audit = _audit(source, guideline_hash, issues, a, b)
    identities.extend(((args.a, a["hash"]), (args.b, b["hash"])))
    if args.action == "seal":
        now = datetime.now(timezone.utc)
        _require(_nonempty(args.received_by) and now >= max(a["completed"], b["completed"]),
                 "Seal requires a custodian and completed A/B submissions")
        _require(source.intake is None or args.received_by == source.intake["custodian"], "Holdout seal requires the split custodian")
        result = {"schema_version": SEAL_SCHEMA, "source_manifest_sha256": source.sha256, "guideline_sha256": guideline_hash,
                  "annotation_sha256": audit["annotation_sha256"], "sealed_at": now.isoformat(),
                  "received_by": args.received_by, **source.intake_pin}
    elif args.action == "template":
        _require(args.seal is not None, "A/B seal is required")
        seal_hash, _ = _sealed(args.seal, a, b, source, guideline_hash)
        identities.append((args.seal, seal_hash))
        result = _blank_packet("C", source, guideline_hash, ab_seal_sha256=seal_hash)
    else:
        try:
            references, final_identities = _finish(args.seal, args.c, source, guideline_hash, a, b, audit)
            result = audit if args.action == "audit" else references
            identities.extend(final_identities)
        except (OSError, ValueError, KeyError, TypeError) as error:
            if args.action != "audit":
                raise
            issues.append(str(error))
            result = audit
    _verify_unchanged(identities)
    _write_new(args.output, result, protected)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("action", choices=("audit", "seal", "template", "export", "template-a", "template-b"))
    for name in ("source", "guideline", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    for name in ("a", "b", "seal", "c"):
        parser.add_argument(f"--{name}", type=Path)
    parser.add_argument("--pdf-root", type=Path, default=PROJECT_ROOT / "inputs")
    parser.add_argument("--holdout-intake", type=Path)
    parser.add_argument("--received-by")
    args = parser.parse_args(argv)
    try:
        result = process(args)
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.error(str(error))
    print(result.get("status", result["schema_version"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
