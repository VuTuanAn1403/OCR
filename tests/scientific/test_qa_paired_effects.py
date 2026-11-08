"""Paired accounting counterexamples, not OCR quality acceptance."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from benchmark.qa.__main__ import main
from benchmark.qa.evidence import file_digest
from benchmark.qa.paired_effects import run, summarize, verdict

ROOT = Path(__file__).resolve().parents[2]
DRAFT = ROOT / "Cai Tien/templates/benchmark_acceptance_protocol.example.yaml"


def counts(side, rows, metric="cer"):
    return {"schema_version": "ocr-paired-counts-v1", "acceptance_status": "NOT_EVALUATED", "run_id": side,
            "protocol_sha256": "1" * 64, "sample_sha256": "2" * 64, "gt_sha256": "3" * 64,
            "prediction_inventory_sha256": "4" * 64, "prediction_manifest_sha256": ("a" if side == "baseline" else "b") * 64,
            "normalization": "visible_strict_v1", "records_by_metric": {metric: rows}}


def row(key, errors, length=10, **evidence):
    return {"unit_id": key, "status": "MEASURED", "numerator": errors, "denominator": length,
            "evidence": {"reference_sha256": "5" * 64, **evidence}}


@pytest.fixture
def comparison():
    units = [{"unit_id": str(i), "document_id": "doc", "pdf_sha256": "6" * 64,
              "page": i + 1, "region_id": "page", "strata": ["small_text"] if i < 2 else [], "metrics": ["cer"]}
             for i in range(4)]
    left = [row(str(i), n) for i, n in enumerate((2, 0, 5, 0))]
    right = [row(str(i), n) for i, n in enumerate((0, 1, 1, 0))]
    return {"schema_version": "ocr-holdout-scorecard-sample-v1", "units": units}, counts("baseline", left), counts("candidate", right)


def test_all_four_transitions_and_conditional_denominators(comparison):
    report = summarize(*comparison)
    metric = report["comparisons"]["cer"]
    overall = metric["overall"]
    assert {k: overall[k] for k in ("fixed", "harmed", "still_wrong", "preserved_correct")} == dict.fromkeys(
        ("fixed", "harmed", "still_wrong", "preserved_correct"), 1)
    assert overall["fix_rate"] == overall["harm_rate"] == .5
    assert overall["documents_with_paired_units"] == 1 and overall["pages_with_paired_units"] == 4
    assert [r["effect"] for r in metric["units"]] == ["fixed", "harmed", "still_wrong", "preserved_correct"]
    assert metric["strata"]["small_text"]["fix_rate"] == metric["strata"]["small_text"]["harm_rate"] == 1
    assert report["quality_status"] == "NOT_EVALUATED" and report["evidence_level"] == "DECLARED_COUNTS_ONLY"
    assert report["access_policy"] == "AGGREGATE_ONLY" and "accuracy" not in report


def test_missing_output_is_wrong_even_on_labelled_empty_text(comparison):
    sample, left, right = comparison
    left["records_by_metric"]["cer"][0].update(numerator=0, denominator=0)
    right["records_by_metric"]["cer"][0].update(status="MISSING_OUTPUT", numerator=0, denominator=0)
    report = summarize(sample, left, right)["comparisons"]["cer"]
    assert report["units"][0]["effect"] == "harmed"
    assert report["overall"]["missing_output"]["candidate"] == 1


def test_missing_count_is_unknown_and_partial_rates_cannot_claim_whole_scope(comparison):
    sample, left, right = comparison
    right["records_by_metric"]["cer"].pop(0)
    result = summarize(sample, left, right)["comparisons"]["cer"]
    assert result["overall"]["status"] == "PARTIAL" and result["overall"]["unscored_units"] == 1
    assert result["overall"]["fix_rate"] is result["overall"]["harm_rate"] is None
    assert result["overall"]["observed_harm_rate"] == .5
    assert result["units"][0]["candidate_reason"] == "COUNT_RECORD_MISSING"


def test_known_wrong_sample_does_not_claim_zero_harm(comparison):
    sample, left, right = comparison
    for item in left["records_by_metric"]["cer"]:
        item["numerator"] = 1
    overall = summarize(sample, left, right)["comparisons"]["cer"]["overall"]
    assert overall["baseline_correct"] == 0 and overall["harm_rate"] is None
    assert overall["harm_rate_reason"] == "NO_BASELINE_CORRECT_UNITS"


@pytest.mark.parametrize("field", ["protocol_sha256", "sample_sha256", "gt_sha256", "prediction_inventory_sha256", "normalization"])
def test_different_reference_policy_or_sample_is_rejected(comparison, field):
    comparison[2][field] = "c" * 64 if field != "normalization" else "different"
    with pytest.raises(ValueError, match="identity differs"):
        summarize(*comparison)


@pytest.mark.parametrize("fault", ["duplicate", "extra", "same_run", "same_prediction", "denominator", "reference", "nan", "negative"])
def test_counterexamples_cannot_be_hidden_by_matching_totals(comparison, fault):
    sample, left, right = comparison
    records = right["records_by_metric"]["cer"]
    if fault == "duplicate": records.append(deepcopy(records[0]))
    elif fault == "extra": records.append(row("outside", 0))
    elif fault == "same_run": right["run_id"] = left["run_id"]
    elif fault == "same_prediction": right["prediction_manifest_sha256"] = left["prediction_manifest_sha256"]
    elif fault == "denominator": records[0]["denominator"] = 11
    elif fault == "reference": records[0]["evidence"]["reference_sha256"] = "7" * 64
    elif fault == "nan": records[0]["numerator"] = float("nan")
    else: records[0]["denominator"] = -1
    with pytest.raises(ValueError): summarize(sample, left, right)


@pytest.mark.parametrize("metric,evidence", [
    ("teds_content", {"missing": 0, "spurious": 1}), ("teds_structure", {"missing": 0, "spurious": 1}),
    ("numeric_cell_exact", {"missing": 0, "extra": 1}), ("keyword_recall", {"missing": 0, "extra": 1}),
    ("reading_order", {"missing_nodes": 0, "duplicate_predictions": 1}),
    ("layout_recall", {"tp": 1, "fn": 0, "fp": 1})])
def test_perfect_ratio_with_extra_sources_is_not_correct(metric, evidence):
    assert verdict(metric, row("u", 1, 1, **evidence))[0] is False
    with pytest.raises(ValueError): verdict(metric, row("u", 1, 1))


def test_continuous_renderer_score_does_not_become_semantic_correctness():
    answer, reason = verdict("formula_cdm_mean", row("f", 1, 1))
    assert answer is None and reason == "NO_BINARY_RULE_FOR_CONTINUOUS_RENDER_METRIC"
    assert verdict("formula_cdm_mean", {"status": "NOT_EVALUATED", "numerator": None, "denominator": None,
                                       "evidence": {"count_region": "fixture"}}) == (None, "SOURCE_COUNT_UNSCORED")


def test_zero_reference_nontext_is_not_fabricated_into_correct_empty_annotation():
    answer, reason = verdict("keyword_recall", row("u", 0, 0, missing=0, extra=0))
    assert answer is None and reason == "NO_REFERENCE_DENOMINATOR_FOR_BINARY_VERDICT"
    assert verdict("cer", row("empty", 3, 0))[0] is False
    assert verdict("cer", row("empty", 0, 0))[0] is True


def test_real_draft_stops_before_sample_prediction_or_ocr_reads(tmp_path):
    before = file_digest(DRAFT)
    output = ROOT.parent / (tmp_path.name + "-outside.json")
    assert main(["paired", "--protocol", str(DRAFT), "--evidence-root", str(ROOT), "--output", str(output)]) == 2
    # The root guard above prevents output outside root; use a local copy solely
    # to check real DRAFT readiness without altering/locking the source template.
    protocol = tmp_path / "protocol.yaml"
    protocol.write_bytes(DRAFT.read_bytes())
    result = run(SimpleNamespace(protocol=protocol, artifact_index=None, evidence_root=tmp_path))
    assert result["status"] == "NOT_READY" and result["quality_status"] == "NOT_EVALUATED"
    assert result["comparisons"] == {} and result["preflight"]["verified_artifact_hashes"] == {}
    assert file_digest(DRAFT) == before


def test_cli_draft_writes_explicit_not_ready_report_and_refuses_overwrite(tmp_path):
    protocol, output = tmp_path / "protocol.yaml", tmp_path / "report.json"
    protocol.write_bytes(DRAFT.read_bytes())
    args = ["paired", "--protocol", str(protocol), "--evidence-root", str(tmp_path), "--output", str(output)]
    assert main(args) == 1
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "NOT_READY"
    assert main(args) == 2
    publication = tmp_path / "publication"
    publication.mkdir()
    (publication / "COMPLETED.json").write_text("{}", encoding="utf-8")
    args[args.index(str(output))] = str(publication / "forbidden.json")
    assert main(args) == 2 and not (publication / "forbidden.json").exists()


@pytest.fixture
def controlled_backend(tmp_path, monkeypatch, comparison):
    """Orchestration double only; existing evaluator contracts cover source scoring."""
    from benchmark.scientific_evaluation import protocol_preflight, stratified_scorecard, scorecard_counts
    from ocr_artifacts.digest import sha256_json_compact
    sample, baseline, candidate = comparison
    paths = {}
    for name, data in (("protocol", {}), ("sample", sample), ("inventory", {}), ("gt", {})):
        paths[name] = tmp_path / (name + ".json")
        paths[name].write_text(json.dumps(data), encoding="utf-8")
    verification = {"status": "INPUTS_VERIFIED", "protocol_sha256": file_digest(paths["protocol"]),
                    "verified_artifact_hashes": {"data.gt_manifest_sha256": file_digest(paths["gt"])}}
    predictions, runs = {}, {"baseline": baseline, "candidate": candidate}
    for side in runs:
        directory = tmp_path / side / "doc"
        directory.mkdir(parents=True)
        for filename in ("manifest.json", "ocr_receipt.json", "COMPLETED.json", "extraction.json", "result.md"):
            (directory / filename).write_text(side + ": contract fixture", encoding="utf-8")
        predictions[side] = {"documents": [{"id": "doc", "source_dir": str(directory)}]}
        runs[side].update(protocol_sha256=verification["protocol_sha256"], sample_sha256=file_digest(paths["sample"]),
                          gt_sha256=file_digest(paths["gt"]), prediction_manifest_sha256=sha256_json_compact(predictions[side]),
                          prediction_inventory_sha256=file_digest(paths["inventory"]))
    inputs = {"verification": verification, "sample": sample, "plan": {"sample_sha256": file_digest(paths["sample"])},
              "predictions": predictions, "prediction_hash": file_digest(paths["inventory"]),
              "protocol": {"evaluation": {"normalization": "visible_strict_v1"}}, "artifact_path": lambda key: paths["gt"]}
    monkeypatch.setattr(protocol_preflight, "preflight", lambda *args: verification)
    monkeypatch.setattr(stratified_scorecard, "verified_inputs", lambda *args: inputs)
    monkeypatch.setattr(scorecard_counts, "count_verified_predictions", lambda inputs, side, *args, **kwargs: deepcopy(runs[side]))
    args = SimpleNamespace(protocol=paths["protocol"], artifact_index=None, sample=paths["sample"],
                           prediction_inventory=paths["inventory"], evidence_root=tmp_path,
                           report=tmp_path / "report.json", baseline=None, candidate=None)
    return args, runs, inputs


def test_verified_orchestration_recomputes_counts_and_rejects_edited_saved_counts(controlled_backend, tmp_path):
    args, runs, _ = controlled_backend
    result = run(args)
    assert result["evidence_level"] == "RECOMPUTED_CANONICAL_COUNTS" and result["quality_status"] == "NOT_EVALUATED"
    assert result["comparisons"]["cer"]["overall"]["fixed"] == 1
    saved = tmp_path / "saved.json"
    saved.write_text(json.dumps(runs["candidate"]), encoding="utf-8")
    args.candidate = saved
    assert run(args)["status"] == "MEASURED"
    changed = deepcopy(runs["candidate"])
    changed["records_by_metric"]["cer"][0]["numerator"] = 9
    saved.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="differs from recomputed"):
        run(args)


def test_verified_orchestration_cannot_substitute_the_other_prediction_side(controlled_backend):
    args, runs, _ = controlled_backend
    runs["candidate"]["prediction_manifest_sha256"] = runs["baseline"]["prediction_manifest_sha256"]
    with pytest.raises(ValueError, match="prediction side"):
        run(args)
