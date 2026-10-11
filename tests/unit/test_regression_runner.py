import json
from pathlib import Path
from scripts.run_regression import (
    compute_numeric_accuracy,
    evaluate_page_pair,
    run_regression_suite,
)

def test_compute_numeric_accuracy():
    gt = "Doanh thu 120.000.000 VND, lợi nhuận 15%, mã số 2020."
    pred_exact = "Doanh thu 120.000.000 VND, lợi nhuận 15%, mã số 2020."
    assert compute_numeric_accuracy(gt, pred_exact) == 1.0

    pred_wrong = "Doanh thu 120.000.001 VND, lợi nhuận 16%, mã số 2020."
    # 1 of 3 numbers matched ("2020")
    assert round(compute_numeric_accuracy(gt, pred_wrong), 2) == 0.33

    gt_no_num = "Không có số nào ở đây"
    assert compute_numeric_accuracy(gt_no_num, "Cũng không có số") == 1.0


def test_evaluate_page_pair():
    gt = "Báo cáo tài chính quý 4 năm 2020"
    pred = "Báo cáo tài chính quý 4 năm 2020"
    res = evaluate_page_pair(gt, pred)
    assert res["cer"] == 0.0
    assert res["wer"] == 0.0
    assert res["der"] == 0.0
    assert res["numeric_accuracy"] == 1.0


def test_run_regression_suite_synthetic(tmp_path):
    gt_dir = tmp_path / "gt"
    gt_dir.mkdir()
    (gt_dir / "doc1.txt").write_text("Doanh thu năm 2020 là 500 tỷ", encoding="utf-8")

    pred_dir = tmp_path / "pred"
    pred_dir.mkdir()
    (pred_dir / "doc1.txt").write_text("Doanh thu năm 2020 là 500 tỷ", encoding="utf-8")

    hist_file = tmp_path / "history.json"

    summary, has_regression = run_regression_suite(
        gt_dir=gt_dir,
        predictions_dir=pred_dir,
        history_file=hist_file,
        alert_threshold=0.02,
        fail_on_regression=False,
        save_history=True,
    )

    assert not has_regression
    assert summary["aggregate"]["cer"] == 0.0
    assert summary["aggregate"]["numeric_accuracy"] == 1.0
    assert hist_file.exists()


def test_run_regression_suite_no_ground_truth(tmp_path):
    gt_dir = tmp_path / "empty_gt"
    gt_dir.mkdir()
    pred_dir = tmp_path / "pred"
    pred_dir.mkdir()
    hist_file = tmp_path / "history.json"

    summary, has_regression = run_regression_suite(
        gt_dir=gt_dir,
        predictions_dir=pred_dir,
        history_file=hist_file,
    )
    assert not has_regression
    assert summary["status"] == "NO_GROUND_TRUTH"
    assert summary["evaluated_count"] == 0
    assert not hist_file.exists()


def test_find_matching_prediction_real_export_structure(tmp_path):
    from scripts.run_regression import find_matching_prediction

    pred_dir = tmp_path / "pred"
    doc_pages_dir = pred_dir / "financial_doc" / "pages"
    doc_pages_dir.mkdir(parents=True)
    (doc_pages_dir / "page-0001.md").write_text("Nội dung trang 1 thực tế", encoding="utf-8")

    matched = find_matching_prediction("financial_doc_page_0001", pred_dir)
    assert matched == "Nội dung trang 1 thực tế"

    matched_dash = find_matching_prediction("financial_doc_page-0001", pred_dir)
    assert matched_dash == "Nội dung trang 1 thực tế"


def test_evaluate_page_pair_no_truncation():
    gt = "abc"
    pred_garbage = "abc" + ("x" * 6000)
    res = evaluate_page_pair(gt, pred_garbage)
    # 6000 insertions on 3 chars -> CER = 6000 / 3 = 2000.0
    assert res["cer"] == 2000.0
    assert res["pred_chars"] == 6003


def test_baseline_isolated_from_regressions(tmp_path):
    gt_dir = tmp_path / "gt"
    gt_dir.mkdir()
    (gt_dir / "doc1.txt").write_text("Hello World 2026", encoding="utf-8")

    pred_dir = tmp_path / "pred"
    pred_dir.mkdir()
    (pred_dir / "doc1.txt").write_text("Hello World 2026", encoding="utf-8")

    hist_file = tmp_path / "history.json"
    baseline_file = tmp_path / "baseline.json"

    # 1. First run sets baseline
    s1, reg1 = run_regression_suite(
        gt_dir=gt_dir,
        predictions_dir=pred_dir,
        history_file=hist_file,
        baseline_file=baseline_file,
        set_baseline=True,
    )
    assert not reg1
    assert baseline_file.exists()
    b1_data = json.loads(baseline_file.read_text(encoding="utf-8"))
    assert b1_data["aggregate"]["cer"] == 0.0

    # 2. Corrupt prediction -> regression detected
    (pred_dir / "doc1.txt").write_text("Corrupted Text 9999", encoding="utf-8")
    s2, reg2 = run_regression_suite(
        gt_dir=gt_dir,
        predictions_dir=pred_dir,
        history_file=hist_file,
        baseline_file=baseline_file,
        alert_threshold=0.005,
        fail_on_regression=False,
    )
    assert reg2

    # Baseline file must NOT have been updated with the failed run
    b2_data = json.loads(baseline_file.read_text(encoding="utf-8"))
    assert b2_data["aggregate"]["cer"] == 0.0

    # 3. Third run with same corrupted text must STILL report regression against original baseline
    s3, reg3 = run_regression_suite(
        gt_dir=gt_dir,
        predictions_dir=pred_dir,
        history_file=hist_file,
        baseline_file=baseline_file,
        alert_threshold=0.005,
        fail_on_regression=False,
    )
    assert reg3

