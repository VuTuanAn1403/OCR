"""Keep callout failures separate from actual body-text projection errors."""
from copy import deepcopy

import pytest

from benchmark.scientific_evaluation.callout_metric import evaluate_window


def fixture():
    frame = {"coordinate_space": "pdf_points_top_left", "transforms": [], "width": 220, "height": 300}
    page = {"page": 1, **frame, "items": [
        {"id": key, "kind": "b", "block_type": "text", "bbox": bbox}
        for key, bbox in (("body-1", [10, 10, 70, 30]), ("quote", [60, 70, 160, 90]), ("body-2", [155, 100, 210, 119]))]}
    record = {**frame, "window_bbox": [0, 0, 220, 300], "quote_regions": [{"id": "q", "bbox": [57, 64, 164, 94]}]}
    chunks = [{"chunk_id": key, "type": "paragraph", "text_corrected": text,
               "spans": [{"page": 1, "block_ids": [key]}]}
              for key, text in (("body-1", "Giữ nguyên (020)."), ("quote", "“Đây là trích dẫn.”"), ("body-2", "Nội dung sau."))]
    return page, {"chunks": chunks}, record


def test_body_cer_counts_leaked_quote_in_the_real_chunk_projection():
    page, doc, record = fixture()
    gt = "Giữ nguyên (020).\n\nNội dung sau."
    before = evaluate_window(page, doc, record, gt)
    assert before["quote_ownership"]["inserted_quote_regions"] == 1
    assert before["body_text_score"]["insertions"] == len("“Đây là trích dẫn.”\n\n")
    assert before["body_text_score"]["cer"] > 0
    doc["chunks"][1]["callout_id"] = "separated-quote"
    after = evaluate_window(page, doc, record, gt)
    assert after["quote_ownership"]["separated_observed_regions"] == 1
    assert after["quote_ownership"]["inserted_quote_regions"] == 0
    assert after["body_text_score"]["cer"] == 0 and after["body_chunk_ids"] == ["body-1", "body-2"]


def test_missing_output_and_wrong_detachment_do_not_become_a_clean_pass():
    page, doc, record = fixture()
    doc["chunks"].pop(1)
    missing = evaluate_window(page, doc, record, None)
    assert missing["quote_ownership"]["missing_quote_regions"] == 1
    assert missing["quote_ownership"]["separated_observed_regions"] == 0
    assert missing["body_text_score"]["cer"] is None
    doc["chunks"][0]["callout_id"] = "wrong-detachment"
    negative = evaluate_window(page, doc, {**record, "quote_regions": []}, None)
    assert negative["quote_ownership"]["false_detached_chunks"] == 1
    assert negative["quote_ownership"]["insertion_rate_per_reference_region"] is None
    unknown = evaluate_window(page, doc, {**record, "quote_regions": None}, None)
    assert unknown["quote_ownership"]["false_detached_chunks"] is None


def test_a_cross_window_paragraph_is_not_truncated_to_compute_cer():
    page, doc, record = fixture()
    other = {**deepcopy(doc["chunks"][1]), "chunk_id": "shared-paragraph", "text_corrected": "Body and quote and another page"}
    other["spans"].append({"page": 2, "block_ids": ["outside"]})
    doc["chunks"][1] = other
    result = evaluate_window(page, doc, record, "some reference")
    assert result["crossing_chunk_ids"] == ["shared-paragraph"]
    assert result["body_text_score"]["cer"] is None and result["quote_ownership"]["inserted_quote_regions"] is None


def test_mixed_source_geometry_blocks_only_the_region_metric():
    page, doc, record = fixture()
    page["items"][1]["bbox"] = [10, 70, 160, 90]
    result = evaluate_window(page, doc, record, "independent body reference")
    assert result["quote_ownership"]["reason"] == "AMBIGUOUS_QUOTE_SOURCE_OVERLAP"
    assert result["body_text_score"]["status"] == "MEASURED"
    with pytest.raises(ValueError, match="coordinate frame"):
        evaluate_window(page, doc, {**record, "transforms": [{"op": "rotate", "degrees": 90}]}, None)
