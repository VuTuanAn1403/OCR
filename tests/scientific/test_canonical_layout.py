import pytest

from benchmark.scientific_evaluation import canonical_layout as layout


def test_class_matching_keeps_duplicates_and_ignores_only_applicable_regions():
    page = "doc:p1"
    reference = layout.reference_regions([
        {"id": "title", "bbox": [0, 0, 10, 10], "category": "Title"},
        {"id": "ignore", "bbox": [0, 0, 20, 20], "ignore": True},
        {"id": "crowd", "bbox": [30, 30, 50, 50], "category": "Text", "iscrowd": True},
        {"id": "footnote", "bbox": [0, 80, 20, 90], "category": "Footnote"},
    ], page)
    items = [
        {"id": "a", "kind": "b", "bbox": [0, 0, 10, 10], "block_type": "title"},
        {"id": "dup", "kind": "b", "bbox": [0, 0, 10, 10], "block_type": "title"},
        {"id": "ignored", "kind": "i", "bbox": [10, 10, 20, 20], "content_type": "FIGURE"},
        {"id": "crowded", "kind": "b", "bbox": [31, 31, 35, 35], "block_type": "text"},
        {"id": "wrong", "kind": "t", "bbox": [31, 31, 35, 35]},
        {"id": "unplaced", "kind": "b", "bbox": [], "block_type": "footnote"},
        {"id": "unmapped", "kind": "b", "bbox": [0, 80, 20, 90], "block_type": "table_cell"},
        {"id": "page-number", "kind": "b", "bbox": [90, 90, 95, 95], "block_type": "page_number"},
        {"id": "header", "kind": "b", "bbox": [30, 0, 50, 9], "block_type": "text",
         "role_final": "running_header", "visibility": "suppressed"},
    ]
    predicted, excluded = layout.prediction_regions(items, page)
    result = layout.evaluate_page(reference, predicted, excluded)
    assert (result["tp"], result["fp"], result["fn"]) == (1, 5, 1)
    assert result["reference_categories"] == ["Footnote", "Title"]
    assert result["duplicate_prediction_ids"] in (["a"], ["dup"])
    assert result["ignored_prediction_ids"] == ["ignored", "crowded"]
    assert result["unmapped_prediction_ids"] == ["unmapped"]
    assert result["unplaced_prediction_ids"] == ["unplaced"]
    assert result["suppressed_furniture_predictions"] == 1
    assert result["excluded_page_number_ids"] == ["page-number"]
    assert result["missing_reference_ids"] == ["footnote"]


def test_layout_ap_keeps_footnote_and_reports_missing_detection():
    pytest.importorskip("pycocotools")
    reference = layout.reference_regions([{"id": "r", "bbox": [0, 0, 10, 10], "category": "Footnote"}], "doc:p1")
    measured = layout.evaluate_page(reference, [], [])
    report = layout.summarize([measured], reference, [], include_ap=True)
    assert report["coco"]["comparison"]["per_class"]["Footnote"]["FN"] == 1
    assert report["coco"]["comparison"]["per_class"]["Footnote"]["AP50"] == 0
    assert report["recall"] == report["f1"] == 0
    empty = layout.evaluate_page([], [], [])
    assert empty["annotation_state"] == "annotated_empty"
    assert layout.summarize([empty], [], [], include_ap=True)["coco"]["reason"] == "NO_REGULAR_LAYOUT_GT"


@pytest.mark.parametrize("row", [
    {"id": "a", "bbox": [0, 0, 10, 10], "category": "decorative"},
    {"id": "a", "bbox": [10, 0, 0, 10], "category": "Title"},
    {"id": "a", "bbox": [0, 0, 10, 10], "category": "Title", "ignore": True, "iscrowd": True},
])
def test_invalid_gt_is_rejected(row):
    with pytest.raises(ValueError):
        layout.reference_regions([row], "doc:p1")
