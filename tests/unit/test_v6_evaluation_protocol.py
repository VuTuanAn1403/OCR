"""Proposal 9.1/9.2: ground truth is matched per document, missing output is
scored as maximum error, and pages outside the run are NOT_EVALUATED."""
import json
import pytest
from pathlib import Path

from benchmark.evaluate import evaluate_document, ground_truth_pages


def _gt(tmp_path, files):
    gt = tmp_path / "gt"
    gt.mkdir()
    for name, text in files.items():
        (gt / name).write_text(text, encoding="utf-8")
    return gt


def _prediction(tmp_path, doc_id, pages, selected=None):
    doc = tmp_path / "out" / doc_id
    (doc / "pages").mkdir(parents=True)
    for page, text in pages.items():
        (doc / "pages" / f"page-{page:04d}.md").write_text(text, encoding="utf-8")
    if selected is not None:
        (doc / "manifest.json").write_text(json.dumps({"selected_pages": selected}), encoding="utf-8")
    return doc


def test_ground_truth_of_another_document_is_not_applied(tmp_path):
    gt = _gt(tmp_path, {"clw_page_0001.txt": "a", "page_0002.txt": "b", "notes.txt": "x"})
    assert set(ground_truth_pages(gt, "CLW_Baocaothuongnien_2020")) == {1, 2}
    assert set(ground_truth_pages(gt, "ACC_Baocaothuongnien_2025")) == {2}
    report = evaluate_document(_prediction(tmp_path, "ACC_Baocaothuongnien_2025", {1: "unrelated"}), gt)
    assert report.evaluation_status == "MEASURED" and set(report.page_reports) == {2}


def test_missing_output_is_maximum_error_not_skipped(tmp_path):
    gt = _gt(tmp_path, {"clw_page_0001.txt": "Doanh thu tăng", "clw_page_0002.txt": "Lợi nhuận giảm mạnh"})
    doc = _prediction(tmp_path, "CLW_report", {1: "Doanh thu tăng"}, selected=[1, 2])
    report = evaluate_document(doc, gt)
    missing = report.page_reports[2]
    assert missing.status == "MISSING_OUTPUT"
    assert missing.cer == 1.0 and missing.wer == 1.0 and missing.reading_order_accuracy == 0.0
    assert report.pages_missing_output == 1 and report.pages_evaluated == 2
    assert report.mean_cer == 0.5
    # Micro CER weights by reference length (9.2 primary aggregate).
    long_ref = len("Lợi nhuận giảm mạnh")
    short_ref = len("Doanh thu tăng")
    assert report.micro_cer == round(long_ref / (long_ref + short_ref), 4)


def test_pages_outside_the_run_are_not_evaluated(tmp_path):
    gt = _gt(tmp_path, {"clw_page_0001.txt": "A", "clw_page_0005.txt": "B"})
    report = evaluate_document(_prediction(tmp_path, "CLW_report", {1: "A"}, selected=[1]), gt)
    assert set(report.page_reports) == {1} and report.pages_not_evaluated == [5]
    assert report.pages_missing_output == 0


def test_no_applicable_ground_truth_is_not_evaluated(tmp_path):
    gt = _gt(tmp_path, {"clw_page_0001.txt": "A"})
    report = evaluate_document(_prediction(tmp_path, "ACC_report", {1: "A"}), gt)
    assert report.evaluation_status == "NOT_EVALUATED" and report.pages_evaluated == 0
    assert report.micro_cer is None


def test_ground_truth_document_prefix_has_an_identity_boundary(tmp_path):
    gt = _gt(tmp_path, {"clw_page_0001.txt": "A"})
    assert not ground_truth_pages(gt, "CLW2_report")


def test_document_specific_ground_truth_overrides_generic(tmp_path):
    gt = _gt(tmp_path, {"page_0001.txt": "generic", "clw_page_0001.txt": "specific"})
    assert ground_truth_pages(gt, "CLW_report")[1].name == "clw_page_0001.txt"


def test_ambiguous_ground_truth_is_rejected(tmp_path):
    gt = _gt(tmp_path, {"clw_page_1.txt": "A", "clw_page_0001.txt": "B"})
    with pytest.raises(ValueError, match="Ambiguous ground truth"):
        ground_truth_pages(gt, "CLW_report")


def test_empty_selected_page_list_does_not_expand_to_every_gt_page(tmp_path):
    gt = _gt(tmp_path, {"clw_page_0001.txt": "A"})
    report = evaluate_document(_prediction(tmp_path, "CLW_report", {}, selected=[]), gt)
    assert report.evaluation_status == "NOT_EVALUATED"
    assert report.pages_not_evaluated == [1]


@pytest.fixture
def scientific_runner(monkeypatch):
    import scripts.run_scientific_benchmark as runner
    monkeypatch.setattr(runner, "capture_environment_metadata", lambda _: {})
    return runner.evaluate_document_scientific


def test_scientific_runner_uses_selected_universe_and_integer_micro_counts(tmp_path, scientific_runner):
    gt = _gt(tmp_path, {"clw_page_0001.txt": "abcdef", "clw_page_0002.txt": "x", "clw_page_0009.txt": "never run"})
    doc = _prediction(tmp_path, "CLW_report", {1: "abcde"}, selected=[1, 2])
    report = scientific_runner(doc, gt)
    metrics = report["academic_metrics"]
    assert metrics["pages_not_evaluated"] == [9]
    assert metrics["pages_missing_output"] == 1
    assert metrics["counts"]["cer"]["errors"] == 2
    assert metrics["micro_cer"] == round(2 / 7, 6)
    assert report["page_evaluations"][1]["status"] == "MISSING_OUTPUT"


def test_scientific_primary_preserves_whitespace_and_reports_secondary(tmp_path, scientific_runner):
    gt = _gt(tmp_path, {"clw_page_0001.txt": "á b"})
    doc = _prediction(tmp_path, "CLW_report", {1: "# Trang 1\ná  b"}, selected=[1])
    metrics = scientific_runner(doc, gt)["academic_metrics"]
    assert metrics["micro_cer"] == round(1 / 3, 6)
    assert metrics["reading_normalized_v1"]["micro_cer"] == 0.0


def test_der_omits_pages_without_reference_diacritics(tmp_path, scientific_runner):
    gt = _gt(tmp_path, {"clw_page_0001.txt": "á", "clw_page_0002.txt": "a"})
    doc = _prediction(tmp_path, "CLW_report", {1: "á", 2: "ááá"}, selected=[1, 2])
    metrics = scientific_runner(doc, gt)["academic_metrics"]
    assert metrics["micro_der"] == 0.0
    assert metrics["counts"]["der"]["pages_without_denominator"] == 1


def test_primary_final_markdown_cannot_borrow_missing_page(tmp_path, scientific_runner):
    gt = _gt(tmp_path, {"clw_page_0001.txt": "á", "clw_page_0002.txt": "đ"})
    doc = _prediction(tmp_path, "CLW_report", {1: "á", 2: "đ"}, selected=[1, 2])
    (doc / "result.md").write_text("# Trang 2\nđ", encoding="utf-8")
    result = scientific_runner(doc, gt)["final_markdown_protocol"]
    assert result["missing_pages"] == [1]
    assert result["micro_cer"] == 0.5 and result["micro_der"] == 0.5
    assert result["fallback_used"] is False


def test_primary_missing_final_markdown_is_deletions(tmp_path, scientific_runner):
    gt = _gt(tmp_path, {"clw_page_0001.txt": "á"})
    doc = _prediction(tmp_path, "CLW_report", {1: "á"}, selected=[1])
    result = scientific_runner(doc, gt)["final_markdown_protocol"]
    assert result["missing_pages"] == [1] and result["micro_cer"] == 1.0


def test_manifest_document_timing_overrides_legacy_time(tmp_path, scientific_runner):
    doc = _prediction(tmp_path, "CLW_report", {1: "á"}, selected=[1])
    (doc / "quality.json").write_text(json.dumps({"total_time_seconds": 0.01,
                                                  "pages_processed_native": 1}), encoding="utf-8")
    manifest = {"selected_pages": [1], "device": "cpu", "timing": {"document_latency_seconds": 2.0}}
    (doc / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    timing = scientific_runner(doc)["timing_and_throughput"]
    assert timing["wall_clock_seconds"] == 2.0
    assert "export included" in timing["timing_source"]
    assert timing["cpu_latency_compliance"]["is_compliant"] is False


@pytest.mark.parametrize("extra,status", [
    ({"device": "cuda"}, "NOT_EVALUATED_NON_CPU_DEVICE"),
    ({"device": "cpu", "cache": {"pages_from_cache": [1]}}, "NOT_EVALUATED_CACHE_REUSE"),
])
def test_gpu_or_cached_timing_cannot_prove_cpu_requirement(tmp_path, scientific_runner, extra, status):
    doc = _prediction(tmp_path, "CLW_report", {1: "á"}, selected=[1])
    (doc / "manifest.json").write_text(json.dumps({"selected_pages": [1], **extra}), encoding="utf-8")
    (doc / "quality.json").write_text(json.dumps({"total_time_seconds": 0.01,
                                                  "pages_processed_native": 1}), encoding="utf-8")
    compliance = scientific_runner(doc)["timing_and_throughput"]["cpu_latency_compliance"]
    assert compliance["status"] == status and compliance["is_compliant"] is False


def test_table_matching_uses_iou_when_predictions_change_order():
    from benchmark.scientific_evaluation.teds_metric import evaluate_table_collection
    def table(value, bbox, page=1):
        return {"html": f"<table><tr><td>{value}</td></tr></table>", "bbox": bbox, "page": page}
    first, second = table("100", [0, 0, 10, 10]), table("200", [0, 20, 10, 30])
    report = evaluate_table_collection([first, second], [second, first])
    assert report["mean_teds"] == 1.0 and report["table_f1"] == 1.0
    wrong_page = evaluate_table_collection([first], [table("100", [0, 0, 10, 10], page=2)])
    assert wrong_page["mean_teds"] == 0.0 and wrong_page["missing_table_count"] == 1
    assert wrong_page["spurious_table_count"] == 1


def test_matching_table_id_cannot_override_disjoint_boxes():
    from benchmark.scientific_evaluation.teds_metric import evaluate_table_collection
    reference = {"table_id": "t1", "bbox": [0, 0, 10, 10], "html": "<table><tr><td>A</td></tr></table>"}
    prediction = {**reference, "bbox": [30, 30, 40, 40]}
    assert evaluate_table_collection([reference], [prediction])["matched_tables"] == 0


def test_numeric_missing_location_does_not_match_everywhere():
    from benchmark.scientific_evaluation.numeric_metric import evaluate_numeric_exact_matching
    result = evaluate_numeric_exact_matching([{"value": "100", "location_id": None}],
                                            [{"value": "100", "location_id": "cell-1"}])
    assert result["true_positives"] == 0 and result["numeric_errors"] == 1
    assert result["reference_items_without_location"] == 1


def test_numeric_location_cannot_cross_pages_and_text_regions_use_iou():
    from benchmark.scientific_evaluation.numeric_metric import evaluate_numeric_exact_matching
    reference = {"value": "100", "location_id": "b1", "page": 1, "bbox": [0, 0, 10, 10]}
    assert evaluate_numeric_exact_matching([reference], [{**reference, "page": 2}])["true_positives"] == 0
    assert evaluate_numeric_exact_matching([reference], [{**reference, "location_id": "renamed"}])["true_positives"] == 1


def test_numeric_tokens_preserve_extended_financial_formats():
    from benchmark.scientific_evaluation.numeric_metric import extract_numeric_tokens
    tokens = extract_numeric_tokens("−5 USD; +3,2; 1 234 triệu đồng; 12,5 %; 626/QĐ-CTN; 31/12/2025")
    assert [token["raw"] for token in tokens] == ["−5 USD", "+3,2", "1 234 triệu đồng",
                                                "12,5 %", "626/QĐ-CTN", "31/12/2025"]


def test_perf_compliance_uses_unrounded_cpu_measurement():
    from benchmark.perf.run_perf import summarize_pages
    page = {"category": "native", "page_type": "NATIVE_TEXT", "seconds": 0.15001,
            "stages": {}, "from_cache": False, "docling_called": False}
    cpu = summarize_pages([page], 120)["categories"]["native"]
    gpu = summarize_pages([page], 120, device="cuda")["categories"]["native"]
    assert cpu["latency_seconds"]["p50"] == 0.15 and cpu["meets_cpu_p50_limit"] is False
    assert gpu["meets_cpu_p50_limit"] is None


def test_unknown_hardware_and_changed_workload_are_not_comparable():
    from benchmark.perf.run_perf import compare_with_previous
    empty = {"page_latency": {"categories": {}}}
    assert compare_with_previous(empty, empty)["same_hardware"] is False
    report = {"run_manifest": {"hardware": {"processor": "x"}}, "device": "cpu",
              "pages": [{"document_id": "a", "page": 1, "page_type": "MIXED"}],
              "page_latency": {"categories": {}}}
    changed = {**report, "pages": [{"document_id": "a", "page": 2, "page_type": "MIXED"}]}
    result = compare_with_previous(report, changed)
    assert result["comparable"] is False and result["mismatches"] == ["page_workload"]


def test_standard_coco_gt_uses_category_ids_xywh_and_selected_pages(tmp_path, scientific_runner):
    doc = _prediction(tmp_path, "CLW_report", {1: "A"}, selected=[1])
    page = {"page_num": 1, "blocks": [{"bbox": [10, 20, 40, 60], "block_type": "text"}]}
    (doc / "pages" / "page-0001.json").write_text(json.dumps(page), encoding="utf-8")
    coco = tmp_path / "layout.json"
    coco.write_text(json.dumps({
        "categories": [{"id": 7, "name": "text"}],
        "images": [{"id": 11, "file_name": "CLW_report_p1.png"},
                   {"id": 12, "file_name": "CLW_report_p2.png"},
                   {"id": 13, "file_name": "OTHER_report_p1.png"}],
        "annotations": [{"image_id": image_id, "category_id": 7, "bbox": [10, 20, 30, 40]}
                        for image_id in (11, 12, 13)],
    }), encoding="utf-8")
    result = scientific_runner(doc, coco_gt_path=coco)["academic_metrics"]["dla_coco"]
    assert result["mAP@50"] == pytest.approx(1.0)
    assert result["acceptance"]["per_class"]["Text"]["GT"] == 1
    assert result["eligible_for_v6_acceptance"] is False


def test_dirty_run_without_gt_is_diagnostic_not_accepted():
    from benchmark.perf.run_perf import protocol_readiness
    result = protocol_readiness({"device": "cpu", "profile": "balanced", "repeats": [{}, {}, {}],
                                 "run_manifest": {"git": {"dirty": True, "commit": "abc"}},
                                 "documents": [{"quality": None}]})
    assert result["run_classification"] == "EXPLORATORY_DIRTY_WORKTREE"
    assert result["acceptance_status"] == "NOT_EVALUATED"
    assert result["checks"]["quality_on_same_outputs"] is False
    assert any("ADJ-05" in requirement for requirement in result["pending_requirements"])


def test_perf_quality_evaluation_is_outside_extraction_wall_clock(tmp_path, monkeypatch):
    import argparse
    from types import SimpleNamespace
    import benchmark.perf.run_perf as perf
    clock = [0.0]
    config_path, input_pdf = tmp_path / "profile.yaml", tmp_path / "input.pdf"
    config_path.write_text("balanced: {}", encoding="utf-8")
    input_pdf.write_bytes(b"fake-pdf-for-hash")
    class Converter:
        def __init__(self, config):
            self.config_path = config_path
        def resolve_profile(self, profile, device):
            return {"device": "cpu"}
        def execute(self, **kwargs):
            clock[0] += 2.0
            doc_dir = Path(kwargs["output_dir"]) / "doc"
            (doc_dir / "pages").mkdir(parents=True)
            quality = SimpleNamespace(page_type="NATIVE_TEXT", time_taken_seconds=1.0,
                                      stage_seconds={}, from_cache=False, errors=0, content_status="EXTRACTED")
            page = SimpleNamespace(page_num=1, quality=quality, metadata={})
            return SimpleNamespace(document_id="doc", file_path=str(input_pdf), pages=[page],
                                   timing={"startup_seconds": 0.2, "document_latency_seconds": 2.0})
    class Recorder:
        def __init__(self, *args, **kwargs):
            self.data = {"documents": [], "cache": {}, "git": {"dirty": True}}
        def add_document(self, doc):
            self.data["documents"].append({})
        def write(self, path):
            return path
    class Memory:
        peak_bytes = 1000
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
    def evaluate(*args):
        clock[0] += 100.0
        return {"academic_metrics": {"evaluated_pages": 1}}
    monkeypatch.setattr(perf, "ConvertDocumentUseCase", Converter)
    monkeypatch.setattr(perf, "RunRecorder", Recorder)
    monkeypatch.setattr(perf, "PeakMemorySampler", Memory)
    monkeypatch.setattr(perf.time, "perf_counter", lambda: clock[0])
    monkeypatch.setattr(perf, "_evaluate", evaluate)
    monkeypatch.setattr(perf, "_reset_peak_vram", lambda: None)
    monkeypatch.setattr(perf, "_peak_vram_mb", lambda: None)
    args = argparse.Namespace(config=str(config_path), profile="balanced", device="cpu", pages="1",
                              output=str(tmp_path / "out"), repeat=2, pdf=[str(input_pdf)],
                              assets="none", ground_truth="gt", compare=None)
    report = perf.run(args)
    assert [repeat["wall_seconds"] for repeat in report["repeats"]] == [2.0, 2.0]
    assert report["documents"][0]["quality"]["academic_metrics"]["evaluated_pages"] == 1
