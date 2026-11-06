"""Source-only A/B intake and adjudication for table boundaries in development."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from ocr_artifacts.hashing import sha256_file

from .human_annotations import _box, _identity, _nonempty, _read, _require, _resolve, _time, _write_new

SOURCE_SCHEMA = "ocr-table-boundary-source-v2"
PACKET_SCHEMA = "ocr-table-boundary-annotation-v2"
SEAL_SCHEMA = "ocr-table-boundary-ab-seal-v2"
LABEL_SCHEMA = "ocr-table-boundary-development-labels-v2"
RELATIONSHIPS = {"SAME_TABLE", "DIFFERENT_TABLES", "NOT_A_TABLE", "UNCERTAIN"}
BOUNDARIES = {"BETWEEN_ROWS", "SPLIT_ROW", "SPANNING_CELL"}
LABEL_FIELDS = ("relationship", "boundary", "column_count", "repeated_header_rows", "cell_links")
SIDES = ("previous", "next")


def _indexed(records, key):
    _require(isinstance(records, list), f"Expected records indexed by {key}")
    result = {}
    for row in records:
        _require(isinstance(row, dict) and _nonempty(row.get(key)) and row[key] not in result,
                 f"Missing or duplicate {key}")
        result[row[key]] = row
    return result


def _integer(value, low):
    return type(value) is int and value >= low


def _source(path, pdf_root, guideline):
    from PIL import Image

    manifest, digest = _read(path)
    guideline_digest = sha256_file(guideline)
    _require(manifest.get("schema_version") == SOURCE_SCHEMA and manifest.get("partition") == "development"
             and manifest.get("guideline_sha256") == guideline_digest, "Expected a development source manifest and its exact guideline")
    units = _indexed(manifest["pairs"], "pair_id")
    _require(bool(units), "Source manifest has no table boundaries")
    identities = {path: digest, guideline: guideline_digest}
    for unit in units.values():
        _require(not Path(unit["pdf_path"]).anchor, "Source PDF path must be relative")
        pdf = _resolve(pdf_root, unit["pdf_path"])
        if pdf not in identities:
            identities[pdf] = sha256_file(pdf)
        _require(identities[pdf] == unit["pdf_sha256"], "Source PDF SHA-256 differs")
        pages = unit["pages"]
        _require(isinstance(pages, list) and len(pages) == 2 and all(_integer(page, 1) for page in pages)
                 and pages[1] == pages[0] + 1, "Table boundary requires consecutive physical pages")
        images = _indexed(unit["images"], "image_id")
        _require({image["side"] for image in images.values()} == set(SIDES), "Both boundary sides require source images")
        for image in images.values():
            _require(not Path(image["path"]).anchor, "Source image path must be relative")
            target = _resolve(path.parent, image["path"])
            _require(target not in identities and sha256_file(target) == image["sha256"], "Source image is reused or its SHA-256 differs")
            identities[target] = image["sha256"]
            _require(image["physical_page"] == pages[SIDES.index(image["side"])] and _box(image["clip_xyxy_pt"])
                     and min(image["clip_xyxy_pt"]) >= 0, "Source image page or PDF crop is invalid")
            with Image.open(target) as bitmap:
                size = image["size_px"]
                _require(bitmap.format == "PNG" and list(bitmap.size) == size and all(_integer(v, 1) for v in size),
                         "Source PNG format or dimensions differ")
                bitmap.verify()
    return units, digest, guideline_digest, identities


def _blank(units, source_digest, guideline_digest, role, **pins):
    return {"schema_version": PACKET_SCHEMA, "status": "BLANK", "role": role,
            "source_manifest_sha256": source_digest, "guideline_sha256": guideline_digest, **pins,
            "actor_type": None, "annotator_id": None, "submitted_at": None,
            "source_images_checked": None, "no_predictions": None, "no_peer_before_submission": None,
            "units": [{"pair_id": pair_id, **dict.fromkeys(LABEL_FIELDS), "source_reason": None} for pair_id in units]}


def _validate_label(row, source):
    relationship, boundary, columns, headers, links = (row[key] for key in LABEL_FIELDS)
    _require(relationship in RELATIONSHIPS and _nonempty(row.get("source_reason")), "Table label requires a relationship and source reason")
    if relationship != "SAME_TABLE":
        _require(all(value is None for value in (boundary, columns, headers, links)), "Nonpositive relationship cannot contain stitch labels")
        return
    if boundary == "UNCERTAIN":
        _require(all(value is None for value in (columns, headers, links)), "Uncertain boundary cannot contain stitch labels")
        return
    _require(boundary in BOUNDARIES and _integer(columns, 1) and columns <= 1024
             and _integer(headers, 0) and isinstance(links, list),
             "Same-table label requires a boundary, column count, repeated header count and cell link list")
    _require(not (boundary == "BETWEEN_ROWS" and links or boundary == "SPANNING_CELL" and not links),
             "Cell links disagree with the boundary kind")
    images = _indexed(source["images"], "image_id")
    spans, boxes = set(), {}
    for link in links:
        _require(isinstance(link, dict) and set(link) == {"column", "column_span", *SIDES}, "Invalid linked cell fields")
        col, width = link["column"], link["column_span"]
        _require(_integer(col, 0) and _integer(width, 1) and col + width <= columns, "Linked cell exceeds the logical columns")
        interval = set(range(col, col + width))
        _require(not interval & spans, "Boundary cell links overlap in logical columns")
        spans.update(interval)
        for side in SIDES:
            part = link[side]
            _require(isinstance(part, dict) and set(part) == {"image_id", "bbox_xyxy_px", "state", "text_raw"},
                     "Invalid source cell fields")
            image = images.get(part["image_id"])
            box, raw = part["bbox_xyxy_px"], part["text_raw"]
            _require(image is not None and image["side"] == side and _box(box) and min(box) >= 0
                     and box[2] <= image["size_px"][0] and box[3] <= image["size_px"][1],
                     "Linked cell must have an in-image bbox on the correct side")
            prior = boxes.setdefault(part["image_id"], [])
            _require(not any(max(box[0], old[0]) < min(box[2], old[2]) and max(box[1], old[1]) < min(box[3], old[3])
                             for old in prior), "Linked cells overlap within a source image")
            prior.append(box)
            _require((part["state"] == "OBSERVED_TEXT" and _nonempty(raw))
                     or (part["state"] == "OBSERVED_EMPTY" and raw == ""), "Linked cell requires exact observed text or an explicit empty cell")


def _packet(path, role, units, source_digest, guideline_digest, **pins):
    packet, digest = _read(path)
    expected = _blank(units, source_digest, guideline_digest, role, **pins)
    fixed = ("schema_version", "role", "source_manifest_sha256", "guideline_sha256", *pins)
    _require(packet.keys() == expected.keys() and all(packet[key] == expected[key] for key in fixed),
             f"Role {role} packet does not match its pinned source, guideline or seal")
    if packet["status"] == "BLANK":
        _require(packet == expected, f"Role {role} BLANK packet contains unexpected values")
        return packet, digest, {}
    completed = _time(packet["submitted_at"])
    _require(packet["status"] == "SUBMITTED" and packet["actor_type"] == "HUMAN" and _identity(packet["annotator_id"])
             and completed is not None and completed <= datetime.now(timezone.utc)
             and packet["source_images_checked"] is True and packet["no_predictions"] is True
             and packet["no_peer_before_submission"] is (None if role == "C" else True),
             f"Role {role} requires a submitted human declaration")
    rows = _indexed(packet["units"], "pair_id")
    _require(rows.keys() == units.keys(), f"Role {role} must label every planned boundary")
    for key, row in rows.items():
        _require(set(row) == {"pair_id", "source_reason", *LABEL_FIELDS}, f"Unexpected fields in boundary {key}")
        _validate_label(row, units[key])
    return packet, digest, rows


def _ab_receipt(a, b, source_digest, guideline_digest):
    return {"schema_version": SEAL_SCHEMA, "source_manifest_sha256": source_digest, "guideline_sha256": guideline_digest,
            "submissions": {role: {"sha256": submission[1], "annotator_id": submission[0]["annotator_id"],
                                    "submitted_at": submission[0]["submitted_at"]}
                            for role, submission in (("A", a), ("B", b))}}


def execute(args):
    units, source_digest, guideline_digest, identities = _source(args.source, args.pdf_root, args.guideline)
    a = _packet(args.annotation_a, "A", units, source_digest, guideline_digest)
    b = _packet(args.annotation_b, "B", units, source_digest, guideline_digest)
    identities.update({args.annotation_a: a[1], args.annotation_b: b[1]})
    complete = bool(a[2] and b[2])
    if complete:
        _require(_identity(a[0]["annotator_id"]) != _identity(b[0]["annotator_id"]), "A and B must be distinct people")
    if args.command == "audit":
        result = {"schema_version": "ocr-table-boundary-intake-audit-v2", "partition": "development",
                  "status": "READY_TO_SEAL" if complete else "WAITING_FOR_AB", "source_manifest_sha256": source_digest,
                  "source_units": len(units), "paired_human_labels": len(units) if complete else 0,
                  "role_status": {"A": a[0]["status"], "B": b[0]["status"]}, "quality_acceptance_status": "NOT_EVALUATED"}
    else:
        _require(complete, "Both independent human submissions are required before sealing or adjudication")
        receipt = _ab_receipt(a, b, source_digest, guideline_digest)
        if args.command == "seal":
            _require(_identity(args.received_by), "A receiving coordinator is required")
            result = {**receipt, "received_by": args.received_by, "sealed_at": datetime.now(timezone.utc).isoformat()}
        else:
            seal, seal_digest = _read(args.seal)
            identities[args.seal] = seal_digest
            sealed_at = _time(seal.get("sealed_at"))
            _require(seal.keys() == {*receipt, "received_by", "sealed_at"}
                     and all(seal[key] == value for key, value in receipt.items()) and _identity(seal["received_by"])
                     and sealed_at is not None and max(_time(a[0]["submitted_at"]), _time(b[0]["submitted_at"])) <= sealed_at
                     <= datetime.now(timezone.utc), "A/B seal does not match the exact submissions or chronology")
            if args.command == "adjudication-template":
                result = _blank(units, source_digest, guideline_digest, "C", seal_sha256=seal_digest)
            else:
                c = _packet(args.adjudication, "C", units, source_digest, guideline_digest, seal_sha256=seal_digest)
                identities[args.adjudication] = c[1]
                _require(bool(c[2]) and _identity(c[0]["annotator_id"]) not in
                         {_identity(a[0]["annotator_id"]), _identity(b[0]["annotator_id"])}
                         and _time(c[0]["submitted_at"]) >= sealed_at, "C must submit independently after the A/B seal")
                records = [{"pair_id": key, "pdf_sha256": units[key]["pdf_sha256"], "pages": units[key]["pages"],
                            "ab_disagreement": any(a[2][key][field] != b[2][key][field] for field in LABEL_FIELDS),
                            "decision": c[2][key]} for key in units]
                result = {"schema_version": LABEL_SCHEMA, "partition": "development", "status": "DECLARED_HUMAN_ADJUDICATED",
                          "quality_acceptance_status": "NOT_EVALUATED", "eligible_for_quality_acceptance": False,
                          "source_manifest_sha256": source_digest, "guideline_sha256": guideline_digest,
                          "seal_sha256": seal_digest, "submission_sha256": {"A": a[1], "B": b[1], "C": c[1]},
                          "adjudicator_id": c[0]["annotator_id"], "records": records}
    _require(all(sha256_file(path) == digest for path, digest in identities.items()), "Input bytes changed during table annotation intake")
    _write_new(args.output, result, [args.source.parent, args.pdf_root, *identities])
    return 1 if args.command == "audit" and not complete else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("audit", "seal", "adjudication-template", "export"):
        command = commands.add_parser(name, allow_abbrev=False)
        for field in ("source", "pdf-root", "guideline", "annotation-a", "annotation-b", "output"):
            command.add_argument(f"--{field}", type=Path, required=True)
        if name == "seal":
            command.add_argument("--received-by", required=True)
        if name in ("adjudication-template", "export"):
            command.add_argument("--seal", type=Path, required=True)
        if name == "export":
            command.add_argument("--adjudication", type=Path, required=True)
    try:
        return execute(parser.parse_args(argv))
    except (OSError, TypeError, ValueError, KeyError, OverflowError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
