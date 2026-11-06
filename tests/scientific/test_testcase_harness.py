"""Counterexamples for the diagnostic entry point shipped in Test case/."""
import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def harness(monkeypatch):
    path = Path(__file__).resolve().parents[2] / "Test case" / "scientific_benchmark_harness.py"
    spec = importlib.util.spec_from_file_location("testcase_harness", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr("scripts.run_scientific_benchmark.capture_environment_metadata", lambda _: {})
    return module


def _fixture(tmp_path, *, missing_final=False, gt_name="DOC_page_0001.txt"):
    gt = tmp_path / "gt"
    gt.mkdir()
    (gt / gt_name).write_text("á", encoding="utf-8")
    doc = tmp_path / "DOC"
    (doc / "pages").mkdir(parents=True)
    (doc / "pages" / "page-0001.md").write_text("# Trang 1\ná", encoding="utf-8")
    (doc / "manifest.json").write_text(json.dumps({"total_pages": 2, "selected_pages": [1, 2]}), encoding="utf-8")
    if not missing_final:
        (doc / "result.md").write_text("# Trang 1\ná", encoding="utf-8")
    return doc, gt


def test_empty_reference_and_no_diacritics_remain_undefined(harness):
    result = harness.ScientificBenchmarkEvaluator().evaluate_text_pair("", "á")
    assert result["cer"] is None and result["wer"] is None and result["der_vn"] is None
    assert result["insertions"] == 1 and result["counts"]["der"]["diacritic_errors"] == 1


def test_pair_metrics_use_one_normalization_policy(harness):
    result = harness.ScientificBenchmarkEvaluator("reading_normalized_v1").evaluate_text_pair("  á\n b", "á b")
    assert result["cer"] == result["wer"] == result["der_vn"] == 0.0
    assert {item["policy"] for item in result["counts"].values()} == {"reading_normalized_v1"}


def test_real_cli_writes_evidence_and_exposes_partial_coverage(harness, tmp_path):
    doc, gt = _fixture(tmp_path)
    output = tmp_path / "reports" / "diagnostic.md"
    assert harness.main(["--pred", str(doc), "--gt", str(gt), "--report", str(output)]) == 0
    result = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))
    summary = result["summary"]
    assert summary["micro_cer"] == 0.0
    assert summary["coverage"]["annotation_fraction"] == 0.5
    assert summary["coverage"]["requested_pages_without_gt"] == [2]
    assert summary["table_metrics"]["status"] == "NOT_EVALUATED"
    assert summary["sota_comparison_status"] == "NOT_EVALUATED"
    assert result["canonical_report"]["final_markdown_protocol"]["counts"]["cer"]["reference_length"] == 1
    assert "CHƯA ĐỐI CHUẨN" in output.read_text(encoding="utf-8")


def test_missing_final_cannot_borrow_correct_page_output(harness, tmp_path):
    doc, gt = _fixture(tmp_path, missing_final=True)
    result = harness.ScientificBenchmarkEvaluator().evaluate_document(doc, gt)
    assert result["summary"]["micro_cer"] == 1.0
    assert result["summary"]["coverage"]["missing_final_markdown_pages"] == [1]
    assert result["canonical_report"]["academic_metrics"]["micro_cer"] == 0.0


def test_missing_page_is_counted_in_final_and_per_page_metrics(harness, tmp_path):
    doc, gt = _fixture(tmp_path)
    (gt / "DOC_page_0002.txt").write_text("đđđ", encoding="utf-8")
    result = harness.ScientificBenchmarkEvaluator().evaluate_document(doc, gt)
    assert result["summary"]["micro_cer"] == 0.75
    assert result["summary"]["coverage"]["missing_per_page_outputs"] == [2]
    assert result["summary"]["counts"]["cer"]["errors"] == 3


def test_no_applicable_gt_is_not_a_successful_benchmark(harness, tmp_path):
    doc, gt = _fixture(tmp_path, gt_name="OTHER_page_0001.txt")
    output = tmp_path / "diagnostic.md"
    assert harness.main(["--pred", str(doc), "--gt", str(gt), "--report", str(output)]) == 2
    summary = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))["summary"]
    assert summary["evaluation_status"] == "NOT_EVALUATED" and summary["micro_cer"] is None
    assert "CHƯA ĐÁNH GIÁ" in output.read_text(encoding="utf-8")


def test_none_metrics_never_receive_perfect_diagnosis(harness, tmp_path):
    content = harness.ScientificBenchmarkEvaluator().generate_markdown_report(
        {"mean_cer": None, "mean_wer": None, "mean_der_vn": None}, tmp_path / "report.md")
    assert "NOT_EVALUATED" in content and "CHƯA ĐÁNH GIÁ" in content
    assert "ĐẠT CHUẨN XUẤT SẮC" not in content


def test_self_test_writes_no_template_or_fake_report(harness, monkeypatch):
    def forbidden_write(*args, **kwargs):
        raise AssertionError("self-test must not write user files")
    monkeypatch.setattr(Path, "write_text", forbidden_write)
    assert harness.run_self_diagnostic_suite() == 0


@pytest.mark.parametrize("args", [[], ["--pred", "output"], ["--gt", "gt"],
                                  ["--run-self-test", "--pred", "output"]])
def test_incomplete_or_conflicting_cli_rejected(harness, args):
    with pytest.raises(SystemExit) as exc:
        harness.main(args)
    assert exc.value.code == 2


def test_invalid_batch_directory_rejected(harness, tmp_path):
    (tmp_path / "gt").mkdir()
    with pytest.raises(ValueError, match="document artifacts"):
        harness.ScientificBenchmarkEvaluator().evaluate_document(tmp_path, tmp_path / "gt")


def test_result_md_input_uses_parent_document_identity(harness, tmp_path):
    doc, gt = _fixture(tmp_path)
    result = harness.ScientificBenchmarkEvaluator().evaluate_document(doc / "result.md", gt)
    assert result["summary"]["document_id"] == "DOC" and result["summary"]["micro_cer"] == 0.0


def test_entirely_empty_gt_does_not_pass_accuracy_benchmark(harness, tmp_path):
    doc, gt = _fixture(tmp_path)
    (gt / "DOC_page_0001.txt").write_text("", encoding="utf-8")
    result = harness.ScientificBenchmarkEvaluator().evaluate_document(doc, gt)
    assert result["summary"]["evaluation_status"] == "NOT_EVALUATED"
    assert result["summary"]["evaluation_reason"] == "ZERO_REFERENCE_CHARACTERS"


def test_structured_cli_scores_transposed_cells_missing_page_and_partial_order(harness, tmp_path):
    doc, gt = _fixture(tmp_path)
    pdf_hash = "a" * 64
    scope = {"coordinate_space": "pdf_points_top_left", "transforms": []}
    bbox = [0, 20, 20, 40]
    nodes = [{"id": "a", "text": "1", "bbox": [0, 0, 5, 5]},
             {"id": "b", "text": "2", "bbox": [0, 6, 5, 11]},
             {"id": "c", "text": "3", "bbox": [8, 0, 13, 5]}]
    order = {"nodes": nodes, "before_pairs": [["a", "b"]]}
    table = {"id": "t", "bbox": bbox, "html": "<table><tr><td>020</td><td>01</td></tr></table>",
             "numeric_cells": [{"row": 0, "col": 0, "value": "020"}, {"row": 0, "col": 1, "value": "01"}]}
    label = {"schema_version": "structured-page-gt-v1", "document_id": "DOC", "pdf_sha256": pdf_hash,
             "total_pages": 2, "pages": [
                 {"page": 1, **scope, "tables": [table], "numeric_cells_complete": True, "reading_order": order},
                 {"page": 2, **scope, "tables": [], "numeric_cells_complete": True, "reading_order": order},
             ]}
    gt_path = gt / "structure.json"
    gt_path.write_text(json.dumps(label), encoding="utf-8")

    def provenance(value):
        return {"text_raw": value, "text_corrected": value, "correction_source": None,
                "source": "fixture", "device": "fixture", "confidence": None, "confidence_source": "unavailable"}

    table_id = f"{pdf_hash[:16]}:p0001:t0001"
    items = [{"kind": "b", "id": f"{pdf_hash[:16]}:p0001:b{index:04d}", "bbox": node["bbox"],
              **provenance(node["text"])} for index, node in enumerate([nodes[2], *nodes[:2]], 1)]
    items.append({"kind": "t", "id": table_id, "bbox": bbox, **provenance("01 | 020"), "cells": [
        {"row": 0, "col": col, "row_span": 1, "col_span": 1, "bbox": bbox, "bbox_source": "table_fallback",
         "spans": [{"page": 1, "bbox": bbox, "block_ids": [table_id]}], **provenance(value)}
        for col, value in enumerate(["01", "020"])
    ]})
    extraction = {"schema_version": "extraction-v1", "doc_id": "DOC", "doc_sha16": pdf_hash[:16],
                  "pipeline_version": "fixture", "profile": "unified_gpu_full_ocr", "total_pages": 2,
                  "pages": [{"page": 1, **scope, "width": 100, "height": 100, "page_type": "fixture", "items": items}]}
    (doc / "extraction.json").write_text(json.dumps(extraction), encoding="utf-8")
    output = tmp_path / "diagnostic.md"
    assert harness.main(["--pred", str(doc), "--gt", str(gt), "--structured-gt", str(gt_path),
                         "--report", str(output)]) == 0
    report = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))
    structured = report["canonical_report"]["structured_scoreboard"]
    assert structured["eligible_for_quality_acceptance"] is False
    assert structured["tables"]["mean_teds_struct"] == 1.0
    assert structured["numeric_cells"]["bag_recall"] == 1.0
    assert structured["numeric_cells"]["location_fn"] == structured["numeric_cells"]["location_fp"] == 2
    assert structured["reading_order"]["penalized_precedence"] == 0.5
    assert structured["coverage"]["reading_order"]["missing_prediction_pages"] == [2]
    assert structured["pages"][1]["tables"]["table_f1"] is None
    assert "0.500000" in output.read_text(encoding="utf-8")

    from ocr_artifacts.hashing import sha256_file

    order["alignment_mode"] = "reviewed_spans"
    gt_path.write_text(json.dumps(label), encoding="utf-8")
    alignment = tmp_path / "reviewed.json"
    alignment.write_text(json.dumps({
        "schema_version": "ocr-reading-order-alignment-v1", "document_id": "DOC", "pdf_sha256": pdf_hash,
        "ground_truth_sha256": sha256_file(gt_path), "extraction_sha256": sha256_file(doc / "extraction.json"),
        "reviewed_by": "fixture", "reviewed_at": "2020-01-01T12:00:00+07:00",
        "reviewed_against_source": True, "intended_partition": "development", "pages": [{"page": 1, "mappings": [
            {"gt_id": node["id"], "reason": "Fixture", "spans": [
                {"prediction_id": item["id"], "start": 0, "end": 1}]}
            for node, item in zip([nodes[2], *nodes[:2]], items)
        ]}],
    }), encoding="utf-8")
    reviewed_output = tmp_path / "reviewed-report.md"
    assert harness.main(["--pred", str(doc), "--gt", str(gt), "--structured-gt", str(gt_path),
                         "--reading-order-alignment", str(alignment), "--report", str(reviewed_output)]) == 0
    reviewed = json.loads(reviewed_output.with_suffix(".json").read_text(encoding="utf-8"))
    reading_order = reviewed["canonical_report"]["structured_scoreboard"]["reading_order"]
    assert reading_order["reviewed_alignment_pages"] == [1] and reading_order["penalized_precedence"] == 0.5

    order["before_pairs"].append(["b", "a"])
    gt_path.write_text(json.dumps(label), encoding="utf-8")
    with pytest.raises(ValueError, match="cycle"):
        harness.ScientificBenchmarkEvaluator().evaluate_document(doc, gt, structured_gt_path=gt_path)


@pytest.mark.parametrize("inside_gt", [False, True])
def test_report_cannot_overwrite_prediction_or_gt(harness, tmp_path, inside_gt):
    doc, gt = _fixture(tmp_path)
    output = gt / "report.md" if inside_gt else doc / "result.md"
    with pytest.raises(SystemExit) as exc:
        harness.main(["--pred", str(doc), "--gt", str(gt), "--report", str(output)])
    assert exc.value.code == 2
    assert (doc / "result.md").read_text(encoding="utf-8") == "# Trang 1\ná"

