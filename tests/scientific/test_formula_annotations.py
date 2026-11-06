"""Formula custody validates submission order, coverage and exact source bytes."""
from copy import deepcopy
import csv
from datetime import datetime, timezone
import hashlib
import json
from types import SimpleNamespace

import pytest

from benchmark.ground_truth_tools import formula_annotations as custody
from benchmark.scientific_evaluation.formula_alignment import _align_page
from benchmark.scientific_evaluation.formula_policy import SAMPLE_SCHEMA
from src.ocr.collect.catalog import ACCEPTANCE_SPLITS, FIELDS, file_sha256, lock_company_splits


def _write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _label(key, value):
    return {"id": key, "bbox": [1, 2, 20, 10], "placement": "inline", "format": "TEXT",
            "content_raw": value, "equation_label": None}


@pytest.fixture
def packet(tmp_path):
    source_dir, inputs = tmp_path / "source", tmp_path / "inputs"
    source_dir.mkdir()
    inputs.mkdir()
    pdf = inputs / "test.pdf"
    pdf.write_bytes(b"fixture PDF identity")
    image = source_dir / "p1.png"
    image.write_bytes(b"fixture image identity")
    source, guide = source_dir / "manifest.json", source_dir / "guide.md"
    guide.write_bytes(b"fixture instructions")
    guide_hash = hashlib.sha256(guide.read_bytes()).hexdigest()
    frame = {"page": 1, "coordinate_space": "pdf_points_top_left", "transforms": [], "width": 100, "height": 80}
    doc = {"document_id": "test", "pdf_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(), "total_pages": 1}
    source_hash = _write(source, {"schema_version": custody.SOURCE_SCHEMA, "partition": "development",
                                 "documents": [{**doc, "pages": [{**frame, "image": image.name,
                                      "image_sha256": hashlib.sha256(image.read_bytes()).hexdigest()}]}]})
    a, b = tmp_path / "A.json", tmp_path / "B.json"
    submissions = {}
    for role, path, label in (("A", a, _label("a", "x=1")), ("B", b, _label("b", "x=2"))):
        submissions[role] = {"schema_version": custody.ANNOTATION_SCHEMA, "intended_partition": "development",
                             "role": role, "status": "SUBMITTED", "source_manifest_sha256": source_hash,
                             "guideline_sha256": guide_hash, "annotator": f"fixture-{role}", "actor_type": "HUMAN",
                             "completed_at": "2024-11-04T12:00:00+07:00", "source_images_checked": True,
                             "no_model_or_native_text": True, "no_peer_before_submission": True,
                             "documents": [{**doc, "pages": [{**frame, "formulas": [label], "ignore_regions": []}]}]}
        _write(path, submissions[role])
    args = SimpleNamespace(action="audit", source=source, pdf_root=inputs, guideline=guide, a=a, b=b,
                           output=tmp_path / "audit.json", seal=None, c=None, received_by="fixture custodian")
    return args, submissions


def _sealed_c(args):
    folder = args.output.parent
    args.action, args.output = "seal", folder / "seal.json"
    custody.process(args)
    args.seal = args.output
    args.action, args.output = "template", folder / "blank-C.json"
    c = custody.process(args)
    assert c["status"] == "BLANK" and c["documents"][0]["pages"][0]["formulas"] is None
    c.update(status="SUBMITTED", annotator="fixture-C", actor_type="HUMAN", completed_at=datetime.now(timezone.utc).isoformat(),
             source_images_checked=True, no_model_or_native_text=True)
    page = c["documents"][0]["pages"][0]
    page.update(formulas=[_label("final", "x=1")], page_reason="Reviewed whole fixture page",
                decisions=[{"id": "d", "A": ["a"], "B": ["b"], "final": ["final"], "reason": "Fixture resolves content"}])
    args.c = folder / "C.json"
    _write(args.c, c)
    args.action, args.output = "export", folder / "references.json"
    return c


def test_sealed_workflow_preserves_all_disagreements_and_feeds_alignment(packet):
    args, _ = packet
    _sealed_c(args)
    result = custody.process(args)
    assert result["custody"]["adjudication_groups"] == {"different_A_B": 1}
    assert result["custody"]["acceptance_status"] == "NOT_EVALUATED"
    assert result["intended_partition"] == "development" and not result["custody"]["independent_ground_truth_verified"]
    page = result["documents"][0]["pages"][0]
    aligned, pairs = _align_page("test", {**page, "items": []}, page, .5)
    assert aligned["counts"] == {"tp": 0, "fp": 0, "fn": 1}
    assert pairs[0]["reference"] == "x=1" and pairs[0]["prediction"] is None


def test_blank_or_duplicate_actor_cannot_seal(packet):
    args, submissions = packet
    blank = deepcopy(submissions["B"])
    blank["status"] = "BLANK"
    _write(args.b, blank)
    audit = custody.process(args)
    assert audit["status"] == "NOT_EVALUATED" and audit["paired_declared_pages"] == 0
    args.action, args.output = "seal", args.output.parent / "seal.json"
    with pytest.raises(ValueError, match="submitted formula packet"):
        custody.process(args)
    _write(args.b, {**submissions["B"], "annotator": " FIXTURE-a "})
    with pytest.raises(ValueError, match="distinct declared identities"):
        custody.process(args)
    assert not args.output.exists()


def test_export_rejects_post_seal_edits_and_unresolved_disagreement(packet):
    args, submissions = packet
    c = _sealed_c(args)
    c["documents"][0]["pages"][0]["decisions"][0]["B"] = []
    _write(args.c, c)
    with pytest.raises(ValueError, match="account for every"):
        custody.process(args)
    assert not args.output.exists()
    _write(args.b, {**submissions["B"], "notes": "Edited after seal"})
    with pytest.raises(ValueError, match="A/B seal differs"):
        custody.process(args)


def test_reference_export_rejects_wrong_actor_or_unread_page(packet):
    args, _ = packet
    c = _sealed_c(args)
    _write(args.c, {**c, "annotator": "fixture-A"})
    with pytest.raises(ValueError, match="distinct human identity"):
        custody.process(args)
    c["documents"][0]["pages"][0]["formulas"] = None
    _write(args.c, c)
    args.action, args.output = "audit", args.output.parent / "final-audit.json"
    report = custody.process(args)
    assert report["status"] == "NOT_EVALUATED" and "unfinished page" in report["issues"][0]


def test_source_image_checksum_and_out_of_scope_page_are_rejected(packet):
    args, submissions = packet
    submissions["A"]["documents"][0]["pages"][0]["page"] = 2
    _write(args.a, submissions["A"])
    result = custody.process(args)
    assert "outside selected source" in result["issues"][0]
    (args.source.parent / "p1.png").write_bytes(b"different image")
    args.output = args.output.parent / "tamper-audit.json"
    with pytest.raises(ValueError, match="image hash differs"):
        custody.process(args)


@pytest.fixture
def holdout_packet(packet):
    args, submissions = packet
    root = args.output.parent
    source = json.loads(args.source.read_bytes())
    source.update(schema_version=custody.HOLDOUT_SOURCE_SCHEMA, partition="holdout")
    pdf_hash = source["documents"][0]["pdf_sha256"]
    pins = {"sample": root / "sample.json", "sources": root / "sources.csv", "splits": root / "splits.json",
            "source_use_audit": root / "source-use.json"}
    ids = ("train", "development", "calibration", "test")
    with pins["sources"].open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, FIELDS)
        writer.writeheader()
        for index, name in enumerate(ids, start=1):
            writer.writerow(dict(document_id=name, relative_path=f"{name}.pdf", company_id=name,
                                 sha256=pdf_hash if name == "test" else f"{index:064x}", pages=2, status="OK"))
    source["documents"][0]["total_pages"] = 2
    source_hash = _write(args.source, source)
    _write(pins["source_use_audit"], {"schema_version": "split-leakage-audit-v2", "status": "REVIEWED",
           "sources_sha256": file_sha256(pins["sources"]), "reviewed_by": "fixture reviewer",
           "reviewed_at": "2024-10-01T00:00:00Z", "holdout_custodian": args.received_by,
           "template_groups": {name: name for name in ids}, "near_duplicate_groups": {name: name for name in ids},
           "source_dispositions": {name: {"status": "development_only" if name == "development" else "eligible_for_assignment",
                                          "exposure_evidence": "fixture-exposure", "rights_evidence": "fixture-rights"} for name in ids},
           "partition_access": {"calibration": "fixture-calibration-access", "holdout": "fixture-holdout-access"}})
    lock_company_splits(pins["sources"], dict(zip(ACCEPTANCE_SPLITS, ([name] for name in ids), strict=True)),
                        pins["splits"], audit=pins["source_use_audit"])
    _write(pins["sample"], {"schema_version": SAMPLE_SCHEMA,
                           "documents": [{"document_id": "test", "pdf_sha256": pdf_hash, "pages": [1]}]})
    args.holdout_intake = root / "intake.json"
    intake = {"schema_version": custody.INTAKE_SCHEMA, "status": "REVIEWED", "reviewed_by": args.received_by,
              "reviewed_at": "2024-10-02T00:00:00Z", "source_manifest_sha256": source_hash,
              "guideline_sha256": file_sha256(args.guideline)}
    for key, path in pins.items():
        intake.update({f"{key}_path": path.name, f"{key}_sha256": file_sha256(path)})
    intake_hash = _write(args.holdout_intake, intake)
    for role, path in (("A", args.a), ("B", args.b)):
        submissions[role].update(intended_partition="holdout", source_manifest_sha256=source_hash,
                                 holdout_intake_sha256=intake_hash)
        submissions[role]["documents"][0]["total_pages"] = 2
        _write(path, submissions[role])
    return args, pins, intake


def _review_holdout(args, pins):
    root = args.output.parent
    manifest = root / "adjudication.json"
    review = {"status": "REVIEWED", "reviewed_by": args.received_by, "review_evidence": "fixture review",
              "reviewed_at": datetime.now(timezone.utc).isoformat()}
    for name in ("source", "guideline", "a", "b", "seal", "c"):
        path = getattr(args, name)
        review.update({f"{name}_path": path.relative_to(root).as_posix(), f"{name}_sha256": file_sha256(path)})
    review.update(intake_path=args.holdout_intake.name, intake_sha256=file_sha256(args.holdout_intake))
    digest = _write(manifest, {"schema_version": custody.ADJUDICATION_SCHEMA, "formula_custody": review})
    data = {"adjudication_manifest_sha256": digest, "holdout_custodian": args.received_by,
            "annotation_guideline_sha256": file_sha256(args.guideline)}
    data.update({field: file_sha256(pins[key]) for key, field in custody.PROTOCOL_PINS.items()})
    protocol = {"status": "LOCKED", "locked_at": datetime.now(timezone.utc).isoformat(), "data": data,
                "scope": {"formula_scope_decision": {"decision": "IN_SCOPE"}}}
    return manifest, protocol


def test_holdout_replay_reconstructs_exact_adjudicated_pages_without_export(holdout_packet):
    args, pins, _ = holdout_packet
    c = _sealed_c(args)
    assert c["intended_partition"] == "holdout" and c["holdout_intake_sha256"] == file_sha256(args.holdout_intake)
    manifest, protocol = _review_holdout(args, pins)
    references = custody.replay_holdout_references(manifest, protocol, args.pdf_root)
    assert not args.output.exists()
    assert references["intended_partition"] == "holdout"
    assert references["custody"]["status"] == "DECLARED_CUSTODY_COMPLETE_FOR_HOLDOUT"
    assert references["custody"]["acceptance_status"] == "NOT_EVALUATED"
    assert not references["custody"]["independent_ground_truth_verified"]
    assert references["custody"]["review_manifest_sha256"] == file_sha256(manifest)
    assert references["documents"][0]["pages"][0]["formulas"][0]["content_raw"] == "x=1"
    assert len(references["documents"][0]["pages"]) == 1
    assert references["documents"] == custody.process(args)["documents"]


def test_holdout_templates_are_blank_and_need_no_peer_submission(holdout_packet):
    args, _, _ = holdout_packet
    args.a.unlink()
    args.b.unlink()
    for role in ("a", "b"):
        output = args.output.with_name(f"blank-{role}.json")
        assert custody.main([f"template-{role}", "--source", str(args.source), "--guideline", str(args.guideline),
                             "--pdf-root", str(args.pdf_root), "--holdout-intake", str(args.holdout_intake),
                             "--output", str(output)]) == 0
        blank = json.loads(output.read_bytes())
        assert blank["status"] == "BLANK" and blank["role"] == role.upper() and blank["annotator"] is None
        assert blank["holdout_intake_sha256"] == file_sha256(args.holdout_intake)
        assert blank["no_peer_before_submission"] is None and blank["documents"][0]["pages"][0]["formulas"] is None
        assert "annotation_sha256" not in blank and "ab_seal_sha256" not in blank


def test_intake_rejects_repinned_sample_page_change_before_packets(holdout_packet):
    args, pins, intake = holdout_packet
    sample = json.loads(pins["sample"].read_bytes())
    sample["documents"][0]["pages"] = [2]
    intake["sample_sha256"] = _write(pins["sample"], sample)
    _write(args.holdout_intake, intake)
    args.a.unlink()
    with pytest.raises(ValueError, match="pages differ from the sample"):
        custody.process(args)
    assert not args.output.exists()


def test_holdout_rejects_missing_intake_and_unauthorized_seal(holdout_packet):
    args, _, _ = holdout_packet
    intake_path = args.holdout_intake
    args.holdout_intake = None
    with pytest.raises(ValueError, match="holdout source manifest with reviewed intake"):
        custody.process(args)
    args.holdout_intake = intake_path
    args.action, args.received_by = "seal", "fixture-other"
    with pytest.raises(ValueError, match="requires the split custodian"):
        custody.process(args)
    assert not args.output.exists()


def test_holdout_replay_rejects_wrong_lock_and_post_review_changes(holdout_packet):
    args, pins, _ = holdout_packet
    _sealed_c(args)
    manifest, protocol = _review_holdout(args, pins)
    other_protocol = deepcopy(protocol)
    other_protocol["data"]["formula_holdout_sample_sha256"] = "a" * 64
    with pytest.raises(ValueError, match="differs from the locked sample"):
        custody.replay_holdout_references(manifest, other_protocol, args.pdf_root)
    amended = json.loads(manifest.read_bytes())
    amended["formula_custody"]["reviewed_at"] = "2024-11-01T00:00:00Z"
    other_protocol["data"].update(protocol["data"])
    other_protocol["data"]["adjudication_manifest_sha256"] = _write(manifest, amended)
    with pytest.raises(ValueError, match="completed before custodian review"):
        custody.replay_holdout_references(manifest, other_protocol, args.pdf_root)
    _write(args.c, {**json.loads(args.c.read_bytes()), "notes": "Changed after custodian review"})
    with pytest.raises(ValueError, match="c SHA-256 differs"):
        custody.replay_holdout_references(manifest, other_protocol, args.pdf_root)


def test_holdout_custody_rejects_ambiguous_packet_json(holdout_packet):
    args, _, _ = holdout_packet
    raw = args.a.read_text(encoding="utf-8")
    args.a.write_text('{"status": "BLANK",' + raw[1:], encoding="utf-8")
    result = custody.process(args)
    assert result["status"] == "NOT_EVALUATED" and "Duplicate JSON keys" in result["issues"][0]
