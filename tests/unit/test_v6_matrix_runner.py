"""Proposal 9.4 matrix runner on the product pipeline (V8-042): one variable per
configuration, every slot visible, B0 accepted only under the 6.5 conditions
at a locked commit, failed documents counted as MISSING_OUTPUT, counts only
from GT. Documents run through a fake `run_document`; the real one launches
`ocr_pipeline.cli.main` (tests/unit/test_product_run.py)."""
import argparse
import hashlib
import json
from pathlib import Path

import pytest

from benchmark import product_run
from benchmark.scientific_evaluation.matrix_runner import (
    MATRIX, RUN_RECORD_SCHEMA, _company_inventory, assemble, b0_conditions, derive_profile, document_ids,
    missing_output_records, normalize_company_id, overrides_for, parse_score_pages, read_source_inventory,
    run_configuration,
)
from benchmark.scientific_evaluation.matrix_statistics import CONFIGURATIONS
from ocr_runtime.pipeline_policy import PROFILE, validate_profile

ROOT = Path(__file__).resolve().parents[2]
V6_LIKE = {"native_first": True, "render_dpi": 180, "fallback_enabled": False,
           "fallback_only_on_review": True, "fallback_upscale_dpi": 250,
           "docling": {"enabled": True, "table_mode": "fast", "formulas": True}}


def _product_profile():
    return product_run.base_profile(ROOT / "config/profiles.yaml")[1]


def test_matrix_declares_every_configuration_with_a_reason_when_not_runnable():
    assert tuple(MATRIX) == CONFIGURATIONS
    for name, spec in MATRIX.items():
        assert spec["status"] in ("RUNNABLE", "NOT_APPLICABLE", "NOT_IMPLEMENTED")
        if spec["status"] != "RUNNABLE":
            assert spec["reason"], name
    assert "native_first=false" in MATRIX["A1"]["reason"]  # retired routing is declared, not hidden


def test_product_ablations_change_only_their_variable_and_stay_valid_product_profiles():
    base = _product_profile()
    a6, reason = overrides_for("A6", base)
    assert reason is None and a6 == {"diacritic_retry": {"enabled": False}, "short_token_retry": {"enabled": False}}
    v1, reason = overrides_for("V1", base)
    assert reason is None and v1 == {"docling": {"table_mode": "accurate"}}
    for overrides in (a6, v1):
        derived = derive_profile(base, overrides)
        validate_profile(derived)  # prepare_backend accepts the derived configuration
        changed = {key for key in derived if derived[key] != base[key]}
        assert changed == set(overrides)
    assert base["docling"]["table_mode"] == "fast"  # the base profile is not mutated


def test_v6_style_regional_retry_keys_are_still_disabled():
    a6, reason = overrides_for("A6", V6_LIKE)
    assert reason is None and a6 == {"fallback_only_on_review": False, "fallback_upscale_dpi": 180}


def test_misspelled_or_missing_override_keys_are_errors():
    with pytest.raises(ValueError, match="not configured"):
        derive_profile({"render_dpi": 180}, {"native_frist": False})
    with pytest.raises(ValueError, match="expects a mapping"):
        derive_profile({"docling": True}, {"docling": {"table_mode": "accurate"}})


def test_configurations_that_would_equal_f_are_not_applicable():
    quiet = {"render_dpi": 150, "fallback_enabled": False, "docling": {"enabled": False}}
    assert overrides_for("A6", quiet)[1] and overrides_for("V1", quiet)[1]
    accurate = {"docling": {"enabled": True, "table_mode": "accurate"}}
    assert "already" in overrides_for("V1", accurate)[1]


def test_b0_requires_clean_tree_cuda_and_the_unified_profile():
    clean = {"commit": "abc", "dirty": False}
    assert b0_conditions(clean, "cuda", PROFILE)["met"]
    assert not b0_conditions({"commit": "abc", "dirty": True}, "cuda", PROFILE)["met"]
    assert not b0_conditions(clean, "cpu", PROFILE)["met"]
    assert not b0_conditions(clean, "cuda", "balanced")["met"]


def test_score_pages_parse_and_reject_malformed_selections():
    assert parse_score_pages(None) is None
    assert parse_score_pages("1,3-4") == [1, 3, 4]
    for value in ("", "0", "3-1", "a", "1,", "1-", "3-,5", "-3"):
        with pytest.raises(ValueError):
            parse_score_pages(value)


def test_source_inventory_requires_the_matrix_columns(tmp_path):
    good = tmp_path / "sources.csv"
    good.write_text("document_id,company_id,sha256\nA,CO," + "a" * 64 + "\n", encoding="utf-8")
    assert read_source_inventory(good)[0]["company_id"] == "co"
    bad = tmp_path / "bad.csv"
    bad.write_text("document_id,sha256\nA," + "a" * 64 + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="company_id"):
        read_source_inventory(bad)


def test_malformed_inventory_rows_are_value_errors_and_hex_case_is_accepted(tmp_path):
    header = "document_id,company_id,sha256\n"
    for name, body in (("short.csv", "A,CO\n"), ("long.csv", "A,CO," + "a" * 64 + ",extra\n"),
                       ("blank_id.csv", "A,CO,\n")):
        path = tmp_path / name
        path.write_text(header + body, encoding="utf-8")
        with pytest.raises(ValueError):  # never TypeError: main reports ValueError via parser.error
            read_source_inventory(path)
    upper = tmp_path / "upper.csv"
    upper.write_text(header + "A,CO," + "AB" * 32 + "\n", encoding="utf-8")
    assert read_source_inventory(upper)[0]["sha256"] == "ab" * 32


def test_company_ids_are_normalized_so_one_company_is_one_cluster(tmp_path):
    # As `collect sources` writes them: NFC, stripped, case-folded; any spelling of unknown is unknown.
    sha = "a" * 64
    sources = tmp_path / "sources.csv"
    sources.write_text("document_id,company_id,sha256\n"
                       f"ACB_2021,ACB,{sha}\nACB_2022, acb ,{sha}\nX_2022, Unknown,{sha}\nY_2022,,{sha}\n"
                       f"Z_2022,CÔNG,{sha}\n", encoding="utf-8")
    inventory = _company_inventory(str(sources))
    assert {key: row["company_id"] for key, row in inventory.items()} == \
        {"ACB_2021": "acb", "ACB_2022": "acb", "Z_2022": "công"}
    assert normalize_company_id("Co\u0302ng") == "công"  # decomposed input composes to NFC
    display = tmp_path / "display.csv"
    display.write_text(f"document_id,company_id,sha256\nA,Ngan hang ACB,{sha}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="display name"):
        read_source_inventory(display)


def test_colliding_document_ids_are_refused_before_any_run(tmp_path):
    pdfs = [tmp_path / "a" / "ACB_2022.pdf", tmp_path / "b" / "acb_2022.pdf"]
    with pytest.raises(ValueError, match="distinct document IDs"):
        document_ids([str(p) for p in pdfs])
    product = FakeProduct()
    with pytest.raises(ValueError, match="distinct document IDs"):
        run_configuration("F", _args(tmp_path, pdfs), GIT, {}, product)
    assert product.calls == [] and not (tmp_path / "matrix").exists()
    assert document_ids([str(tmp_path / "A.pdf"), str(tmp_path / "B.pdf")]) == ["A", "B"]


class FakeProduct:
    """Stands in for product_run.run_product; writes a compact document output."""

    def __init__(self, text="Doanh thu tang truong manh", fail=False):
        self.text, self.fail, self.calls = text, fail, []

    def __call__(self, pdf, output, *, config, assets, output_mode):
        self.calls.append({"pdf": str(pdf), "output": Path(output), "config": Path(config)})
        document = Path(output) / Path(pdf).stem
        if not self.fail:
            (document / "pages").mkdir(parents=True)
            (document / "pages" / "page-0001.md").write_text(self.text, encoding="utf-8")
            (document / "manifest.json").write_text(json.dumps(
                {"device": "cuda", "selected_pages": [1], "total_pages": 1}), encoding="utf-8")
            (document / "COMPLETED.json").write_text("{}", encoding="utf-8")
        return {"entry_point": product_run.ENTRY_POINT, "pdf": str(pdf), "document_id": Path(pdf).stem,
                "output": str(document), "log": str(Path(output).with_name(Path(output).name + ".log")),
                "returncode": 1 if self.fail else 0, "wall_seconds": 1.0, "peak_rss_mb": None,
                "ocr_identity": None if self.fail else "id", "pdf_sha256": None,
                "status": "FAILED" if self.fail else "COMPLETED"}


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    import scripts.run_scientific_benchmark as runner
    monkeypatch.setattr(runner, "capture_environment_metadata", lambda _: {})
    pdf = tmp_path / "MAT_report.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake input for hashing")
    gt = tmp_path / "gt"
    gt.mkdir()
    (gt / "mat_page_0001.txt").write_text("Doanh thu tang truong manh", encoding="utf-8")
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    sources = tmp_path / "sources.csv"
    sources.write_text(f"document_id,company_id,sha256\nMAT_report,MAT,{sha}\n", encoding="utf-8")
    inventory = {"MAT_report": {"company_id": "MAT", "sha256": sha}}
    return pdf, gt, sources, inventory


def _args(tmp_path, pdfs, gt=None, sources=None, output="matrix"):
    return argparse.Namespace(pdf=[str(p) for p in pdfs], score_pages="1", config=str(ROOT / "config/profiles.yaml"),
                              assets="none", output_mode="compact", ground_truth=str(gt) if gt else None,
                              sources=str(sources) if sources else None, splits=None,
                              output=str(tmp_path / output))


GIT = {"commit": "abc", "dirty": True, "uncommitted_diff_sha256": "d"}


def test_runs_record_counts_from_gt_and_keep_unrunnable_slots(tmp_path, workspace):
    pdf, gt, sources, inventory = workspace
    args = _args(tmp_path, [pdf], gt, sources)
    product = FakeProduct()
    f = run_configuration("F", args, GIT, inventory, product)
    assert f["status"] == "COMPLETED" and f["schema"] == RUN_RECORD_SCHEMA
    assert f["entry_point"] == "ocr_pipeline.cli.main" and f["profile"] == PROFILE
    assert f["quality_status"] == "COUNTS_RECORDED"
    cer = f["records_by_metric"]["cer"]
    assert [(r["company_id"], r["document_id"], r["page"], r["status"]) for r in cer] == \
        [("MAT", "MAT_report", 1, "MEASURED")]
    # F runs the base file itself, so its receipt identity can match a baseline lock.
    assert product.calls[0]["config"] == ROOT / "config/profiles.yaml"
    assert f["documents"][0]["device"] == "cuda"

    v1 = run_configuration("V1", args, GIT, inventory, product)
    assert v1["status"] == "COMPLETED" and v1["overrides"] == {"docling": {"table_mode": "accurate"}}
    derived = tmp_path / "matrix/V1/profiles.yaml"
    assert product.calls[1]["config"] == derived
    _, profile = product_run.base_profile(derived)
    assert profile["docling"]["table_mode"] == "accurate"
    assert "pipeline:" in derived.read_text(encoding="utf-8")  # base declarations kept
    assert v1["config_sha256"] != f["config_sha256"]

    for name in ("A1", "A2"):
        record = run_configuration(name, args, GIT, inventory, product)
        assert record["status"] in ("NOT_APPLICABLE", "NOT_IMPLEMENTED")
        assert (tmp_path / f"matrix/{name}/run_record.json").is_file()
    assert len(product.calls) == 2  # unrunnable slots never start the product
    with pytest.raises(ValueError, match="fresh"):
        run_configuration("F", args, GIT, inventory, product)


def test_failed_document_contributes_missing_output_records(tmp_path, workspace):
    pdf, gt, sources, inventory = workspace
    record = run_configuration("F", _args(tmp_path, [pdf], gt, sources), GIT, inventory, FakeProduct(fail=True))
    assert record["status"] == "FAILED" and record["failed_documents"] == ["MAT_report"]
    assert "product exit code 1" in record["documents"][0]["error"]
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
    record = run_configuration("F", _args(tmp_path, [pdf], gt, sources, "m1"), GIT, {}, FakeProduct())
    assert record["quality_status"] == "NOT_EVALUATED" and "company_id" in record["quality_status_reason"]
    (gt / "mat_page_0001.txt").rename(gt / "page_0001.txt")
    record = run_configuration("F", _args(tmp_path, [pdf], gt, sources, "m2"), GIT, inventory, FakeProduct())
    assert "document-prefixed" in record["quality_status_reason"] and "records_by_metric" not in record


def test_company_check_uses_the_digest_product_run_already_took(tmp_path, workspace):
    pdf, gt, sources, inventory = workspace

    class HashedProduct(FakeProduct):
        def __init__(self, digest):
            super().__init__()
            self.digest = digest

        def __call__(self, pdf, output, **options):
            return {**super().__call__(pdf, output, **options), "pdf_sha256": self.digest}

    good = run_configuration("F", _args(tmp_path, [pdf], gt, sources, "h1"), GIT, inventory,
                             HashedProduct(inventory["MAT_report"]["sha256"]))
    assert good["quality_status"] == "COUNTS_RECORDED"
    stale = run_configuration("F", _args(tmp_path, [pdf], gt, sources, "h2"), GIT, inventory,
                              HashedProduct("0" * 64))
    assert "PDF hash differs" in stale["quality_status_reason"]  # the recorded digest, not a rehash


def test_b0_records_its_conditions_from_the_product_output(tmp_path, workspace):
    pdf, gt, sources, inventory = workspace
    clean = {"commit": "locked", "dirty": False}
    record = run_configuration("B0", _args(tmp_path, [pdf]), clean, inventory, FakeProduct())
    assert record["b0_conditions"]["met"] is True and record["b0_conditions"]["commit"] == "locked"
    failed = run_configuration("B0", _args(tmp_path, [pdf], output="m3"), clean, inventory, FakeProduct(fail=True))
    assert failed["b0_conditions"]["met"] is False  # no device recorded without an output


def _write_record(runs, name, **fields):
    (runs / name).mkdir(parents=True, exist_ok=True)
    record = {"schema": RUN_RECORD_SCHEMA, "configuration": name, "status": "COMPLETED", "git": GIT,
              "profile": PROFILE, "source_fingerprint": "s", "base_config_sha256": "c",
              "inputs": {"pdf": ["a.pdf"], "score_pages": None}, **fields}
    (runs / name / "run_record.json").write_text(json.dumps(record), encoding="utf-8")
    return runs / name / "run_record.json"


def test_assemble_keeps_all_slots_and_rejects_unqualified_runs(tmp_path):
    runs = tmp_path / "runs"
    _write_record(runs, "F")
    _write_record(runs, "A2", status="NOT_IMPLEMENTED")
    _write_record(runs, "A6", source_fingerprint="older-code")
    _write_record(runs, "A3", base_config_sha256="other-config")
    (runs / "V1").mkdir()
    (runs / "V1" / "run_record.json").write_text("{not json", encoding="utf-8")
    b0 = _write_record(tmp_path / "b0", "B0", git={"commit": "head", "dirty": False},
                       b0_conditions={"met": True})
    protocol = tmp_path / "protocol.json"
    protocol.write_text(json.dumps({"metrics": ["cer"], "b0_commit": "locked"}), encoding="utf-8")
    result = assemble(str(b0), str(runs), str(protocol))
    assert set(result["slots"]) == set(CONFIGURATIONS)
    assert result["slots"]["B0"]["status"] == "NOT_ACCEPTED_AS_B0"  # HEAD is not the locked commit
    assert result["slots"]["A2"]["status"] == "NOT_IMPLEMENTED"
    assert result["slots"]["A1"]["status"] == "NOT_RUN"
    for name in ("A6", "A3"):
        assert result["slots"][name]["status"] == "INVALID_RECORD"
        assert "more than one variable" in result["slots"][name]["reason"]
    assert result["slots"]["V1"]["status"] == "INVALID_RECORD"
    assert len(result["family"]) == 8
    assert all(c["status"] == "NOT_EVALUATED" for c in result["comparisons"].values())
    assert result["eligible_for_quality_acceptance"] is False
