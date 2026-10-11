"""
Mandatory Counterexample Test Suite for Protocol V5.
Verifies all 6 counterexample criteria defined in RESEARCH_PROTOCOL_V5.md Section 7:
1. Missing predictions (no false perfect scores)
2. Mismatched document/page keys (no cross-page leakage)
3. Absent layout classes (AP is None/not_evaluated, never 1.0)
4. Misplaced Vietnamese diacritics (sequence-aligned DER detects tone shifts)
5. Merged cells in tables (rowspan/colspan structural penalties in TEDS)
6. Markdown content loss and broken image detection
"""

import pytest
from pathlib import Path
from benchmark.scientific_evaluation.teds_metric import compute_teds, compute_teds_struct, evaluate_table_collection
from benchmark.scientific_evaluation.dla_metric import compute_dla_map, evaluate_coco_class_ap
from benchmark.scientific_evaluation.ocr_metric import compute_cer, compute_wer, compute_der, compute_reading_order
from benchmark.scientific_evaluation.markdown_evaluator import evaluate_final_markdown, parse_markdown_artifacts


def test_counterexample_missing_predictions():
    """
    Counterexample 1: When predictions are missing/dropped, metrics must NEVER
    assign a false perfect score (1.0).
    """
    # 1. Reading order with 5 reference paragraphs and empty/sparse prediction
    refs = [
        "1. Đoạn văn thứ nhất giới thiệu tổng quan đề tài.",
        "2. Đoạn văn thứ hai mô tả phương pháp thực nghiệm.",
        "3. Đoạn văn thứ ba phân tích kết quả dữ liệu.",
        "4. Đoạn văn thứ tư so sánh các baseline.",
        "5. Đoạn văn thứ năm kết luận và kiến nghị."
    ]
    # Prediction dropped almost all paragraphs (only retained 1 snippet)
    pred_sparse = "1. Đoạn văn thứ nhất giới thiệu tổng quan đề tài."
    order_res = compute_reading_order(refs, pred_sparse)
    assert order_res["matched_fraction"] <= 0.25
    assert order_res["penalized_score"] < 0.25
    # Must NOT give 1.0!
    assert order_res["penalized_score"] != 1.0

    # 2. Table collection with 2 GT tables and 0 predicted tables
    gt_tables = [
        {"table_id": "tab_1", "html": "<table><tr><td>A</td><td>B</td></tr></table>"},
        {"table_id": "tab_2", "html": "<table><tr><td>C</td><td>D</td></tr></table>"}
    ]
    tab_res = evaluate_table_collection(gt_tables, [])
    assert tab_res["mean_teds"] == 0.0
    assert tab_res["missing_table_count"] == 2


def test_counterexample_mismatched_document_or_page_keys():
    """
    Counterexample 2: Predictions for doc_A page 1 must NOT match ground truth
    for doc_A page 2 or doc_B page 1.
    """
    gt = [
        {"bbox": [10.0, 10.0, 100.0, 50.0], "category": "header", "image_id": "docA_page1"},
    ]
    # Prediction has identical coordinates and category, but belongs to docA_page2!
    pred_wrong_page = [
        {"bbox": [10.0, 10.0, 100.0, 50.0], "category": "header", "score": 0.99, "image_id": "docA_page2"},
    ]

    res = compute_dla_map(gt, pred_wrong_page, classes=["header"])
    # Because image_ids differ, this prediction is a False Positive on page2 and page1 has no prediction!
    # AP@50 on page1 must be 0.0!
    assert res["mAP@50"] == 0.0


def test_counterexample_absent_classes():
    """
    Counterexample 3: If a class has zero ground truth annotations in the dataset,
    official COCO AP must be None / not_evaluated, and must NOT artificially inflate mAP with 1.0.
    """
    gt = [
        {"bbox": [10.0, 10.0, 100.0, 50.0], "category": "header", "image_id": "p1"},
    ]
    pred = [
        {"bbox": [10.0, 10.0, 100.0, 50.0], "category": "header", "score": 0.95, "image_id": "p1"},
        {"bbox": [20.0, 20.0, 50.0, 50.0], "category": "formula", "score": 0.90, "image_id": "p1"},
    ]
    # "formula" has 0 GT boxes!
    res = compute_dla_map(gt, pred, classes=["header", "formula"])
    assert res["per_class"]["formula"]["status"] == "not_evaluated_no_ground_truth"
    assert res["per_class"]["formula"]["ap_50"] is None
    # Header was evaluated and has 1.0
    assert res["per_class"]["header"]["ap_50"] == 1.0
    # Overall mAP should only reflect evaluated classes
    assert res["mAP@50"] == 1.0


def test_counterexample_misplaced_diacritics():
    """
    Counterexample 4: Vietnamese tone mark shifts and diacritic deletions/substitutions
    must be captured by sequence-aligned DER.
    """
    # 1. Missing tone mark: "Việt Nam" -> "Viet Nam"
    ref1 = "Việt Nam"
    pred1 = "Viet Nam"
    der1 = compute_der(ref1, pred1)
    assert der1 > 0.0

    # 2. Shifted / misplaced tone: "hòa" vs "hào" (both have accent on a vowel, but different vowel!)
    ref2 = "hòa bình"
    pred2 = "hào bình"
    der2 = compute_der(ref2, pred2)
    assert der2 > 0.0

    # 3. Tone modification: "lớn" vs "lơn" (dropped horn diacritic on 'ơ')
    ref3 = "phát triển lớn mạnh"
    pred3 = "phát triển lơn mạnh"
    der3 = compute_der(ref3, pred3)
    assert der3 > 0.0


def test_counterexample_merged_cells_table():
    """
    Counterexample 5: Table with merged cells (rowspan or colspan) must be distinguished
    from tables with flattened / missing spans.
    """
    # GT table with colspan=2 in first row
    gt_html = "<table><tr><th colspan='2'>Doanh thu hợp nhất</th></tr><tr><td>Năm 2019</td><td>Năm 2020</td></tr></table>"
    # Pred table with missing colspan (regular cell)
    pred_html_flattened = "<table><tr><th>Doanh thu hợp nhất</th></tr><tr><td>Năm 2019</td><td>Năm 2020</td></tr></table>"

    teds_full = compute_teds(gt_html, pred_html_flattened)
    teds_struct = compute_teds_struct(gt_html, pred_html_flattened)

    # Must be penalized for incorrect cell spanning!
    assert teds_full < 1.0
    assert teds_struct < 1.0


def test_counterexample_markdown_content_loss(tmp_path):
    """
    Counterexample 6: Markdown evaluator must detect missing content and broken image links.
    """
    md_file = tmp_path / "result.md"
    md_content = """# Báo cáo năm 2020
> **Header**: Báo cáo tài chính

Đoạn văn bản số một.

![Embedded image](../images/non_existent_image.png)

| Chỉ tiêu | Giá trị |
| --- | --- |
| Doanh thu | 500 tỷ |
"""
    md_file.write_text(md_content, encoding="utf-8")

    gt_text = "Đoạn văn bản số một. Đoạn văn bản số hai bị mất hoàn toàn trong quá trình trích xuất."
    eval_res = evaluate_final_markdown(md_file, ground_truth_text=gt_text)

    # Broken image must be reported
    assert eval_res["broken_image_count"] == 1
    assert "non_existent_image.png" in eval_res["broken_images"][0]

    # Dropped second paragraph must be penalized in CER and WER
    assert eval_res["text_evaluation"]["cer"] > 0.30
    assert eval_res["text_evaluation"]["wer"] > 0.30
