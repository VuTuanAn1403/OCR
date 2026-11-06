"""Audit human pilot annotations and freeze source-only submission custody.

These checks validate declared provenance, not the identity of real people or
the correctness of a transcription. Pilot output remains development-only.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import unicodedata

from ocr_artifacts.hashing import sha256_file
from ocr_runtime.paths import PROJECT_ROOT


SOURCE_SCHEMA = "keyword-pilot-regions-v1"
DECLARATIONS_SCHEMA = "human-pilot-declarations-v1"
ADJUDICATOR_SCHEMA = "human-pilot-adjudicator-declaration-v1"
SEAL_SCHEMA = "human-pilot-submission-seal-v1"
READY = "DECLARED_HUMAN_PACKET_COMPLETE_FOR_REVIEW"
FILES = {"A": "annotation_A.json", "B": "annotation_B.json", "C": "adjudication.json"}


class PacketNotReady(ValueError):
    def __init__(self, issues):
        super().__init__("Human pilot packet is not ready")
        self.issues = issues


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _read(path):
    def unique_fields(pairs):
        value = dict(pairs)
        _require(len(value) == len(pairs), f"Duplicate JSON keys: {path}")
        return value

    raw = Path(path).read_bytes()
    value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique_fields)
    _require(isinstance(value, dict), f"Expected a JSON object: {path}")
    return value, hashlib.sha256(raw).hexdigest()


def _nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def _identity(value):
    return unicodedata.normalize("NFC", value.strip()).casefold() if _nonempty(value) else None


def _time(value):
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.utcoffset() is not None else None
    except (TypeError, ValueError):
        return None


def _box(value):
    return (isinstance(value, list) and len(value) == 4
            and all(type(number) in (int, float) and math.isfinite(number) for number in value)
            and value[2] > value[0] and value[3] > value[1])


def _resolve(root, value):
    _require(_nonempty(value), "Source file path is required")
    path = (root / value).resolve()
    _require(path.is_relative_to(root.resolve()), "Source file escapes the declared source root")
    return path


def _source(path, source_root):
    manifest, digest = _read(path)
    _require(manifest.get("schema_version") == SOURCE_SCHEMA
             and manifest.get("role") == "development_candidate", "Expected a development pilot source manifest")
    _require(_nonempty(manifest.get("document_id")), "Document ID is required")
    pdf = _resolve(source_root, manifest.get("pdf_path"))
    _require(sha256_file(pdf) == manifest.get("pdf_sha256"), "Source PDF checksum mismatch")
    if manifest.get("source_manifest") is not None:
        _require(sha256_file(_resolve(source_root, manifest["source_manifest"])) ==
                 manifest.get("source_manifest_sha256"), "Image provenance manifest checksum mismatch")
    rows = manifest.get("units")
    _require(isinstance(rows, list) and rows, "Source requires at least one unit")
    units = {}
    for row in rows:
        _require(isinstance(row, dict), "Source unit must be an object")
        key = row.get("unit_id")
        _require(_nonempty(key) and key not in units, "Source unit IDs must be nonempty and unique")
        _require(type(row.get("physical_page")) is int and row["physical_page"] > 0,
                 "Physical page must be a positive integer")
        box, clip = row.get("bbox"), row.get("clip_bbox")
        _require(_box(box) and _box(clip) and clip[0] <= box[0] < box[2] <= clip[2]
                 and clip[1] <= box[1] < box[3] <= clip[3], "Source target must fit a positive finite clip bbox")
        _require(row.get("coordinate_space") == "pdf_points_top_left", "Unsupported source coordinate space")
        _require(row.get("pdf_sha256", manifest["pdf_sha256"]) == manifest["pdf_sha256"], "Unit PDF identity mismatch")
        _require(sha256_file(_resolve(source_root, row.get("image"))) == row.get("image_sha256"),
                 f"Source image checksum mismatch: {key}")
        units[key] = row
    return manifest, digest, units


def _packet(path, role, source, units):
    value, digest = _read(path)
    expected_schema = "keyword-pilot-adjudication-v1" if role == "C" else "keyword-pilot-transcription-v1"
    _require(value.get("schema_version") == expected_schema, f"Unexpected packet schema for {role}")
    _require(role == "C" or value.get("role") == "annotator_" + role, f"Unexpected annotator role: {role}")
    _require(value.get("pdf_sha256") == source["pdf_sha256"], f"Packet PDF checksum mismatch: {role}")
    rows = value.get("units")
    _require(isinstance(rows, list) and all(isinstance(row, dict) for row in rows), "Packet units must be objects")
    keyed = {row.get("unit_id"): row for row in rows if isinstance(row.get("unit_id"), str)}
    _require(len(keyed) == len(rows) and keyed.keys() == units.keys(), f"Packet must contain every source unit once: {role}")
    if role != "C":
        for key, row in keyed.items():
            original = units[key]
            _require(type(row.get("physical_page")) is int
                     and all(row.get(field) == original[field] for field in ("physical_page", "image", "image_sha256")),
                     f"Packet source location changed: {role}/{key}")
            x0, y0, x1, y1 = original["bbox"]
            left, top, right, bottom = original["clip_bbox"]
            fraction = [round(number, 4) for number in ((x0-left)/(right-left), (y0-top)/(bottom-top),
                                                       (x1-left)/(right-left), (y1-top)/(bottom-top))]
            _require(_box(row.get("target_xyxy_fraction_in_image"))
                     and row["target_xyxy_fraction_in_image"] == fraction, f"Packet target changed: {role}/{key}")
    return value, digest, keyed


def _declaration(path, schema, source_hash, guideline_hash):
    if path is None or not Path(path).is_file():
        return None, None
    value, digest = _read(path)
    _require(value.get("schema_version") == schema and value.get("source_manifest_sha256") == source_hash
             and value.get("guideline_sha256") == guideline_hash, "Declaration schema/source/guideline mismatch")
    return value, digest


def _actor(packet, digest, declaration, role, issues):
    previous_issues = len(issues)
    raw_id = packet.get("adjudicator_id" if role == "C" else "annotator_id")
    identity = _identity(raw_id)
    if identity is None:
        issues.append(f"{role}: human actor ID is required")
    if packet.get("actor_type") not in (None, "HUMAN") or packet.get("status") == "AI_DRAFT":
        issues.append(f"{role}: AI/nonhuman draft cannot establish independent human annotation")
    if not isinstance(declaration, dict):
        issues.append(f"{role}: source-only human declaration is missing")
        return identity, None, False
    _require(declaration.get("packet_sha256") == digest, f"Declaration packet checksum mismatch: {role}")
    if declaration.get("actor_type") != "HUMAN" or _identity(declaration.get("actor_id")) != identity or identity is None:
        issues.append(f"{role}: declaration must identify the same human actor")
    flags = ("source_images_checked", "no_model_or_workbook")
    if role != "C":
        flags += ("no_peer_before_submission",)
    if any(declaration.get(flag) is not True for flag in flags):
        issues.append(f"{role}: source-only independence confirmations are incomplete")
    completed = _time(declaration.get("completed_at"))
    confirmed = _time(declaration.get("confirmed_at"))
    if completed is None or confirmed is None or completed > confirmed:
        issues.append(f"{role}: expected completed/confirmed timestamps with timezone in chronological order")
    elif confirmed > datetime.now(timezone.utc):
        issues.append(f"{role}: human confirmation cannot be in the future")
    if packet.get("completed_at") is not None and _time(packet["completed_at"]) != completed:
        issues.append(f"{role}: packet and declaration completion timestamps differ")
    return identity, confirmed, len(issues) == previous_issues


def _transcriptions(rows, role, issues):
    complete = set()
    for key, row in rows.items():
        text = row.get("transcription")
        state = row.get("annotation_state")
        if isinstance(text, str) and text.strip() and state in (None, "annotated_nonempty"):
            if _nonempty(row.get("ambiguity_reason")):
                issues.append(f"{role}/{key}: uncertain text must remain unannotated")
            else:
                complete.add(key)
        elif text == "" and state == "annotated_empty" and _nonempty(row.get("empty_reason")) and not _nonempty(row.get("ambiguity_reason")):
            complete.add(key)
        else:
            issues.append(f"{role}/{key}: transcription is missing or empty was not explicitly confirmed")
    return complete


def _inspect(source_path, packet_directory, guideline_path, declarations_path, *, source_root,
             seal_path=None, adjudicator_declaration=None, include_adjudicator=True):
    source, source_hash, units = _source(source_path, source_root)
    guideline_hash = sha256_file(guideline_path)
    declarations, declarations_hash = _declaration(declarations_path, DECLARATIONS_SCHEMA, source_hash, guideline_hash)
    issues, packets, identities, confirmations, complete, human = [], {}, {}, {}, {}, {}
    c_declaration, c_declaration_hash = None, None
    actors = declarations.get("actors", {}) if declarations else {}
    _require(isinstance(actors, dict), "Declaration actors must be an object")
    roles = ("A", "B", "C") if include_adjudicator else ("A", "B")
    for role in roles:
        path = packet_directory / FILES[role]
        if not path.is_file():
            issues.append(f"{role}: packet file is missing")
            continue
        packet, digest, rows = _packet(path, role, source, units)
        packets[role] = dict(value=packet, sha256=digest, rows=rows, path=path)
        declaration = actors.get(role)
        if role == "C":
            c_declaration, c_declaration_hash = _declaration(adjudicator_declaration, ADJUDICATOR_SCHEMA, source_hash, guideline_hash)
            declaration = c_declaration
        identities[role], confirmations[role], human[role] = _actor(packet, digest, declaration, role, issues)
        complete[role] = _transcriptions(rows, role, issues)
    present_ids = [value for value in identities.values() if value is not None]
    if len(set(present_ids)) != len(present_ids):
        issues.append("A, B and adjudicator must have distinct human identities")
    seal, seal_hash = None, None
    if seal_path is not None and Path(seal_path).is_file():
        seal, seal_hash = _read(seal_path)
        _require(seal.get("schema_version") == SEAL_SCHEMA and seal.get("intended_partition") == "development"
                 and seal.get("source_manifest_sha256") == source_hash and seal.get("guideline_sha256") == guideline_hash
                 and (declarations_hash is None or seal.get("declarations_sha256") == declarations_hash), "Submission seal identity mismatch")
        _require(_nonempty(seal.get("received_by")), "Submission custodian is required")
        sealed_at = _time(seal.get("sealed_at"))
        _require(sealed_at is not None, "Submission seal needs a timezone-aware timestamp")
        annotations = seal.get("annotations")
        _require(isinstance(annotations, dict), "Submission seal annotations must be an object")
        for role in ("A", "B"):
            entry = annotations.get(role)
            _require(role in packets and isinstance(entry, dict) and entry.get("sha256") == packets[role]["sha256"],
                     f"Sealed annotation changed: {role}")
            if confirmations.get(role) is None or confirmations[role] > sealed_at:
                issues.append(f"{role}: declaration must precede the submission seal")
        if "C" in packets:
            if c_declaration is None or c_declaration.get("ab_seal_sha256") != seal_hash:
                issues.append("C: adjudicator must pin the previously sealed A/B inputs")
            c_completed = _time(c_declaration.get("completed_at")) if c_declaration else None
            if c_completed is None or c_completed < sealed_at:
                issues.append("C: adjudication must follow the A/B submission seal")
    elif include_adjudicator or seal_path is not None:
        issues.append("A/B submission seal is missing")
    disagreements, corrections = [], []
    if all(role in packets for role in ("A", "B", "C")):
        decision = packets["C"]["value"]
        for role in ("A", "B"):
            pinned = decision.get(f"annotation_{role}_sha256")
            if pinned is None:
                issues.append(f"C: original annotation {role} checksum is missing")
            else:
                _require(pinned == packets[role]["sha256"], f"Adjudication must pin {role}")
        for key in units:
            a, b, c = (packets[role]["rows"][key].get("transcription") for role in ("A", "B", "C"))
            if a != b:
                disagreements.append(key)
            if c != a or c != b:
                corrections.append(key)
            final = packets["C"]["rows"][key]
            if final.get("source_checked") is not True or not _nonempty(final.get("decision_reason")):
                issues.append(f"C/{key}: confirmation against the source image and decision reason are required")
    context = dict(source=source, source_sha256=source_hash, units=units, guideline_sha256=guideline_hash,
                declarations_sha256=declarations_hash, packets=packets, issues=issues,
                complete=complete, seal_sha256=seal_hash, disagreements=disagreements, corrections=corrections,
                human=human, identities=identities, adjudicator_declaration_sha256=c_declaration_hash)
    _unchanged(context, source_path, guideline_path, declarations_path, seal_path, adjudicator_declaration, source_root)
    return context


def _unchanged(context, source_path, guideline_path, declarations_path, seal_path, adjudicator_declaration, source_root):
    for path, expected in ((source_path, context["source_sha256"]), (guideline_path, context["guideline_sha256"]),
                           (declarations_path, context["declarations_sha256"]), (seal_path, context["seal_sha256"]),
                           (adjudicator_declaration, context["adjudicator_declaration_sha256"])):
        if expected is not None:
            _require(sha256_file(path) == expected, "Annotation input changed during inspection")
    for packet in context["packets"].values():
        _require(sha256_file(packet["path"]) == packet["sha256"], "Received annotation changed during inspection")
    source = context["source"]
    _require(sha256_file(_resolve(source_root, source["pdf_path"])) == source["pdf_sha256"], "PDF changed during inspection")
    if source.get("source_manifest") is not None:
        _require(sha256_file(_resolve(source_root, source["source_manifest"])) == source["source_manifest_sha256"],
                 "Image provenance manifest changed during inspection")
    for unit in context["units"].values():
        _require(sha256_file(_resolve(source_root, unit["image"])) == unit["image_sha256"], "Source image changed during inspection")


def audit(source_path, packet_directory, guideline_path, declarations_path=None, *, source_root=PROJECT_ROOT,
          seal_path=None, adjudicator_declaration=None):
    context = _inspect(Path(source_path), Path(packet_directory), Path(guideline_path), declarations_path,
                       source_root=Path(source_root), seal_path=seal_path, adjudicator_declaration=adjudicator_declaration)
    return _report(context)


def _report(context):
    eligible_pair = (all(context["human"].get(role) is True for role in ("A", "B"))
                     and context["identities"]["A"] != context["identities"]["B"])
    paired = context["complete"].get("A", set()) & context["complete"].get("B", set()) if eligible_pair else set()
    return {"schema_version": "human-pilot-audit-v1", "status": READY if not context["issues"] else "NOT_EVALUATED",
            "quality_acceptance_status": "NOT_EVALUATED", "eligible_for_quality_acceptance": False,
            "intended_partition": "development", "document_id": context["source"]["document_id"],
            "source_manifest_sha256": context["source_sha256"], "guideline_sha256": context["guideline_sha256"],
            "source_units": len(context["units"]), "paired_human_transcriptions": len(paired),
            "observed_disagreements": context["disagreements"], "adjudicator_corrections": context["corrections"],
            "packet_sha256": {role: packet["sha256"] for role, packet in context["packets"].items()},
            "seal_sha256": context["seal_sha256"], "issues": context["issues"],
            "limits": "Checks declared identities, custody and provenance; requires independent human verification of people, procedure and content"}


def _write_new(path, value, protected):
    path = Path(path).resolve()
    _require(not any(path == Path(item).resolve() or path.is_relative_to(Path(item).resolve())
                     for item in protected if item is not None), "Output must be outside received packets and input files")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def declaration_template(source_path, packet_directory, guideline_path, output, *, role="AB", seal_path=None,
                         source_root=PROJECT_ROOT):
    source, source_hash, units = _source(Path(source_path), Path(source_root))
    guideline_hash = sha256_file(guideline_path)
    _require(role in ("AB", "C"), "Declaration role must be AB or C")
    records = {}
    for key in (("A", "B") if role == "AB" else ("C",)):
        packet, digest, _ = _packet(Path(packet_directory) / FILES[key], key, source, units)
        record = {"packet_sha256": digest, "actor_id": packet.get("adjudicator_id" if key == "C" else "annotator_id"),
                  "actor_type": None, "completed_at": packet.get("completed_at"), "confirmed_at": None,
                  "source_images_checked": None, "no_model_or_workbook": None}
        if key != "C":
            record["no_peer_before_submission"] = None
        records[key] = record
    value = {"schema_version": DECLARATIONS_SCHEMA if role == "AB" else ADJUDICATOR_SCHEMA,
             "source_manifest_sha256": source_hash, "guideline_sha256": guideline_hash}
    if role == "AB":
        value["actors"] = records
    else:
        _require(seal_path is not None, "C declaration requires the A/B seal")
        seal, seal_hash = _read(seal_path)
        _require(seal.get("schema_version") == SEAL_SCHEMA and seal.get("source_manifest_sha256") == source_hash
                 and seal.get("guideline_sha256") == guideline_hash, "Submission seal identity mismatch")
        value.update(records["C"], ab_seal_sha256=seal_hash)
    _write_new(output, value, (packet_directory, source_path, guideline_path, seal_path))
    return value


def seal_submissions(source_path, packet_directory, guideline_path, declarations_path, output, *, received_by,
                     source_root=PROJECT_ROOT):
    _require(_nonempty(received_by), "Submission custodian is required")
    context = _inspect(Path(source_path), Path(packet_directory), Path(guideline_path), declarations_path,
                       source_root=Path(source_root), include_adjudicator=False)
    if context["issues"]:
        raise PacketNotReady(context["issues"])
    now = datetime.now(timezone.utc)
    seal = {"schema_version": SEAL_SCHEMA, "intended_partition": "development", "received_by": received_by,
            "sealed_at": now.isoformat(), "source_manifest_sha256": context["source_sha256"],
            "guideline_sha256": context["guideline_sha256"], "declarations_sha256": context["declarations_sha256"],
            "annotations": {role: {"path": str(packet["path"].resolve()), "sha256": packet["sha256"]}
                            for role, packet in context["packets"].items()},
            "quality_acceptance_status": "NOT_EVALUATED"}
    _write_new(output, seal, (packet_directory, source_path, guideline_path, declarations_path))
    return seal


def adjudication_template(source_path, packet_directory, guideline_path, declarations_path, output, *, seal_path,
                          source_root=PROJECT_ROOT):
    _require(seal_path is not None, "Adjudication template requires a submission seal path")
    context = _inspect(Path(source_path), Path(packet_directory), Path(guideline_path), declarations_path,
                       source_root=Path(source_root), seal_path=seal_path, include_adjudicator=False)
    if context["issues"]:
        raise PacketNotReady(context["issues"])
    value = {"schema_version": "keyword-pilot-adjudication-v1", "status": "BLANK",
             "adjudicator_id": None, "actor_type": None, "completed_at": None,
             "quality_acceptance_status": "NOT_EVALUATED", "pdf_sha256": context["source"]["pdf_sha256"],
             "annotation_A_sha256": context["packets"]["A"]["sha256"],
             "annotation_B_sha256": context["packets"]["B"]["sha256"],
             "units": [{"unit_id": key, "transcription": None, "ambiguity_reason": None,
                        "source_checked": None, "decision_reason": None} for key in context["units"]]}
    _write_new(output, value, (source_path, guideline_path, declarations_path, seal_path,
                              Path(packet_directory) / FILES["A"], Path(packet_directory) / FILES["B"]))
    return value


def export_keyword_gt(source_path, packet_directory, guideline_path, declarations_path, dictionary_path, output, *,
                      seal_path, adjudicator_declaration, source_root=PROJECT_ROOT):
    from ocr_keywords.contract import validate_snapshot
    from ocr_keywords import counter as counter_module
    KeywordCounter = counter_module.KeywordCounter
    counter_path = Path(counter_module.__file__)
    counter_hash = sha256_file(counter_path)
    context = _inspect(Path(source_path), Path(packet_directory), Path(guideline_path), declarations_path,
                       source_root=Path(source_root), seal_path=seal_path, adjudicator_declaration=adjudicator_declaration)
    report = _report(context)
    if report["status"] != READY:
        raise PacketNotReady(report["issues"])
    source, source_hash, originals = context["source"], context["source_sha256"], context["units"]
    dictionary, dictionary_hash = _read(dictionary_path)
    validate_snapshot(dictionary)
    ids = {row["keyword"]: row["id"] for row in dictionary["canonical_keywords"]}
    _require(KeywordCounter.unique_keywords(list(ids)) == list(ids), "Dictionary keywords must be canonical and unique")
    final = context["packets"]["C"]["value"]
    units = []
    for row in final["units"]:
        original = originals[row["unit_id"]]
        text = row["transcription"]
        occurrences = [{"id": f"{row['unit_id']}:occ-{number}", "keyword_id": ids[word], "start": start, "end": end}
                       for number, (word, start, end) in enumerate(KeywordCounter.iter_occurrences(text, list(ids)), 1)]
        units.append({**{key: original.get(key) for key in ("unit_id", "physical_page", "coordinate_space", "bbox", "table_cell_id")},
                      "transcription": text, "keyword_occurrences": occurrences,
                      "source_image_sha256": original["image_sha256"]})
    value = {"schema_version": "keyword-source-gt-v1", "intended_partition": "development",
             "annotation_origin": "DECLARED_TWO_HUMAN_SOURCE_ONLY_WITH_ADJUDICATION",
             "quality_acceptance_status": "NOT_EVALUATED", "eligible_for_quality_acceptance": False,
             "identity": {"document_id": source["document_id"], "pdf_sha256": source["pdf_sha256"],
                          "dictionary_sha256": dictionary["snapshot_sha256"]}, "units": units,
             "provenance": {"source_manifest_sha256": source_hash, "guideline_sha256": report["guideline_sha256"],
                            "packet_sha256": report["packet_sha256"], "seal_sha256": report["seal_sha256"],
                            "declarations_sha256": context["declarations_sha256"],
                            "adjudicator_declaration_sha256": context["adjudicator_declaration_sha256"],
                            "dictionary_file_sha256": dictionary_hash,
                            "exporter_file_sha256": sha256_file(Path(__file__)),
                            "keyword_counter_file_sha256": counter_hash}}
    _unchanged(context, source_path, guideline_path, declarations_path, seal_path, adjudicator_declaration, Path(source_root))
    _require(sha256_file(dictionary_path) == dictionary_hash, "Dictionary changed during export")
    _require(sha256_file(counter_path) == counter_hash, "Keyword counter changed during export")
    _write_new(output, value, (packet_directory, source_path, guideline_path, declarations_path, dictionary_path,
                              seal_path, adjudicator_declaration))
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("audit", "declaration-template", "seal", "adjudication-template", "export-keywords"))
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--packets", type=Path, required=True)
    parser.add_argument("--guideline", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--declarations", type=Path)
    parser.add_argument("--seal", type=Path)
    parser.add_argument("--adjudicator-declaration", type=Path)
    parser.add_argument("--dictionary", type=Path)
    parser.add_argument("--received-by")
    parser.add_argument("--declaration-role", choices=("AB", "C"), default="AB")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "audit":
            result = audit(args.source, args.packets, args.guideline, args.declarations, source_root=args.source_root,
                           seal_path=args.seal, adjudicator_declaration=args.adjudicator_declaration)
            _write_new(args.output, result, (args.packets, args.source, args.guideline, args.declarations,
                                            args.seal, args.adjudicator_declaration))
            code = 0 if result["status"] == READY else 1
        elif args.command == "declaration-template":
            result = declaration_template(args.source, args.packets, args.guideline, args.output,
                                           role=args.declaration_role, seal_path=args.seal, source_root=args.source_root)
            code = 0
        elif args.command == "seal":
            _require(args.declarations is not None, "--declarations is required to seal submissions")
            result = seal_submissions(args.source, args.packets, args.guideline, args.declarations, args.output,
                                      received_by=args.received_by, source_root=args.source_root)
            code = 0
        elif args.command == "adjudication-template":
            _require(args.declarations is not None and args.seal is not None, "Adjudication template requires declarations and seal")
            result = adjudication_template(args.source, args.packets, args.guideline, args.declarations, args.output,
                                            seal_path=args.seal, source_root=args.source_root)
            code = 0
        else:
            _require(all(value is not None for value in (args.declarations, args.dictionary, args.seal,
                                                        args.adjudicator_declaration)),
                     "Keyword export requires declarations, dictionary, seal and adjudicator declaration")
            result = export_keyword_gt(args.source, args.packets, args.guideline, args.declarations, args.dictionary,
                                       args.output, seal_path=args.seal, adjudicator_declaration=args.adjudicator_declaration,
                                       source_root=args.source_root)
            code = 0
        print(json.dumps({"status": result.get("status", "WRITTEN_FOR_REVIEW"), "output": str(args.output),
                          "quality_acceptance_status": "NOT_EVALUATED", "issues": result.get("issues", [])}))
        return code
    except PacketNotReady as error:
        print(json.dumps({"status": "NOT_EVALUATED", "issues": error.issues}))
        return 1
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"status": "INVALID_INPUT", "error": str(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
