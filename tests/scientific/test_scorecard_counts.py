import json

import pytest

from benchmark.scientific_evaluation import scorecard_counts
from benchmark.scientific_evaluation.teds_metric import evaluate_table_collection
from ocr_artifacts.hashing import sha256_file


@pytest.fixture
def document(tmp_path, monkeypatch):
    directory = tmp_path / "DOC"
    directory.mkdir()
    markdown = directory / "result.md"
    markdown.write_text("# Trang 1\n\nThêm\n", encoding="utf-8")
    pdf_hash = "a" * 64
    publication = {"id": "DOC", "pdf_sha256": pdf_hash, "source_dir": str(directory),
                   "ocr_identity": "fixture", "total_pages": 2, "result_md_sha256": sha256_file(markdown)}
    for name, field in (("COMPLETED.json", "completion_sha256"), ("ocr_receipt.json", "ocr_receipt_sha256")):
        path = directory / name
        path.write_text("{}", encoding="utf-8")
        publication[field] = sha256_file(path)
    monkeypatch.setattr(scorecard_counts, "verify_extraction_source", lambda path: publication.copy())
    monkeypatch.setattr(scorecard_counts, "valid_ocr", lambda *args: True)
    monkeypatch.setattr(scorecard_counts, "verify_completed", lambda *args: True)
    return directory, publication


def _evidence(path, content):
    path.write_text(content, encoding="utf-8")
    return {"path": path.name, "sha256": sha256_file(path)}


def test_counts_use_final_markdown_and_keep_missing_and_empty_units(tmp_path, document):
    _, publication = document
    gt = {"pdf_sha256": publication["pdf_sha256"], "text_pages": {
        "1": _evidence(tmp_path / "p1.txt", ""), "2": _evidence(tmp_path / "p2.txt", "020")}}
    units = [{"unit_id": str(page), "page": page, "region_id": "page", "metrics": ["cer", "wer", "der", "reading_order"]}
             for page in (1, 2)]
    scores = {(metric, row["unit_id"]): row for metric, row in scorecard_counts._document_counts(
        units, publication, gt, tmp_path, None, "visible_strict_v1")}
    blank = scores["cer", "1"]
    assert (blank["status"], blank["numerator"], blank["denominator"]) == ("MEASURED", 4, 0)
    missing = scores["cer", "2"]
    assert (missing["status"], missing["numerator"], missing["denominator"]) == ("MISSING_OUTPUT", 3, 3)
    assert scores["reading_order", "2"]["status"] == "NOT_EVALUATED"
    (tmp_path / "p2.txt").write_text("O2O", encoding="utf-8")
    with pytest.raises(ValueError, match="Frozen evidence changed"):
        list(scorecard_counts._document_counts(units, publication, gt, tmp_path, None, "visible_strict_v1"))


def test_duplicate_markers_and_changed_receipt_are_rejected(tmp_path, document):
    directory, publication = document
    markdown = directory / "result.md"
    markdown.write_text("# Trang 1\n\nA\n\n# Trang 1\n\nB\n", encoding="utf-8")
    gt = {"pdf_sha256": publication["pdf_sha256"]}
    unit = [{"unit_id": "u", "page": 1, "region_id": "page", "metrics": ["cer"]}]
    with pytest.raises(ValueError, match="unambiguous page markers"):
        list(scorecard_counts._document_counts(unit, publication, gt, tmp_path, None, "visible_strict_v1"))
    (directory / "COMPLETED.json").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="changed while generating counts"):
        list(scorecard_counts._document_counts([], publication, gt, tmp_path, None, "visible_strict_v1"))


def test_raw_teds_and_structure_counts_do_not_reconstruct_from_rounded_mean(monkeypatch):
    from benchmark.scientific_evaluation import teds_metric

    monkeypatch.setattr(teds_metric, "match_tables", lambda *args: [(0, 0)])
    monkeypatch.setattr(teds_metric, "compute_teds", lambda *args: 1 / 3)
    monkeypatch.setattr(teds_metric, "compute_teds_struct", lambda *args: 2 / 3)
    tables = evaluate_table_collection([{}, {}], [{}])
    row = {"prediction_status": "PRESENT", "tables": tables, "numeric_cells": {
        "location_tp": 2, "location_fn": 1, "location_fp": 4},
        "reading_order": {"status": "MEASURED", "correct_pairs": 3, "gt_pairs": 7, "missing_nodes": 1,
                          "duplicate_predictions": 2}}
    for metric, numerator, denominator in (("teds_content", 1 / 3, 2), ("teds_structure", 2 / 3, 2),
                                            ("numeric_cell_exact", 2, 3), ("reading_order", 3, 7)):
        record = scorecard_counts._structure_count("u", metric, row, "fixture")
        assert (record["numerator"], record["denominator"]) == (numerator, denominator)
    assert tables["mean_teds"] * tables["gt_table_count"] != tables["teds_sum"]


def test_keyword_count_keeps_source_page_and_extra_occurrences(tmp_path, document, monkeypatch):
    directory, publication = document
    (directory.parent / "keyword_dictionary.snapshot.json").write_text("{}", encoding="utf-8")
    gt = _evidence(tmp_path / "gt.json", "{}")
    alignment = _evidence(tmp_path / "alignment.json", json.dumps({"ground_truth_sha256": gt["sha256"]}))
    observed = {"identity": {"pdf_sha256": publication["pdf_sha256"],
                              "result_md_sha256": publication["result_md_sha256"]}}
    monkeypatch.setattr(scorecard_counts.keyword_acceptance, "inventory", lambda *args: observed)
    monkeypatch.setattr(scorecard_counts.keyword_acceptance, "evaluate", lambda *args: {
        "status": "FAIL", "unit_locations": {"region": {"physical_page": 2}},
        "correct": [{"reference": {"unit_id": "region"}}], "missing": [{"unit_id": "region"}],
        "extra": [{"unit_id": "region"}, {"unit_id": "region"}]})
    units = [{"unit_id": "u", "page": 2, "region_id": "region", "metrics": ["keyword_recall"]}]
    _, row = next(scorecard_counts._document_counts(
        units, publication, {"pdf_sha256": publication["pdf_sha256"], "keywords": gt}, tmp_path,
        (tmp_path, alignment), "visible_strict_v1"))
    assert (row["numerator"], row["denominator"], row["evidence"]["extra"]) == (1, 2, 2)


def test_formula_reference_units_merge_exact_source_counts_or_remain_unscored(tmp_path, document):
    _, publication = document
    gt_path = tmp_path / "gt-index.json"
    gt = {"documents": {"DOC": {"pdf_sha256": publication["pdf_sha256"]}}}
    gt_path.write_text(json.dumps(gt), encoding="utf-8")
    inputs = {"artifact_path": lambda *_: gt_path, "artifact": lambda *_: gt,
        "sample": {"units": [{"unit_id": "formula", "document_id": "DOC", "page": 1,
                               "region_id": "formula:ref", "metrics": ["formula_detection_recall"]}]},
        "predictions": {"candidate": {"documents": [publication]}}, "prediction_hash": "fixture",
        "protocol": {"evaluation": {"normalization": "visible_strict_v1"}}, "plan": {"sample_sha256": "fixture"},
        "verification": {"protocol_sha256": "fixture", "verified_artifact_hashes": {"data.gt_manifest_sha256": sha256_file(gt_path)}}}
    incomplete = scorecard_counts.count_verified_predictions(inputs, "candidate")
    assert incomplete["records_by_metric"]["formula_detection_recall"][0]["status"] == "NOT_EVALUATED"
    projected = {"records_by_metric": {metric: [] for metric in scorecard_counts.FORMULA_METRICS}}
    projected["records_by_metric"]["formula_detection_recall"] = [
        {"unit_id": "formula", "status": "MISSING_OUTPUT", "numerator": 0, "denominator": 1}]
    counted = scorecard_counts.count_verified_predictions(inputs, "candidate", formula_counts=projected)
    assert counted["records_by_metric"]["formula_detection_recall"][0]["denominator"] == 1
    projected["records_by_metric"]["formula_detection_recall"].append({"unit_id": "other"})
    with pytest.raises(ValueError, match="frozen metric units exactly"):
        scorecard_counts.count_verified_predictions(inputs, "candidate", formula_counts=projected)


def test_development_pilot_gt_cannot_be_promoted_to_holdout_counts(tmp_path, document):
    directory, publication = document
    gt = _evidence(tmp_path / "pilot.json", json.dumps({"intended_partition": "development"}))
    alignment = _evidence(tmp_path / "alignment.json", json.dumps({"ground_truth_sha256": gt["sha256"]}))
    with pytest.raises(ValueError, match="Development pilot annotations"):
        scorecard_counts._keyword_counts(directory, publication, gt, tmp_path, (tmp_path, alignment))


@pytest.mark.parametrize("reference,prediction,expected_status,errors,uncomposed", [
    ("ma", "má", "MEASURED", 1, 0),
    ("đổi", "đổ\u0309i", "MEASURED", 0, 1),
    ("đổ\u0309i", "đổi", "NOT_EVALUATED", None, None),
])
def test_der_source_counts_preserve_zero_denominator_errors_and_gate_marks(
        tmp_path, document, reference, prediction, expected_status, errors, uncomposed):
    directory, publication = document
    (directory / "result.md").write_text("# Trang 1\n\n" + prediction, encoding="utf-8")
    publication["result_md_sha256"] = sha256_file(directory / "result.md")
    gt = {"pdf_sha256": publication["pdf_sha256"], "text_pages": {
        "1": _evidence(tmp_path / "text.txt", reference)}}
    unit = {"unit_id": "text", "page": 1, "region_id": "page", "metrics": ["der"]}
    _, row = next(scorecard_counts._document_counts([unit], publication, gt, tmp_path, None, "visible_strict_v1"))
    assert row["status"] == expected_status
    if expected_status == "MEASURED":
        assert row["numerator"] == errors
        assert row["evidence"]["diacritic_gate"]["uncomposed_prediction_marks"] == uncomposed


def test_layout_scorecard_counts_empty_missing_and_unannotated_pages(tmp_path, document):
    directory, publication = document
    publication["total_pages"] = 4
    pdf_hash = publication["pdf_sha256"]
    scope = {"coordinate_space": "pdf_points_top_left_rotated", "transforms": [{"op": "rotate", "degrees": 90}]}
    box = [10, 20, 40, 60]
    region = {"id": "ref", "bbox": box, "category": "Title"}
    structured = {"schema_version": "structured-page-gt-v1", "document_id": "DOC", "pdf_sha256": pdf_hash,
                  "total_pages": 4, "intended_partition": "holdout", "pages": [
                      {"page": 1, **scope, "layout": [region]}, {"page": 2, **scope, "layout": []},
                      {"page": 3, **scope, "layout": [region]}, {"page": 4, **scope},
                  ]}
    item = {"kind": "b", "bbox": box, "block_type": "title", "text_raw": "A", "text_corrected": "A",
            "correction_source": None, "source": "fixture", "device": "fixture",
            "confidence": None, "confidence_source": "unavailable"}
    extraction = {"schema_version": "extraction-v1", "doc_id": "DOC", "doc_sha16": pdf_hash[:16],
                  "pipeline_version": "fixture", "profile": "unified_gpu_full_ocr", "total_pages": 4,
                  "pages": [{"page": page, **scope, "width": 100, "height": 100, "page_type": "fixture",
                             "items": [{**item, "id": f"{pdf_hash[:16]}:p{page:04d}:b0001"}]} for page in (1, 2)]}
    _evidence(directory / "extraction.json", json.dumps(extraction))
    metrics = ["layout_recall", "layout_errors_per_gt"]
    units = [{"unit_id": str(page), "page": page, "region_id": "page", "metrics": metrics} for page in range(1, 5)]

    def counts():
        gt = {"pdf_sha256": pdf_hash, "structure": _evidence(tmp_path / "layout.json", json.dumps(structured))}
        return {(metric, row["unit_id"]): row for metric, row in scorecard_counts._document_counts(
            units, publication, gt, tmp_path, None, "visible_strict_v1")}

    result = counts()
    matched = result["layout_recall", "1"]
    assert (matched["numerator"], matched["denominator"], matched["evidence"]["reference_categories"]) == (1, 1, ["Title"])
    empty = result["layout_errors_per_gt", "2"]
    assert (empty["numerator"], empty["denominator"], empty["evidence"]["fp"]) == (1, 0, 1)
    missing = result["layout_errors_per_gt", "3"]
    assert (missing["status"], missing["numerator"], missing["denominator"]) == ("MISSING_OUTPUT", 1, 1)
    assert result["layout_recall", "4"]["status"] == "NOT_EVALUATED"
    structured["pages"][0]["transforms"] = [{"op": "rotate", "degrees": 270}]
    with pytest.raises(ValueError, match="coordinate spaces/transforms differ"):
        counts()
    structured["intended_partition"] = "development"
    with pytest.raises(ValueError, match="GT declared for holdout"):
        counts()


def test_scorecard_reads_pinned_reviewed_spans_and_penalizes_a_missing_page(tmp_path, document):
    directory, publication = document
    pdf_hash = publication["pdf_sha256"]
    page_scope = {"coordinate_space": "pdf_points_top_left", "transforms": []}
    nodes = [{"id": "a", "text": "A B", "bbox": [0, 0, 10, 10]},
             {"id": "b", "text": "C", "bbox": [10, 0, 15, 10]}]
    order = {"alignment_mode": "reviewed_spans", "nodes": nodes, "before_pairs": [["a", "b"]],
             "adjacent_pairs": [["a", "b"]]}
    structure = _evidence(tmp_path / "structured.json", json.dumps({
        "schema_version": "structured-page-gt-v1", "document_id": "DOC", "pdf_sha256": pdf_hash, "total_pages": 2,
        "pages": [{"page": n, **page_scope, "reading_order": order} for n in (1, 2)],
    }))
    first, second = [f"{pdf_hash[:16]}:p0001:b{n:04d}" for n in (1, 2)]
    items = [{"kind": "b", "id": key, "bbox": box, "text_raw": text, "text_corrected": text, "correction_source": None,
              "source": "fixture", "device": "fixture", "confidence": None, "confidence_source": "unavailable"}
             for key, box, text in ((first, [0, 0, 5, 10], "A"), (second, [5, 0, 15, 10], "B C"))]
    extraction = _evidence(directory / "extraction.json", json.dumps({
        "schema_version": "extraction-v1", "doc_id": "DOC", "doc_sha16": pdf_hash[:16], "pipeline_version": "fixture",
        "profile": "unified_gpu_full_ocr", "total_pages": 2,
        "pages": [{"page": 1, **page_scope, "width": 100, "height": 100, "page_type": "fixture", "items": items}],
    }))
    manifest = {
        "schema_version": "ocr-reading-order-alignment-v1", "document_id": "DOC", "pdf_sha256": pdf_hash,
        "ground_truth_sha256": structure["sha256"], "extraction_sha256": extraction["sha256"],
        "reviewed_by": "fixture-reviewer", "reviewed_at": "2020-01-01T12:00:00+07:00",
        "reviewed_against_source": True, "intended_partition": "holdout", "pages": [{"page": 1, "mappings": [
            {"gt_id": "a", "reason": "Split fixture", "spans": [
                {"prediction_id": first, "start": 0, "end": 1}, {"prediction_id": second, "start": 0, "end": 1}]},
            {"gt_id": "b", "reason": "Merged fixture", "spans": [{"prediction_id": second, "start": 2, "end": 3}]},
        ]}],
    }
    alignment_path = tmp_path / "alignment.json"
    alignment = _evidence(alignment_path, json.dumps(manifest))
    units = [{"unit_id": str(n), "page": n, "region_id": "page", "metrics": ["reading_order"]} for n in (1, 2)]
    gt = {"pdf_sha256": pdf_hash, "structure": structure}

    def counts(record=None):
        return [row for _, row in scorecard_counts._document_counts(
            units, publication, gt, tmp_path, None, "visible_strict_v1",
            reading_order_alignment=(tmp_path, record) if record else None)]

    observed, missing = counts(alignment)
    assert (observed["status"], observed["numerator"], observed["denominator"]) == ("MEASURED", 1, 1)
    assert observed["evidence"]["alignment_sha256"] == alignment["sha256"]
    assert (missing["status"], missing["numerator"], missing["denominator"]) == ("MISSING_OUTPUT", 0, 1)
    unreviewed, _ = counts()
    assert unreviewed == {"unit_id": "1", "status": "NOT_EVALUATED", "reason": "MISSING_REVIEWED_ALIGNMENT"}
    manifest["intended_partition"] = "development"
    dev = _evidence(alignment_path, json.dumps(manifest))
    with pytest.raises(ValueError, match="different partition"):
        counts(dev)
    manifest.update(intended_partition="holdout", extraction_sha256="0" * 64)
    stale = _evidence(alignment_path, json.dumps(manifest))
    with pytest.raises(ValueError, match="exact document, GT and extraction"):
        counts(stale)
