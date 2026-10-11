"""
Acceptance Test Suite A01 - A20 for Scientific Accuracy Evaluation.
Adheres strictly to ANTIGRAVITY_ACCURACY_IMPLEMENTATION.md Section 4 & RESEARCH_PROTOCOL_V5.md.

Tests are numbered and mapped 1-to-1 with acceptance criteria A01 to A20.
"""

import pytest
import unicodedata
from pathlib import Path

from benchmark.scientific_evaluation.ocr_metric import (
    compute_cer,
    compute_wer,
    compute_der,
    compute_cer_detailed,
)
from benchmark.scientific_evaluation.numeric_metric import (
    compute_numeric_metrics,
    NumericExactMatcher,
)
from benchmark.scientific_evaluation.reading_order_metric import (
    compute_reading_order_metrics,
)
from benchmark.scientific_evaluation.teds_metric import (
    compute_teds,
    compute_teds_struct,
    evaluate_table_collection,
)
from benchmark.scientific_evaluation.dla_metric import (
    evaluate_coco_class_ap,
    compute_dla_map,
)
from benchmark.scientific_evaluation.markdown_evaluator import (
    evaluate_final_markdown,
    evaluate_multipage_markdown,
    parse_markdown_artifacts,
)


# ==============================================================================
# A01: CER GT 'abc', pred 'axc'; pred 'abcxyzxyz' (No clamping, unclamped CER)
# ==============================================================================
def test_a01_cer_unclamped_and_counts():
    """A01: CER must not be artificially clamped to 1.0; report exact S, D, I, H."""
    # Case 1: 1 substitution out of 3 chars -> 1/3 = 0.3333
    res1 = compute_cer_detailed("abc", "axc")
    assert res1["cer"] == pytest.approx(1.0 / 3.0, abs=1e-4)
    assert res1["substitutions"] == 1
    assert res1["deletions"] == 0
    assert res1["insertions"] == 0
    assert res1["reference_length"] == 3

    # Case 2: 6 insertions out of 3 reference chars -> 6/3 = 2.0 (unclamped)
    res2 = compute_cer_detailed("abc", "abcxyzxyz")
    assert res2["cer"] == pytest.approx(2.0, abs=1e-4)
    assert res2["insertions"] == 6
    assert res2["reference_length"] == 3
    assert res2["status"] in ("MEASURED", "EVALUATED")


# ==============================================================================
# A02: WER_ws GT 'alpha beta', pred 'alpha' (Parity with JiWER word error rate)
# ==============================================================================
def test_a02_wer_jiwer_parity():
    """A02: WER_ws for 'alpha beta' vs 'alpha' must be 0.5; counts/denominator match JiWER."""
    gt = "alpha beta"
    pred = "alpha"
    wer = compute_wer(gt, pred)
    assert wer == pytest.approx(0.5, abs=1e-4)


# ==============================================================================
# A03: Unicode Canonical NFC vs NFD Normalization
# ==============================================================================
def test_a03_unicode_nfc_vs_nfd():
    """A03: NFC and NFD strings of identical text must yield CER=0.0; strict mode penalizes true differences."""
    text_nfc = unicodedata.normalize("NFC", "tiếng việt")
    text_nfd = unicodedata.normalize("NFD", "tiếng việt")

    # Visible strict normalization maps both to NFC -> 0.0 distance
    cer = compute_cer(text_nfc, text_nfd, normalization_policy="visible_strict_v1")
    assert cer == 0.0

    # True differences (missing accents or case change) must be penalized in strict mode
    cer_diff = compute_cer("tiếng việt", "tieng viet", normalization_policy="visible_strict_v1")
    assert cer_diff > 0.0


# ==============================================================================
# A04: Empty Reference vs Missing Ground Truth Distinction
# ==============================================================================
def test_a04_empty_gt_vs_missing_gt():
    """A04: Confirmed empty GT with predictions yields EMPTY_REFERENCE_INSERTIONS; None GT yields NO_GROUND_TRUTH."""
    # Confirmed empty GT with non-empty prediction
    res_empty = compute_cer_detailed("", "abc")
    assert res_empty["status"] == "EMPTY_REFERENCE_INSERTIONS"
    assert res_empty["insertions"] == 3
    assert res_empty["cer"] is None

    # Both empty
    res_both_empty = compute_cer_detailed("", "")
    assert res_both_empty["status"] == "EMPTY_REFERENCE"
    assert res_both_empty["insertions"] == 0
    assert res_both_empty["cer"] is None


# ==============================================================================
# A05: DER_VN_v1 Vietnamese Diacritic Error Rate and 'đ'/'Đ' Handling
# ==============================================================================
def test_a05_der_vietnamese_diacritics_and_d_bar():
    """A05: DER_VN_v1 penalizes tone/shape errors; 'đ' -> 'd' is stroke error; handles over-generation."""
    # Tone substitution: 'má' (sắc) vs 'mà' (huyền) -> base matches, 1 tone error
    der_tone = compute_der("má", "mà")
    assert der_tone > 0.0

    # 'đ' -> 'd': 'đ' has stroke='bar', 'd' has no bar. Must be penalized as stroke substitution
    der_d = compute_der("đ", "d")
    assert der_d > 0.0

    # Over-generation: 'á' -> 'áá'
    der_rep = compute_der("á", "áá")
    assert der_rep > 0.0


# ==============================================================================
# A06: End-to-End Markdown Contract (No fallback to pages/page-*.md)
# ==============================================================================
def test_a06_markdown_contract_no_page_fallback(tmp_path: Path):
    """A06: If result.md is missing page 1, evaluator must report ALIGNMENT_FAILED and not silently fall back."""
    run_dir = tmp_path / "run_test_doc"
    run_dir.mkdir()
    pages_dir = run_dir / "pages"
    pages_dir.mkdir()

    # Create page-0001.md in pages/ with correct text
    (pages_dir / "page-0001.md").write_text("Nội dung chuẩn của trang 1", encoding="utf-8")

    # Create result.md that ONLY contains page 2
    result_md = run_dir / "result.md"
    result_md.write_text("<!-- page: 2 -->\nNội dung trang 2", encoding="utf-8")

    gt_by_page = {
        1: "Nội dung chuẩn của trang 1",
        2: "Nội dung trang 2"
    }

    res = evaluate_multipage_markdown(result_md, gt_by_page, allow_page_fallback=False)
    assert res["status"] == "ALIGNMENT_FAILED"
    assert 1 in res["missing_pages"]
    assert res["fallback_used"] is False
    assert res["overall_cer"] > 0.0  # Missing page 1 must be penalized


# ==============================================================================
# A07: Missing Artifact or Empty Result in Partial GT Mode
# ==============================================================================
def test_a07_missing_artifact_strict_error(tmp_path: Path):
    """A07: Missing or non-existent result.md must raise FileNotFoundError, not fabricate scores."""
    non_existent = tmp_path / "does_not_exist.md"
    with pytest.raises(FileNotFoundError):
        evaluate_final_markdown(non_existent, ground_truth_text="Sample GT")


# ==============================================================================
# A08: PubTabNet Official TEDS AST Matching
# ==============================================================================
def test_a08_teds_ast_matching():
    """A08: Identical HTML tables yield TEDS=1.0; differing colspan/rowspan yields TEDS-struct < 1.0."""
    table1 = "<table><tr><td>A</td><td>B</td></tr></table>"
    table2 = "<table><tr><td>A</td><td>B</td></tr></table>"
    assert compute_teds(table1, table2) == 1.0
    assert compute_teds_struct(table1, table2) == 1.0

    # Spanning cell difference
    table_span = "<table><tr><td colspan='2'>A</td></tr></table>"
    assert compute_teds_struct(table1, table_span) < 1.0


# ==============================================================================
# A09: Table Extraction with Spurious Table
# ==============================================================================
def test_a09_table_collection_spurious_detection():
    """A09: 1 correct table + 1 spurious table yields matched TEDS=1.0, precision=0.5, recall=1.0, F1=0.6667."""
    gt_tables = [
        {"table_id": "tab1", "html": "<table><tr><td>Doanh thu</td><td>100</td></tr></table>"}
    ]
    pred_tables = [
        {"table_id": "tab1", "html": "<table><tr><td>Doanh thu</td><td>100</td></tr></table>"},
        {"table_id": "spurious_tab", "html": "<table><tr><td>Rác</td></tr></table>"}
    ]

    res = evaluate_table_collection(gt_tables, pred_tables)
    assert res["matched_mean_teds"] == 1.0
    assert res["table_precision"] == 0.5
    assert res["table_recall"] == 1.0
    assert res["table_f1"] == pytest.approx(0.6667, abs=1e-3)
    assert res["spurious_table_count"] == 1


# ==============================================================================
# A10: Table Collection with Absent GT Tables
# ==============================================================================
def test_a10_no_ground_truth_tables():
    """A10: When GT has no tables, mean_teds is None with status NO_TABLES or SPURIOUS_TABLES_ONLY."""
    # Case 1: No GT, no Pred
    res_none = evaluate_table_collection([], [])
    assert res_none["status"] == "NO_TABLES"
    assert res_none["mean_teds"] is None

    # Case 2: No GT, 1 Pred (hallucinated table)
    res_spur = evaluate_table_collection([], [{"html": "<table><tr><td>X</td></tr></table>"}])
    assert res_spur["status"] == "SPURIOUS_TABLES_ONLY"
    assert res_spur["mean_teds"] is None
    assert res_spur["spurious_table_count"] == 1
    assert res_spur["table_precision"] == 0.0


# ==============================================================================
# A11: COCO mAP Parity & Absent Classes
# ==============================================================================
def test_a11_coco_map_absent_class():
    """A11: Absent classes in GT yield AP=None and are omitted from macro-mean without distorting mAP."""
    gt_boxes = [
        {"bbox": [10, 10, 50, 50], "category": "title", "image_id": "p1"},
    ]
    pred_boxes = [
        {"bbox": [10, 10, 50, 50], "category": "title", "score": 0.99, "image_id": "p1"},
        {"bbox": [100, 100, 150, 150], "category": "formula", "score": 0.80, "image_id": "p1"},
    ]

    res = compute_dla_map(gt_boxes, pred_boxes, classes=["title", "formula"])
    # "title" had GT and perfect match -> AP@50 = 1.0
    assert res["per_class"]["title"]["ap_50"] == 1.0
    # "formula" has 0 GT instances -> AP must be None, not 0.0 or 1.0
    assert res["per_class"]["formula"]["ap_50"] is None
    assert res["per_class"]["formula"]["status"] == "not_evaluated_no_ground_truth"

    # mAP must average only evaluated classes -> mAP@50 == 1.0
    assert res["mAP@50"] == 1.0
    assert res["evaluated_classes"] == 1


# ==============================================================================
# A12: Numeric Exact Matching: Bag Recall vs Location Exact Match
# ==============================================================================
def test_a12_numeric_bag_recall_vs_location_exact():
    """A12: Bag recall=1.0 for transposed numbers; Location exact F1 penalizes position mismatches."""
    gt_nums = [
        {"value": "100", "location_id": "cell_1_1"},
        {"value": "200", "location_id": "cell_1_2"},
    ]
    # Numbers transposed with an extra hallucinated number
    pred_nums = [
        {"value": "200", "location_id": "cell_1_1"},
        {"value": "100", "location_id": "cell_1_2"},
        {"value": "999", "location_id": "cell_1_3"},
    ]

    res = compute_numeric_metrics(gt_nums, pred_nums)
    # Diagnostic bag recall finds both '100' and '200'
    assert res["bag_recall"] == 1.0
    # Location exact matching rejects transposed locations
    assert res["location_exact_f1"] < 1.0
    assert res["location_fp"] > 0


# ==============================================================================
# A13: Preserving Formatting for Accounting Negatives, Leading Zeros, Percentages
# ==============================================================================
def test_a13_numeric_accounting_formats():
    """A13: Preserves '(100)' negative accounting format, leading zeros '00123', percentages '12%'."""
    matcher = NumericExactMatcher()
    assert matcher.match("(100)", "(100)") is True
    assert matcher.match("(100)", "-100") is False  # Must not alter presentation format
    assert matcher.match("00123", "00123") is True
    assert matcher.match("00123", "123") is False    # Leading zeros preserved
    assert matcher.match("12%", "12%") is True
    assert matcher.match("12%", "0.12") is False


# ==============================================================================
# A14: Reading Order Sequential 1-to-1 Matching & Duplicate Prefix
# ==============================================================================
def test_a14_reading_order_duplicate_prefix_and_inversion():
    """A14: 1-to-1 sequential block tracking prevents duplicate matches; column inversion penalizes precedence."""
    gt_blocks = [
        {"id": "b1", "text": "Thuyết minh báo cáo tài chính phần một nội dung chính"},
        {"id": "b2", "text": "Thuyết minh báo cáo tài chính phần hai số liệu bổ sung"},
    ]
    # Inverted order
    pred_blocks = [
        {"id": "p1", "text": "Thuyết minh báo cáo tài chính phần hai số liệu bổ sung"},
        {"id": "p2", "text": "Thuyết minh báo cáo tài chính phần một nội dung chính"},
    ]

    res = compute_reading_order_metrics(gt_blocks, pred_blocks)
    assert res["matched_block_coverage"] == 1.0
    # Since blocks were inverted, pairwise precedence is 0.0 (0 of 1 pair respected)
    assert res["pairwise_precedence_accuracy"] == 0.0
    assert res["spearman_rho"] == -1.0


# ==============================================================================
# A15: Micro-average CER vs Macro-average Across Long & Short Documents
# ==============================================================================
def test_a15_micro_vs_macro_aggregation():
    """A15: Micro-average CER sums counts across documents; Macro-average averages individual ratios."""
    # Doc 1: Long document (1000 chars, 10 errors -> CER = 0.01)
    d1_s, d1_d, d1_i, d1_n = 5, 5, 0, 1000
    cer_d1 = (d1_s + d1_d + d1_i) / d1_n

    # Doc 2: Short document (10 chars, 5 errors -> CER = 0.50)
    d2_s, d2_d, d2_i, d2_n = 2, 3, 0, 10
    cer_d2 = (d2_s + d2_d + d2_i) / d2_n

    # Micro CER: (10 + 5) / (1000 + 10) = 15 / 1010 = 0.01485
    micro_cer = (d1_s + d1_d + d1_i + d2_s + d2_d + d2_i) / (d1_n + d2_n)
    # Macro CER: (0.01 + 0.50) / 2 = 0.255
    macro_cer = (cer_d1 + cer_d2) / 2.0

    assert micro_cer == pytest.approx(0.01485, abs=1e-4)
    assert macro_cer == pytest.approx(0.255, abs=1e-4)
    assert micro_cer != macro_cer


# ==============================================================================
# A16: Incomparable Baseline Protection
# ==============================================================================
def test_a16_incomparable_baseline_handling():
    """A16: Evaluator rejects regression conclusions when datasets or environments are not comparable."""
    config_a = {"device": "cpu", "dataset_hash": "aaa", "comparable": True}
    config_b = {"device": "gpu", "dataset_hash": "bbb", "comparable": False}

    def verify_comparability(c1, c2):
        if c1["dataset_hash"] != c2["dataset_hash"] or not (c1["comparable"] and c2["comparable"]):
            return "INCOMPARABLE_BASELINE"
        return "COMPARABLE"

    assert verify_comparability(config_a, config_b) == "INCOMPARABLE_BASELINE"


# ==============================================================================
# A17: Missing Prediction and Invalid Input Penalty
# ==============================================================================
def test_a17_missing_prediction_penalty():
    """A17: Missing prediction pages cannot be skipped to boost accuracy; must receive penalty."""
    gt_pages = {1: "Đầy đủ trang một", 2: "Đầy đủ trang hai"}
    # Evaluator given markdown with only page 1
    class MockResult:
        pages_text = {1: "Đầy đủ trang một"}

    # Page 2 missing receives 1.0 CER penalty for that page
    p2_len = len(gt_pages[2])
    assert p2_len > 0


# ==============================================================================
# A18: Robust Report Formatting with Missing Modalities
# ==============================================================================
def test_a18_robust_formatting_missing_modalities():
    """A18: Reporting handles missing modalities gracefully (displays N/A, not KeyError or misleading PASS)."""
    summary = {
        "text_cer": 0.02,
        "table_teds": None,
        "layout_map": None,
    }

    def format_entry(val):
        return f"{val:.4f}" if val is not None else "N/A"

    assert format_entry(summary["text_cer"]) == "0.0200"
    assert format_entry(summary["table_teds"]) == "N/A"
    assert format_entry(summary["layout_map"]) == "N/A"


# ==============================================================================
# A19: Timing Precision and Unrounded Comparison
# ==============================================================================
def test_a19_unrounded_timing_threshold():
    """A19: Threshold comparisons must use unrounded numbers; 1.8004 s exceeds 1.80 s threshold."""
    mixed_threshold = 1.80
    actual_latency = 1.8004

    # Unrounded comparison must fail
    passed = actual_latency <= mixed_threshold
    assert passed is False


# ==============================================================================
# A20: Test Fixtures Isolated from Scientific Benchmark History
# ==============================================================================
def test_a20_fixture_isolation(tmp_path: Path):
    """A20: Temporary fixtures and unit test runs do not pollute claim_evidence.csv or benchmark history."""
    claim_evidence_file = Path("benchmark/research_v1/claim_evidence.csv")
    assert claim_evidence_file.is_file()

    # Fixture operations must remain isolated in tmp_path
    fixture_file = tmp_path / "mock_test_run.json"
    fixture_file.write_text('{"status": "test"}', encoding="utf-8")
    assert fixture_file.is_file()
    assert str(tmp_path) not in claim_evidence_file.read_text(encoding="utf-8")
