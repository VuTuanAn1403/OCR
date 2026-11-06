"""Formula counts keep missing, duplicate and unannotated pages distinct."""
import hashlib
import json

import pytest

from benchmark.scientific_evaluation import formula_alignment as alignment


FRAME = {"coordinate_space": "pdf_points_top_left", "width": 400, "height": 200, "transforms": []}
BOX = [10, 10, 30, 30]


def predicted(identifier, bbox, *, kind="f", text="x^{2}", **fields):
    item = {"id": identifier, "kind": kind, "bbox": bbox, "text_raw": text, "text_corrected": text,
            "source": "fixture"}
    item.update({"latex": text} if kind == "f" else {"block_type": "formula"})
    return {**item, **fields}


def labelled(identifier, bbox, placement):
    return {"id": identifier, "bbox": bbox, "placement": placement, "format": "LATEX",
            "content_raw": "x^{2}", "equation_label": "(2)" if placement == "display" else None}


def test_matches_by_page_geometry_and_keeps_duplicate_overlapping_ignore():
    inline_box, ignored_box = [70, 10, 90, 30], [100, 10, 120, 30]
    page = {**FRAME, "page": 1, "items": [
        predicted("duplicate", [11, 11, 30, 30]),
        predicted("text", inline_box, kind="b", text="x²", text_corrected="x2"),
        predicted("best", BOX), predicted("ignore", ignored_box), predicted("unplaced", []),
        predicted("out_of_frame", [-1, 10, 30, 30]),
        predicted("hidden", BOX, kind="b", visibility="suppressed"),
    ]}
    annotation = {**FRAME, "page": 1, "formulas": [labelled("inline", inline_box, "inline"),
                  labelled("display", BOX, "display"), labelled("missing", [150, 10, 170, 30], "display")],
                  "ignore_regions": [{"id": "overlaps_regular", "bbox": BOX, "reason": "fixture overlap"},
                                     {"id": "mask", "bbox": ignored_box, "reason": "fixture"}]}
    result, pairs = alignment._align_page("doc", page, annotation, .5)
    assert result["counts"] == {"tp": 2, "fp": 3, "fn": 1}
    assert result["duplicates"] == [{"prediction_id": "duplicate", "reference_ids": ["display"]}]
    assert result["unplaced"] == ["unplaced", "out_of_frame"]
    assert result["ignored"] == [{"prediction_id": "ignore", "ignore_region_ids": ["mask"]}]
    assert result["missing"] == ["missing"] and result["prediction_count"] == 6
    assert result["references"][1]["equation_label"] == "(2)"
    assert result["reference_placement"]["display"] == {"matched": 1, "total": 2}
    assert pairs[0]["prediction_format"] == "TEXT" and pairs[0]["prediction"] == "x²"
    assert pairs[1]["prediction"] == "x^{2}" and pairs[2]["prediction"] is None
    assert "pair_id" not in annotation["formulas"][0]


def test_missing_annotation_and_annotated_negative_have_different_counts():
    page = {**FRAME, "page": 2, "items": [predicted("extra", BOX)]}
    missing, _ = alignment._align_page("doc", page, None, .5)
    null, _ = alignment._align_page("doc", page, {**FRAME, "formulas": None}, .5)
    empty, pairs = alignment._align_page("doc", page, {**FRAME, "formulas": []}, .5)
    assert missing == null and missing["counts"] is None
    assert empty["counts"] == {"tp": 0, "fp": 1, "fn": 0} and pairs == []


def test_alignment_rejects_changed_frame_and_duplicate_reference_ids():
    page = {**FRAME, "page": 1, "items": []}
    with pytest.raises(ValueError, match="frame differs"):
        alignment._align_page("doc", page, {**FRAME, "transforms": [{"op": "rotate"}], "formulas": []}, .5)
    ref = labelled("same", BOX, "inline")
    with pytest.raises(ValueError, match="Duplicate id"):
        alignment._align_page("doc", page, {**FRAME, "formulas": [ref, ref]}, .5)


def test_embedded_raw_text_links_content_without_adding_localization_credit():
    cell = {"row": 0, "col": 2, "bbox": [5, 4, 100, 90], "bbox_source": "cell",
            "text_raw": "Tổng (020 − 2) cuối", "text_corrected": "Tổng (020 = 2) cuối", "source": "fixture-cell"}
    page = {**FRAME, "page": 1, "items": [{"id": "table", "kind": "t", "cells": [cell]}]}
    annotation = {**FRAME, "formulas": [labelled("ref", BOX, "inline")]}
    span = {"id": "cell-span", "locator": {"item_id": "table", "row": 0, "col": 2},
            "start": 5, "end": 14, "reason": "Fixture review", "reference_id": "ref"}
    report, pairs = alignment._align_page("doc", page, annotation, .5, [span])
    assert report["counts"] == {"tp": 0, "fp": 0, "fn": 1}
    assert report["missing"] == ["ref"] and report["references"][0]["embedded_content_span_id"] == "cell-span"
    assert report["embedded_spans"][0]["formula_bbox"] is None
    assert pairs[0]["prediction"] == "(020 − 2)" and pairs[0]["prediction_format"] == "TEXT"


def test_embedded_rejects_overlap_overrides_and_replacement_of_dedicated_prediction():
    block = predicted("block", BOX, kind="b", text="x - 1", block_type="text")
    page = {**FRAME, "page": 1, "items": [block]}
    span = {"id": "one", "locator": {"item_id": "block"}, "start": 0, "end": 4, "reason": "Fixture review"}
    with pytest.raises(ValueError, match="overlapping raw text"):
        alignment._align_page("doc", page, None, .5, [span, {**span, "id": "two", "start": 3, "end": 5}])
    with pytest.raises(ValueError, match="overrides"):
        alignment._align_page("doc", page, None, .5, [{**span, "content_raw": "x = 1"}])
    report, pairs = alignment._align_page("doc", page, None, .5, [span])
    assert report["counts"] is None and pairs == []
    assert report["embedded_spans"][0]["content_raw"] == "x - "
    page["items"].append(predicted("formula", BOX))
    with pytest.raises(ValueError, match="replace a localized formula"):
        alignment._align_page("doc", page, {**FRAME, "formulas": [labelled("ref", BOX, "inline")]},
                              .5, [{**span, "reference_id": "ref"}])


def test_embedded_coarse_table_geometry_cannot_link_content():
    cell = {"row": 0, "col": 0, "bbox": [0, 0, 200, 100], "bbox_source": "table_fallback", "text_raw": "x - 1"}
    page = {**FRAME, "page": 1, "items": [{"id": "table", "kind": "t", "cells": [cell]}]}
    span = {"id": "one", "locator": {"item_id": "table", "row": 0, "col": 0}, "start": 0, "end": 5,
            "reason": "Fixture review"}
    report, _ = alignment._align_page("doc", page, None, .5, [span])
    assert report["embedded_spans"][0]["container_bbox_source"] == "table_fallback"
    with pytest.raises(ValueError, match="in-frame block or cell"):
        alignment._align_page("doc", page, {**FRAME, "formulas": [labelled("ref", BOX, "inline")]},
                              .5, [{**span, "reference_id": "ref"}])


def test_batch_entry_binds_annotation_and_extraction_and_preserves_missing_pairs(tmp_path, monkeypatch):
    doc = tmp_path / "doc"
    doc.mkdir()
    extraction = {"doc_id": "doc", "doc_sha16": "a" * 16, "total_pages": 2,
                  "pages": [{**FRAME, "page": 1, "items": [predicted("block", BOX, kind="b", text="x-1", block_type="text")]},
                            {**FRAME, "page": 2, "items": [predicted("next-page", BOX)]}]}
    raw = json.dumps(extraction).encode()
    (doc / "extraction.json").write_bytes(raw)
    receipt = json.dumps({"files": {"extraction.json": hashlib.sha256(raw).hexdigest()}}).encode()
    (doc / "ocr_receipt.json").write_bytes(receipt)
    (doc / "COMPLETED.json").write_bytes(receipt)
    publication = {"batches": [], "documents": [{"id": "doc", "source_dir": str(doc), "pdf_sha256": "a" * 64,
                   "total_pages": 2, "ocr_receipt_sha256": hashlib.sha256(receipt).hexdigest(),
                   "completion_sha256": hashlib.sha256(receipt).hexdigest()}]}
    monkeypatch.setattr(alignment, "collect_predictions", lambda _: publication)
    labels = {"schema_version": alignment.ANNOTATION_SCHEMA, "documents": [{"document_id": "doc",
              "pdf_sha256": "a" * 64, "total_pages": 2, "pages": [{**FRAME, "page": 1,
              "formulas": [labelled("ref", BOX, "inline")]}]}]}
    labels_path = tmp_path / "annotations.json"
    labels_path.write_text(json.dumps(labels), encoding="utf-8")
    output = tmp_path / "result"
    assert alignment.main(["--batch", str(doc), "--annotations", str(labels_path),
                           "--iou-threshold", ".5", "--output", str(output)]) == 0
    report = json.loads((output / "alignment.json").read_bytes())
    pairs_raw = (output / "cdm-pairs.json").read_bytes()
    assert report["cdm_pairs_sha256"] == hashlib.sha256(pairs_raw).hexdigest()
    assert report["annotated_page_counts"] == {"tp": 0, "fp": 0, "fn": 1}
    assert report["coverage"] == {"documents": 1, "pages": 2, "annotated_pages": 1, "visible_predictions": 1}
    assert report["acceptance_status"] == "NOT_EVALUATED" and not report["independent_ground_truth_verified"]
    assert json.loads(pairs_raw)[0]["prediction"] is None
    evidence_path = tmp_path / "embedded.json"
    evidence = {"schema_version": alignment.EMBEDDED_SCHEMA,
                "annotation_sha256": hashlib.sha256(labels_path.read_bytes()).hexdigest(),
                "documents": [{"document_id": "doc", "pdf_sha256": "a" * 64,
                               "extraction_sha256": hashlib.sha256(raw).hexdigest(),
                               "completion_sha256": hashlib.sha256(receipt).hexdigest(),
                               "pages": [{**FRAME, "page": 1, "spans": [{"id": "one", "locator": {"item_id": "block"},
                                          "start": 0, "end": 3, "reason": "Fixture review", "reference_id": "ref"}]}]}]}
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    linked, pairs = alignment.align_batches([doc], annotations_path=labels_path, iou_threshold=.5,
                                            embedded_spans_path=evidence_path)
    assert linked["embedded_linked_content_pairs"] == 1 and linked["annotated_page_counts"] == report["annotated_page_counts"]
    assert pairs[0]["prediction"] == "x-1"
    labels["documents"][0]["pdf_sha256"] = "d" * 64
    labels_path.write_text(json.dumps(labels), encoding="utf-8")
    with pytest.raises(ValueError, match="annotation SHA256 mismatch"):
        alignment.align_batches([doc], annotations_path=labels_path, iou_threshold=.5, embedded_spans_path=evidence_path)
    with pytest.raises(ValueError, match="PDF identity differs"):
        alignment.align_batches([doc], annotations_path=labels_path, iou_threshold=.5)
    (doc / "extraction.json").write_bytes(raw + b" ")
    with pytest.raises(ValueError, match="differs from verified publication"):
        alignment.align_batches([doc], iou_threshold=.5)
