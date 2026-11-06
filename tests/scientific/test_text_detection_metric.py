"""Detection scores require the primary model universe and a pinned input image."""
import copy
import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pytest

from ocr_recognition.detection_evidence import capture_primary_detections, input_image_identity
from benchmark.scientific_evaluation import text_detection_metric as detection
from benchmark.scientific_evaluation.structured_scoreboard import evaluate_structure


SETTINGS = {"protocol": detection.PROTOCOL, "iou_threshold": .5, "ignore_overlap": .5}
FRAME = {"coordinate_space": "pdf_points_top_left", "transforms": [], "width": 400, "height": 200}


def source(boxes, page=1):
    engine = SimpleNamespace(METHOD="fixture-db", last_input_shape=[100, 200, 3], last_detections=[
        {"bbox": box, "polygon": [[box[0], box[1]], [box[2], box[1]], [box[2], box[3]], [box[0], box[3]]], "score": .9}
        for box in boxes])
    snapshot = capture_primary_detections(engine, input_image_identity(np.zeros((100, 200, 3), np.uint8)), [400, 200])
    assert snapshot["status"] == "CAPTURED"
    return {"page_num": page, "width": 400, "height": 200, "blocks": [],
            "metadata": {"coordinate_space": {"name": "pdf_display_points"}, "primary_text_detection": snapshot}}


def annotation(record, rows):
    return {"input_image_sha256": record["metadata"]["primary_text_detection"]["input_image"]["sha256"], "regions": rows}


def gt(key, box, ignore=False):
    return {"id": key, "bbox": [n * 2 for n in box], "ignore": ignore}


def test_matching_keeps_raw_rejected_duplicates_and_degenerate_detections():
    # blocks=[] represents a recognizer that kept none of the five detections.
    page = source([[10, 10, 30, 20], [10, 10, 30, 20], [100, 0, 110, 10], [150, 40, 160, 50], [199, 80, 199, 85]])
    label = annotation(page, [gt("r", [10, 10, 30, 20]), gt("missing", [50, 50, 80, 60]),
                              {"id": "ignore", "bbox": [0, 0, 230, 50], "ignore": True}])
    result = detection.evaluate_page(label, page, {"page": 1, **FRAME}, SETTINGS)
    assert result["counts"] == {"tp": 1, "fp": 3, "fn": 1}
    assert result["predicted_regions"] == 5 and result["ignored_prediction_ids"] == ["d000002"]
    assert result["duplicate_prediction_ids"] in (["d000000"], ["d000001"])
    assert result["degenerate_prediction_ids"] == ["d000004"]
    assert result["missing_reference_ids"] == ["missing"]


def test_matching_maximizes_cardinality_before_total_iou():
    page = source([[11, 10, 21, 20], [8, 10, 18, 20]])
    label = annotation(page, [gt("a", [10, 10, 20, 20]), gt("b", [14, 10, 24, 20])])
    result = detection.evaluate_page(label, page, {"page": 1, **FRAME}, SETTINGS)
    assert result["counts"] == {"tp": 2, "fp": 0, "fn": 0}
    assert {(row["reference_id"], row["prediction_id"]) for row in result["matched"]} == {("a", "d000001"), ("b", "d000000")}


def test_confirmed_blank_and_zero_detections_have_real_counts_without_fictitious_accuracy():
    page = source([[1, 1, 5, 5]])
    empty = detection.evaluate_page(annotation(page, []), page, {"page": 1, **FRAME}, SETTINGS)
    summary = detection.summarize([empty])
    assert summary["status"] == "EMPTY_REFERENCE" and summary["counts"] == {"tp": 0, "fp": 1, "fn": 0}
    assert summary["precision"] is summary["recall"] is summary["hmean"] is None
    page = source([])
    absent = detection.evaluate_page(annotation(page, [gt("a", [1, 1, 5, 5])]), page, {"page": 1, **FRAME}, SETTINGS)
    summary = detection.summarize([absent, empty])
    assert summary["counts"] == {"tp": 0, "fp": 1, "fn": 1}
    assert summary["recall"] == summary["hmean"] == 0


def test_legacy_or_missing_evidence_cannot_borrow_post_recognition_blocks():
    page = source([[1, 1, 5, 5]])
    label = annotation(page, [gt("a", [1, 1, 5, 5])])
    for unmeasured in (None, {"metadata": {}, "blocks": [{"bbox": [2, 2, 10, 10], "text": "correct"}]}):
        result = detection.evaluate_page(label, unmeasured, {"page": 1, **FRAME}, SETTINGS)
        assert result["status"] == "NOT_EVALUATED" and result["counts"] is None
        assert detection.summarize([result])["observed_counts"] is None
    unknown = detection.evaluate_page({"input_image_sha256": None, "regions": None}, page, {"page": 1, **FRAME}, SETTINGS)
    known = detection.evaluate_page(label, page, {"page": 1, **FRAME}, SETTINGS)
    combined = detection.summarize([unknown, known])
    assert combined["counts"] is None and combined["precision"] is None and combined["observed_counts"]["tp"] == 1


def test_image_identity_geometry_and_explicit_matching_are_required():
    page = source([[1, 1, 5, 5]])
    label = annotation(page, [gt("a", [1, 1, 5, 5])])
    with pytest.raises(ValueError, match="pixel SHA256"):
        detection.evaluate_page({**label, "input_image_sha256": "1" * 64}, page, {"page": 1, **FRAME}, SETTINGS)
    with pytest.raises(ValueError, match="dimensions or page"):
        detection.evaluate_page(label, page, {"page": 2, **FRAME}, SETTINGS)
    for settings in (None, {**SETTINGS, "iou_threshold": True}, {**SETTINGS, "ignore_overlap": float("nan")}):
        with pytest.raises(ValueError):
            detection.evaluate_page(label, page, {"page": 1, **FRAME}, settings)
    unsupported = detection.evaluate_page(label, page, {"page": 1, **FRAME, "transforms": [{"op": "rotate", "degrees": 90}]}, SETTINGS)
    assert unsupported["reason"] == "UNSUPPORTED_TEXT_DETECTION_TARGET_FRAME" and unsupported["counts"] is None


def structured_fixture(tmp_path):
    directory = tmp_path / "DOC"
    (directory / "pages").mkdir(parents=True)
    first, second = source([[1, 1, 5, 5]]), source([], page=2)
    labels = {"schema_version": "structured-page-gt-v1", "document_id": "DOC", "pdf_sha256": "a" * 64,
              "total_pages": 2, "text_detection_matching": SETTINGS, "pages": [
                  {"page": n, "coordinate_space": "pdf_points_top_left", "transforms": [],
                   "text_detection": annotation(record, [gt("a", [1, 1, 5, 5])])}
                  for n, record in enumerate((first, second), 1)]}
    extraction = {"schema_version": "extraction-v1", "doc_id": "DOC", "doc_sha16": "a" * 16,
                  "pipeline_version": "fixture", "profile": "unified_gpu_full_ocr", "total_pages": 2,
                  "pages": [{"page": n, **FRAME, "page_type": "fixture", "items": []} for n in (1, 2)]}
    (directory / "extraction.json").write_text(json.dumps(extraction), encoding="utf-8")
    (directory / "pages/page-0001.json").write_text(json.dumps(first), encoding="utf-8")
    gt_path = tmp_path / "structure.json"
    gt_path.write_text(json.dumps(labels), encoding="utf-8")
    return directory, gt_path, second


def test_structured_scoreboard_reports_missing_source_then_scores_complete_raw_predictions(tmp_path):
    directory, gt_path, second = structured_fixture(tmp_path)
    report = evaluate_structure(directory, gt_path, expected_pdf_sha256="a" * 64)
    assert report["text_detection"]["counts"] is None
    assert report["coverage"]["text_detection"]["measured_pages"] == [1]
    assert report["coverage"]["text_detection"]["unscorable_pages"] == [2]
    path = directory / "pages/page-0002.json"
    path.write_text(json.dumps(second), encoding="utf-8")
    report = evaluate_structure(directory, gt_path, expected_pdf_sha256="a" * 64)
    assert report["text_detection"]["counts"] == {"tp": 1, "fp": 0, "fn": 1}
    assert report["text_detection"]["precision"] == 1
    assert report["text_detection"]["recall"] == .5
    assert report["text_detection"]["hmean"] == 2 / 3
    assert report["pages"][1]["text_detection"]["page_artifact_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert report["eligible_for_quality_acceptance"] is False


def test_source_file_changed_during_scoring_is_rejected(tmp_path, monkeypatch):
    directory, gt_path, second = structured_fixture(tmp_path)
    original = detection.evaluate_page

    def change_source(*args, **kwargs):
        result = original(*args, **kwargs)
        path = directory / "pages/page-0001.json"
        path.write_bytes(path.read_bytes() + b" ")
        return result

    monkeypatch.setattr(detection, "evaluate_page", change_source)
    with pytest.raises(ValueError, match="changed during evaluation"):
        evaluate_structure(directory, gt_path)
