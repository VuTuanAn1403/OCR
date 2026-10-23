"""Proposal 9.4 matrix runner: one variable per configuration, every slot
visible, B0 accepted only under the 6.5 conditions at a locked commit,
failed documents counted as MISSING_OUTPUT, counts only from GT."""
from process_test_helpers import historical_profiles
import argparse
import hashlib
import json

import pymupdf
import pytest

from benchmark.scientific_evaluation.matrix_runner import (
    MATRIX, RUN_RECORD_SCHEMA, assemble, b0_conditions, derive_profile, missing_output_records,
    overrides_for, run_configuration,
)
from benchmark.scientific_evaluation.matrix_statistics import CONFIGURATIONS
from src.ocr.application.convert_document import ConvertDocumentUseCase
from src.ocr.collect.catalog import FIELDS

BALANCED_LIKE = {"native_first": True, "render_dpi": 180, "fallback_enabled": False,
                 "fallback_only_on_review": True, "fallback_upscale_dpi": 250,
                 "docling": {"enabled": True, "table_mode": "fast", "formulas": True}}


def test_matrix_declares_every_configuration_with_a_reason_when_not_runnable():
    assert tuple(MATRIX) == CONFIGURATIONS
    for name, spec in MATRIX.items():
        assert spec["status"] in ("RUNNABLE", "NOT_APPLICABLE", "NOT_IMPLEMENTED")
        if spec["status"] != "RUNNABLE":
            assert spec["reason"], name
    assert MATRIX["A1"]["known_confounds"]  # Docling text layer is declared, not hidden


def test_each_ablation_changes_exactly_its_declared_variable():
    a1, _ = overrides_for("A1", BALANCED_LIKE)
    assert derive_profile(BALANCED_LIKE, a1) == {**BALANCED_LIKE, "native_first": False}
    a6, reason = overrides_for("A6", BALANCED_LIKE)
    assert reason is None and a6 == {"fallback_enabled": False, "fallback_only_on_review": False,
                                     "fallback_upscale_dpi": 180}
    v1 = derive_profile(BALANCED_LIKE, overrides_for("V1", BALANCED_LIKE)[0])
    assert v1["docling"] == {"enabled": True, "table_mode": "accurate", "formulas": True}
    assert BALANCED_LIKE["docling"]["table_mode"] == "fast"  # the base profile is not mutated


def test_misspelled_or_missing_override_keys_are_errors():
    with pytest.raises(ValueError, match="not configured"):
        derive_profile({"render_dpi": 180}, {"native_frist": False})
    with pytest.raises(ValueError, match="expects a mapping"):
        derive_profile({"docling": True}, {"docling": {"table_mode": "accurate"}})


def test_configurations_that_would_equal_f_are_not_applicable():
    fast = {"native_first": True, "render_dpi": 150, "fallback_enabled": False, "docling": {"enabled": False}}
    assert overrides_for("A6", fast)[1] and overrides_for("V1", fast)[1]


def test_b0_requires_clean_tree_cpu_and_balanced():
    clean = {"commit": "abc", "dirty": False}
    assert b0_conditions(clean, "cpu", "balanced")["met"]
    assert not b0_conditions({"commit": "abc", "dirty": True}, "cpu", "balanced")["met"]
    assert not b0_conditions(clean, "cuda", "balanced")["met"]
    assert not b0_conditions(clean, "cpu", "fast")["met"]


@pytest.fixture
def workspace(tmp_path):
    pdf = tmp_path / "MAT_report.pdf"
    with pymupdf.open() as document:
        page = document.new_page(width=595, height=842)
        page.insert_text((72, 100), "Doanh thu tang truong manh", fontsize=14)
        page.insert_text((72, 140), "Loi nhuan sau thue 1.234 ty dong", fontsize=14)
        document.save(pdf)
    gt = tmp_path / "gt"
    gt.mkdir()
    (gt / "mat_page_0001.txt").write_text("Doanh thu tang truong manh\nLoi nhuan sau thue 1.234 ty dong",
                                          encoding="utf-8")
    row = {field: "unknown" for field in FIELDS}
    row.update(document_id="MAT_report", relative_path="MAT_report.pdf", company_id="MAT",
               sha256=hashlib.sha256(pdf.read_bytes()).hexdigest(), pages="1", encrypted="False",
               copy_restricted="False", status="OK", error="")
    sources = tmp_path / "sources.csv"
    sources.write_text(",".join(FIELDS) + "\n" + ",".join(row[f] for f in FIELDS) + "\n", encoding="utf-8")
    inventory = {"MAT_report": {"company_id": "MAT", "sha256": row["sha256"]}}
    return pdf, gt, sources, inventory


def _args(tmp_path, pdfs, gt=None, sources=None):
    return argparse.Namespace(pdf=[str(p) for p in pdfs], pages="1", profile="fast", config=None, device="cpu",
                              assets="none", ground_truth=str(gt) if gt else None,
                              sources=str(sources) if sources else None, splits=None,
                              output=str(tmp_path / "matrix"))


GIT = {"commit": "abc", "dirty": True, "uncommitted_diff_sha256": "d"}


def test_runs_record_counts_from_gt_and_keep_unrunnable_slots(tmp_path, workspace):
    pdf, gt, sources, inventory = workspace
    args = _args(tmp_path, [pdf], gt, sources)
    converter = ConvertDocumentUseCase(config_path=historical_profiles())
    f = run_configuration("F", args, converter, GIT, inventory)
    assert f["status"] == "COMPLETED" and f["schema"] == RUN_RECORD_SCHEMA
    assert f["quality_status"] == "COUNTS_RECORDED"
    cer = f["records_by_metric"]["cer"]
    assert [(r["company_id"], r["document_id"], r["page"], r["status"]) for r in cer] == \
        [("MAT", "MAT_report", 1, "MEASURED")]

    a1 = run_configuration("A1", args, converter, GIT, inventory)
    assert a1["status"] == "COMPLETED" and a1["overrides"] == {"native_first": False}
    output = tmp_path / "matrix/A1/output/MAT_report"
    page = json.loads((output / "pages/page-0001.json").read_text(encoding="utf-8"))
    assert page["metadata"]["routing_override"] == "native_first_disabled"
    assert all(b["source"] != "native" for b in page["blocks"])
    assert all(t["engine"] != "vector" for t in page["tables"])
    quality = json.loads((output / "quality.json").read_text(encoding="utf-8"))
    assert quality["pages_processed_native"] == 0 and quality["pages_processed_ocr"] == 1
    assert a1["config_sha256"] != f["config_sha256"]

    for name in ("V1", "A6"):  # fast profile: Docling and re-OCR are already off
        assert run_configuration(name, args, converter, GIT, inventory)["status"] == "NOT_APPLICABLE"
    a2 = run_configuration("A2", args, converter, GIT, inventory)
    assert a2["status"] == "NOT_APPLICABLE" and (tmp_path / "matrix/A2/run_record.json").is_file()


def test_failed_document_contributes_missing_output_records(tmp_path, workspace):
    pdf, gt, sources, inventory = workspace
    absent = tmp_path / "MAT_report_absent" / "MAT_report.pdf"  # same document id, no file
    record = run_configuration("F", _args(tmp_path, [absent], gt, sources), ConvertDocumentUseCase(config_path=historical_profiles()), GIT,
                               inventory)
    assert record["status"] == "FAILED" and record["failed_documents"] == ["MAT_report"]
    assert record["documents"][0]["traceback"]
    (row,) = record["records_by_metric"]["cer"]
    assert row["status"] == "MISSING_OUTPUT" and row["numerator"] == row["denominator"] > 0


def test_missing_output_records_use_reference_lengths(tmp_path):
    gt = tmp_path / "x_page_0002.txt"
    gt.write_text("Tổng cộng", encoding="utf-8")
    records = missing_output_records({2: gt}, "X", "CO")
    assert records["cer"][0]["denominator"] == len("Tổng cộng")
    assert records["der"][0]["status"] == "MISSING_OUTPUT" and records["der"][0]["denominator"] > 0


def test_unverified_company_or_unprefixed_gt_records_no_counts(tmp_path, workspace):
    pdf, gt, sources, inventory = workspace
    record = run_configuration("F", _args(tmp_path, [pdf], gt, sources), ConvertDocumentUseCase(config_path=historical_profiles()), GIT, {})
    assert record["quality_status"] == "NOT_EVALUATED" and "company_id" in record["quality_status_reason"]
    (gt / "mat_page_0001.txt").rename(gt / "page_0001.txt")
    record = run_configuration("F", _args(tmp_path, [pdf], gt, sources), ConvertDocumentUseCase(config_path=historical_profiles()), GIT, inventory)
    assert "document-prefixed" in record["quality_status_reason"] and "records_by_metric" not in record


def _write_record(runs, name, **fields):
    (runs / name).mkdir(parents=True, exist_ok=True)
    record = {"schema": RUN_RECORD_SCHEMA, "configuration": name, "status": "COMPLETED", "git": GIT,
              "profile": "balanced", "source_fingerprint": "s", "inputs": {"pdf": ["a.pdf"], "pages": None},
              **fields}
    (runs / name / "run_record.json").write_text(json.dumps(record), encoding="utf-8")
    return runs / name / "run_record.json"


def test_assemble_keeps_all_slots_and_rejects_unqualified_runs(tmp_path):
    runs = tmp_path / "runs"
    _write_record(runs, "F")
    _write_record(runs, "A2", status="NOT_APPLICABLE")
    _write_record(runs, "A6", source_fingerprint="older-code")
    (runs / "V1").mkdir()
    (runs / "V1" / "run_record.json").write_text("{not json", encoding="utf-8")
    b0 = _write_record(tmp_path / "b0", "B0", git={"commit": "head", "dirty": False},
                       b0_conditions={"met": True})
    protocol = tmp_path / "protocol.json"
    protocol.write_text(json.dumps({"metrics": ["cer"], "b0_commit": "locked"}), encoding="utf-8")
    result = assemble(str(b0), str(runs), str(protocol))
    assert set(result["slots"]) == set(CONFIGURATIONS)
    assert result["slots"]["B0"]["status"] == "NOT_ACCEPTED_AS_B0"  # HEAD is not the locked commit
    assert result["slots"]["A2"]["status"] == "NOT_APPLICABLE"
    assert result["slots"]["A1"]["status"] == "NOT_RUN"
    assert result["slots"]["A6"]["status"] == "INVALID_RECORD" and "more than one variable" in result["slots"]["A6"]["reason"]
    assert result["slots"]["V1"]["status"] == "INVALID_RECORD"
    assert len(result["family"]) == 8
    assert all(c["status"] == "NOT_EVALUATED" for c in result["comparisons"].values())
    assert result["eligible_for_quality_acceptance"] is False
