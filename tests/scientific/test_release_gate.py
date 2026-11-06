import json
from types import SimpleNamespace

import pytest

from benchmark.scientific_evaluation import release_gate
from ocr_artifacts.digest import sha256_json_compact
from ocr_artifacts.hashing import sha256_file


@pytest.fixture(autouse=True)
def isolate_native_measurement(monkeypatch):
    # Source replay has real-PDF tests in test_native_diacritic_replay.py.
    monkeypatch.setattr(release_gate, "recompute_native_diacritics", lambda *_: {"status": "PASS"})
    monkeypatch.setattr(release_gate, "check_native_readiness", lambda *_: {"status": "DECLARED_NATIVE_INPUTS_READY"})


def test_draft_stops_before_opening_holdout():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    draft = root / "Cai Tien/templates/benchmark_acceptance_protocol.example.yaml"
    report = release_gate.run_gate(SimpleNamespace(protocol=draft, artifact_index=None))
    assert report["release_status"] == "NOT_EVALUATED"
    assert report["preflight"]["status"] == "NOT_READY_FOR_ACCEPTANCE_MEASUREMENT"


def test_cli_rejects_report_under_a_published_batch_before_preflight(tmp_path, monkeypatch):
    import sys

    batch = tmp_path / "batch"
    batch.mkdir()
    (batch / "batch_input_manifest.json").write_text("{}", encoding="utf-8")
    args = [value for key in ("protocol", "artifact-index", "sample", "prediction-inventory")
            for value in (f"--{key}", str(tmp_path / "missing"))]
    report = batch / "new-folder" / "report.json"
    monkeypatch.setattr(sys, "argv", ["release-gate", *args, "--report", str(report)])
    with pytest.raises(SystemExit) as exc:
        release_gate.main()
    assert exc.value.code == 2 and not report.exists()

def test_quality_requires_all_overall_metrics_and_both_gates(monkeypatch):
    seen = []

    def counts(inputs, side, alignment, *, reading_order_alignments):
        seen.append((side, reading_order_alignments))
        return {"side": side}

    monkeypatch.setattr(release_gate, "count_verified_predictions", counts)
    good = {"status": "PASS"}
    comparisons = {
        metric: {"metric": metric, "stratum": "overall", "planned_units": 3, "paired_units": 3,
                 "absolute": good, "noninferiority": good}
        for metric in release_gate.PROTOCOL_THRESHOLDS
    }
    monkeypatch.setattr(release_gate, "evaluate_verified_counts", lambda *args: {"comparisons": comparisons})
    inputs = {"protocol": {"scope": {"declared_modalities": ["text", "numeric_cells", "tables", "reading_order"]},
                           "thresholds": {"declared_gt_evaluation_coverage_minimum": 1}}}
    inputs["protocol"]["scope"]["formula_scope_decision"] = {"decision": "EXCLUDED", "reason": "Controlled fixture scope."}
    args = SimpleNamespace(baseline_keyword_alignments=None, candidate_keyword_alignments=None,
                           candidate_reading_order_alignments="candidate-index")
    incomplete = release_gate._quality(inputs, args)
    assert incomplete["status"] == "NOT_EVALUATED"
    assert incomplete["formula_scope_issues"] == ["scope.formula_scope_decision: v7.0 release requires IN_SCOPE formula correctness"]
    assert seen == [("baseline", None), ("candidate", "candidate-index")]
    inputs["protocol"]["scope"]["formula_scope_decision"] = {"decision": "IN_SCOPE", "reason": "Formula accuracy required."}
    unresolved = release_gate._quality(inputs, args)
    assert unresolved["status"] == "NOT_EVALUATED" and unresolved["formula_scope_issues"]
    inputs["protocol"]["scope"]["formula_scope_decision"] = {"decision": "EXCLUDED", "reason": "Controlled fixture scope."}
    comparisons["cer"]["paired_units"] = 2
    assert release_gate._quality(inputs, args)["status"] == "FAIL"
    comparisons.pop("cer")
    result = release_gate._quality(inputs, args)
    assert result["status"] == "NOT_EVALUATED" and result["missing_overall_metrics"] == ["cer"]


def test_layout_gate_requires_both_metrics_and_mandatory_gt_classes(monkeypatch):
    classes = ["Title"]
    counts = {"records_by_metric": {"layout_recall": [{"evidence": {"reference_categories": classes}}]}}
    good = {"status": "PASS"}
    comparisons = {metric: {"metric": metric, "stratum": "overall", "planned_units": 2, "paired_units": 2,
                            "absolute": good, "noninferiority": good}
                   for metric in (*release_gate.PROTOCOL_THRESHOLDS, *release_gate.MODALITY_METRICS["layout"])}
    monkeypatch.setattr(release_gate, "count_verified_predictions", lambda *args, **kwargs: counts)
    monkeypatch.setattr(release_gate, "evaluate_verified_counts", lambda *args: {"comparisons": comparisons})
    inputs = {"protocol": {"scope": {"declared_modalities": ["text", "numeric_cells", "tables", "reading_order", "layout"]},
                           "thresholds": {"declared_gt_evaluation_coverage_minimum": 1}}}
    inputs["protocol"]["scope"]["formula_scope_decision"] = {"decision": "EXCLUDED", "reason": "Controlled fixture scope."}
    args = SimpleNamespace(baseline_keyword_alignments=None, candidate_keyword_alignments=None)
    report = release_gate._quality(inputs, args)
    assert report["status"] == "NOT_EVALUATED"
    assert set(report["missing_layout_gt_classes"]) == set(release_gate.MANDATORY_CLASSES) - {"Title"}
    classes[:] = release_gate.MANDATORY_CLASSES
    incomplete = release_gate._quality(inputs, args)
    assert incomplete["status"] == "NOT_EVALUATED" and incomplete["missing_layout_gt_classes"] == []
    assert incomplete["formula_scope_issues"]
    comparisons.pop("layout_errors_per_gt")
    assert release_gate._quality(inputs, args)["missing_overall_metrics"] == ["layout_errors_per_gt"]


def test_formula_quality_recomputes_sources_before_the_shared_family(monkeypatch):
    events = []
    formula = {side: {"side": side} for side in ("baseline", "candidate")}
    source_evidence = {"status": "SOURCE_COUNTS_RECOMPUTED", "unsupported_references": []}
    der_count = {"unit_id": "diacritics", "status": "MEASURED", "numerator": 0, "denominator": 10000,
                 "evidence": {"diacritic_gate": {"uncomposed_reference_marks": 0, "uncomposed_prediction_marks": 0}}}

    def replay(inputs, args):
        events.append("source-replay")
        return formula, source_evidence

    def count(inputs, side, alignment, *, reading_order_alignments, formula_counts):
        assert formula_counts is formula[side]
        events.append(side)
        return {"records_by_metric": {"der": [der_count], "keyword_recall": [{"unit_id": "keyword", "status": "MEASURED",
            "numerator": 1, "denominator": 1, "evidence": {"missing": 0, "extra": 0}}]}, "side": side}

    def evaluate(*args):
        events.append("whole-family")
        return {"comparisons": {metric: {"metric": metric, "stratum": "overall", "planned_units": 3, "paired_units": 3,
            "absolute": {"status": "PASS"}, "noninferiority": {"status": "PASS"}}
            for metric in (*release_gate.PROTOCOL_THRESHOLDS, "keyword_recall", *release_gate.FORMULA_METRICS)}}

    monkeypatch.setattr(release_gate, "recompute_for_gate", replay)
    monkeypatch.setattr(release_gate, "count_verified_predictions", count)
    monkeypatch.setattr(release_gate, "evaluate_verified_counts", evaluate)
    inputs = {"sample": {"units": [{"unit_id": "keyword", "metrics": ["keyword_recall"]},
                                   {"unit_id": "diacritics", "metrics": ["der"]}]},
              "protocol": {"scope": {"declared_modalities": ["text", "numeric_cells", "tables", "reading_order", "keywords", "formulas"],
                 "formula_scope_decision": {"decision": "IN_SCOPE", "reason": "Controlled fixture"}},
                           "thresholds": {"declared_gt_evaluation_coverage_minimum": 1}}}
    args = SimpleNamespace(baseline_keyword_alignments=None, candidate_keyword_alignments=None)
    result = release_gate._quality(inputs, args)
    assert events == ["source-replay", "baseline", "candidate", "whole-family"]
    assert result["status"] == "PASS" and not result["unsupported_modalities"] and not result["formula_scope_issues"]
    source_evidence["unsupported_references"].append({"reference_id": "fixture", "format": "MATHML"})
    assert release_gate._quality(inputs, args)["status"] == "NOT_EVALUATED"
    source_evidence["unsupported_references"].clear()
    der_count["numerator"] = 2
    failed = release_gate._quality(inputs, args)
    assert failed["status"] == "FAIL"
    assert failed["diacritic_preservation_gate"]["status"] == "FAIL"
    der_count["numerator"] = 0
    monkeypatch.setattr(release_gate, "recompute_native_diacritics", lambda *_: {"status": "FAIL"})
    assert release_gate._quality(inputs, args)["status"] == "FAIL"
    monkeypatch.setattr(release_gate, "recompute_native_diacritics", lambda *_: {"status": "NOT_EVALUATED"})
    assert release_gate._quality(inputs, args)["status"] == "NOT_EVALUATED"


def _keyword_inputs():
    return {"protocol": {"scope": {"declared_modalities": ["keywords"]}}, "sample": {"units": [
        {"unit_id": "positive", "metrics": ["keyword_recall"]},
        {"unit_id": "negative", "metrics": ["keyword_recall"]},
        {"unit_id": "text-only", "metrics": ["cer"]}]}}, {"records_by_metric": {"keyword_recall": [
        {"unit_id": "positive", "status": "MEASURED", "numerator": 2, "denominator": 2,
         "evidence": {"missing": 0, "extra": 0}},
        {"unit_id": "negative", "status": "MEASURED", "numerator": 0, "denominator": 0,
         "evidence": {"missing": 0, "extra": 0}}]}}


def test_keyword_occurrence_gate_accepts_observed_zero_errors_in_positive_and_negative_regions():
    inputs, candidate = _keyword_inputs()
    result = release_gate._keyword_occurrence_gate(inputs, candidate)
    assert result["status"] == "PASS" and result["planned_units"] == result["evaluated_units"] == 2
    assert result["missing"] == result["extra"] == 0


@pytest.mark.parametrize("change", ["missing", "extra_on_negative", "missing_output"])
def test_keyword_occurrence_errors_cannot_be_hidden_by_recall(change):
    inputs, candidate = _keyword_inputs()
    positive, negative = candidate["records_by_metric"]["keyword_recall"]
    if change == "missing":
        positive["numerator"] = 1
        positive["evidence"]["missing"] = 1
    elif change == "extra_on_negative":
        negative["evidence"]["extra"] = 1
    else:
        negative["status"] = "MISSING_OUTPUT"
    assert release_gate._keyword_occurrence_gate(inputs, candidate)["status"] == "FAIL"


@pytest.mark.parametrize("change", ["missing_record", "missing_count", "null_count", "contradictory", "unmeasured"])
def test_incomplete_keyword_evidence_keeps_totals_unknown(change):
    inputs, candidate = _keyword_inputs()
    records = candidate["records_by_metric"]["keyword_recall"]
    if change == "missing_record":
        records.pop()
    elif change == "missing_count":
        records[1]["evidence"].pop("extra")
    elif change == "null_count":
        records[1]["evidence"]["extra"] = None
    elif change == "contradictory":
        records[1]["evidence"]["missing"] = 1
    else:
        records[1]["status"] = "NOT_EVALUATED"
    result = release_gate._keyword_occurrence_gate(inputs, candidate)
    assert result["status"] == "NOT_EVALUATED" and result["evaluated_units"] == 1
    assert result["missing"] is result["extra"] is None


def test_v70_keyword_gate_cannot_be_omitted_or_use_an_empty_sample():
    inputs, candidate = _keyword_inputs()
    inputs["protocol"]["scope"]["declared_modalities"] = ["text"]
    assert release_gate._keyword_occurrence_gate(inputs, candidate)["status"] == "NOT_EVALUATED"
    inputs["protocol"]["scope"]["declared_modalities"] = ["keywords"]
    inputs["sample"]["units"].clear()
    candidate["records_by_metric"]["keyword_recall"].clear()
    result = release_gate._keyword_occurrence_gate(inputs, candidate)
    assert result["status"] == "NOT_EVALUATED" and result["missing"] is result["extra"] is None


@pytest.mark.parametrize("denominator,expected", [(9999, "FAIL"), (10000, "PASS")])
def test_ocr_preservation_release_gate_uses_integer_counts_at_the_9999_boundary(denominator, expected):
    inputs = {"sample": {"units": [{"unit_id": "u", "metrics": ["der"]}]}}
    counts = {"records_by_metric": {"der": [{"unit_id": "u", "status": "MEASURED", "numerator": 1,
        "denominator": denominator, "evidence": {"diacritic_gate": {
            "uncomposed_reference_marks": 0, "uncomposed_prediction_marks": 0}}}]}}
    assert release_gate._ocr_diacritic_point_gate(inputs, counts)["status"] == expected
    counts["records_by_metric"]["der"][0]["evidence"]["diacritic_gate"]["uncomposed_prediction_marks"] = 1
    assert release_gate._ocr_diacritic_point_gate(inputs, counts)["status"] == "FAIL"


@pytest.mark.parametrize("change", ["missing_record", "missing_marks", "invalid_gt", "missing_output", "zero_denominator"])
def test_ocr_preservation_gate_requires_full_evaluated_scope(change):
    inputs = {"sample": {"units": [{"unit_id": "u", "metrics": ["der"]}]}}
    row = {"unit_id": "u", "status": "MEASURED", "numerator": 0, "denominator": 1,
           "evidence": {"diacritic_gate": {"uncomposed_reference_marks": 0, "uncomposed_prediction_marks": 0}}}
    counts = {"records_by_metric": {"der": [row]}}
    if change == "missing_record":
        counts["records_by_metric"]["der"].clear()
    elif change == "missing_marks":
        row["evidence"].clear()
    elif change == "invalid_gt":
        row["evidence"]["diacritic_gate"]["uncomposed_reference_marks"] = 1
    elif change == "missing_output":
        row["status"] = "MISSING_OUTPUT"
    else:
        row["denominator"] = 0
    assert release_gate._ocr_diacritic_point_gate(inputs, counts)["status"] == "NOT_EVALUATED"


def test_release_gate_reuses_release_scope_when_loading_verified_inputs(tmp_path, monkeypatch):
    verified = {"status": "INPUTS_VERIFIED", "scope_context": "V70_RELEASE", "protocol_sha256": "fixture"}
    inputs = {"verification": verified, "predictions": {"baseline": {"batches": []}, "candidate": {"batches": []}},
              "prediction_hash": "fixture", "plan": {"sample_sha256": "fixture"}}

    def load(args, *, for_release):
        assert for_release is True
        return inputs

    monkeypatch.setattr(release_gate, "preflight", lambda *_args, **_kwargs: verified)
    monkeypatch.setattr(release_gate, "verified_inputs", load)
    monkeypatch.setattr(release_gate, "_verify_evaluator", lambda *_: None)
    monkeypatch.setattr(release_gate, "_verify_candidate_runtime", lambda *_: None)
    monkeypatch.setattr(release_gate, "_quality", lambda *_: {"status": "NOT_EVALUATED"})
    args = SimpleNamespace(protocol=None, artifact_index=None, operational_evidence=None, decision=None,
                           report=tmp_path / "gate.json")
    assert release_gate.run_gate(args)["release_status"] == "NOT_EVALUATED"


def test_slo_uses_pooled_pages_elapsed_and_keeps_a_resource_failure():
    runs = [
        dict(document_seconds={"a": 2, "b": 4}, elapsed_seconds=8, pages=16, peak_rss_mib=7,
             peak_vram_mib=6, cost=4, retries=0, timeouts=0, oom=0),
        dict(document_seconds={"a": 3, "b": 5}, elapsed_seconds=10, pages=16, peak_rss_mib=8,
             peak_vram_mib=9, cost=4, retries=1, timeouts=0, oom=0),
    ]
    limits = dict(document_p50_seconds_max=4, document_p95_seconds_max=5, pages_per_second_min=1.5,
                  peak_rss_mib_max=10, peak_vram_mib_max=8, cost_per_page_max=.3,
                  retries_max=1, timeouts_max=0, oom_max=0)
    result = release_gate._slo(runs, limits)
    assert result["metrics"]["pages_per_second"] == pytest.approx(32 / 18)
    assert result["metrics"]["document_p50_seconds"] == 3.5
    assert result["metrics"]["document_p95_seconds"] == 5
    assert result["status"] == "FAIL" and result["checks"]["peak_vram_mib"] == "FAIL"
    limits["peak_vram_mib_max"] = 10
    runs[0]["cost"] = None
    incomplete = release_gate._slo(runs, limits)
    assert incomplete["metrics"]["cost_per_page"] is None
    assert incomplete["status"] == incomplete["checks"]["cost_per_page"] == "NOT_EVALUATED"
    runs[0]["cost"] = 4
    runs[0]["peak_rss_mib"] = None
    incomplete = release_gate._slo(runs, limits)
    assert incomplete["metrics"]["peak_rss_mib"] is None
    assert incomplete["checks"]["peak_rss_mib"] == "NOT_EVALUATED"


def test_gate_checks_evaluator_and_candidate_identity():
    from pathlib import Path

    root = Path(release_gate.__file__).parent
    files = {name: sha256_file(root / name) for name in release_gate.EVALUATOR_MODULES}
    locks = {"text.lock": "a" * 64, "docling.lock": "b" * 64}
    runtime = {"lock_hashes": locks, "text_python": "text/python", "docling_python": "docling/python",
               "model_hashes": {"runtime-models.json": "c" * 64}}
    gpu = {"device": "fixture", "total_mib": 4096}
    values = {"evaluation.evaluator_commit_and_dirty_diff_sha256": {"modules": files},
              "runtime.dependency_lock_manifest_sha256": {"locks": locks},
              "runtime.interpreter_and_hardware_manifest_sha256": {
                  "text_python": runtime["text_python"], "docling_python": runtime["docling_python"], "gpu": gpu}}
    inputs = {"artifact": lambda key, schema: values[key],
              "verification": {"verified_artifact_hashes": {
                  "evaluation.projection_code_sha256": files["markdown_evaluator.py"],
                  "runtime.model_registry_sha256": "c" * 64}},
              "predictions": {"candidate": {"batches": [{"runtime": runtime}],
                                            "documents": [{"scheduler": {"gpu": gpu.copy()}}]}}}
    release_gate._verify_evaluator(inputs)
    release_gate._verify_candidate_runtime(inputs)
    detector_digest = files.pop("text_detection_metric.py")
    with pytest.raises(ValueError, match="evaluator or projection"):
        release_gate._verify_evaluator(inputs)
    files["text_detection_metric.py"] = detector_digest
    files["numeric_metric.py"] = "wrong"
    with pytest.raises(ValueError, match="evaluator or projection"):
        release_gate._verify_evaluator(inputs)
    inputs["predictions"]["candidate"]["documents"][0]["scheduler"]["gpu"]["device"] = "another"
    with pytest.raises(ValueError, match="GPU identity"):
        release_gate._verify_candidate_runtime(inputs)


def test_runtime_rechecks_publication_and_rejects_reuse(monkeypatch, tmp_path):
    batch = tmp_path / "batch"
    runtime = {"source_fingerprint": "fixture"}
    publication = {"batches": [{"runtime": runtime}],
                   "documents": [{"completion_sha256": "first", "scheduler": {
                       "generation": "same", "gpu": {"device": "fixture", "total_mib": 4096}}}]}
    monkeypatch.setattr(release_gate, "collect_predictions", lambda roots: publication)
    monkeypatch.setattr(release_gate, "_extraction_identity", lambda batch: sha256_json_compact(batch["runtime"]))
    trace = {"batch_roots": [str(batch)], "inventory_sha256": sha256_json_compact(publication)}
    paths, hashes = set(), set()
    gpu = {("fixture", 4096)}
    assert release_gate._validate_runtime_batch(trace, paths, hashes, {sha256_json_compact(runtime)}, gpu)
    with pytest.raises(ValueError, match="separate output"):
        release_gate._validate_runtime_batch(trace, paths, hashes, {sha256_json_compact(runtime)}, gpu)
    trace["batch_roots"] = [str(tmp_path / "different")]
    with pytest.raises(ValueError, match="Duplicate operational publication"):
        release_gate._validate_runtime_batch(trace, paths, hashes, {sha256_json_compact(runtime)}, gpu)
    trace["inventory_sha256"] = "changed"
    with pytest.raises(ValueError, match="receipts or runtime"):
        release_gate._validate_runtime_batch(trace, paths, set(), {sha256_json_compact(runtime)}, gpu)
    publication["documents"][0]["scheduler"]["gpu"]["device"] = "other"
    trace["inventory_sha256"] = sha256_json_compact(publication)
    with pytest.raises(ValueError, match="Operational GPU"):
        release_gate._validate_runtime_batch(trace, set(), set(), {sha256_json_compact(runtime)}, gpu)


def test_extraction_identity_covers_config_and_export_options_with_staging_allowed(tmp_path):
    from ocr_pipeline.backend import OCR_IDENTITY_KEYS

    backend = {key: "fixture" for key in OCR_IDENTITY_KEYS if key not in ("pdf_sha256", "assets", "output_mode")}
    backend["config"] = {"render_dpi": 300}
    config = {"backend": backend, "assets": "png", "output_mode": "compact", "input_path": "original"}
    path = tmp_path / "batch_config.json"

    def identity():
        path.write_text(json.dumps(config), encoding="utf-8")
        return release_gate._extraction_identity({"path": str(tmp_path), "configuration_sha256": sha256_file(path)})

    original = identity()
    config["input_path"] = "byte-identical-staging"
    assert identity() == original
    config["backend"]["config"]["render_dpi"] = 180
    assert identity() != original
    config["backend"]["config"]["render_dpi"] = 300
    config["assets"] = "none"
    assert identity() != original
    config["assets"] = "png"
    config["output_mode"] = "legacy"
    assert identity() != original

def test_operations_keep_modes_workloads_and_recovery_scope(tmp_path, monkeypatch):
    def write(name, schema, **payload):
        path = tmp_path / name
        path.write_text(json.dumps({"schema_version": schema, **payload}), encoding="utf-8")
        return {"path": name, "sha256": sha256_file(path)}

    pdf = "a" * 64
    runtime = {"source_fingerprint": "fixture"}
    gpu = {"device": "fixture", "total_mib": 4096}
    monkeypatch.setattr(release_gate, "_extraction_identity", lambda batch: sha256_json_compact(batch["runtime"]))
    plan = write("plan.json", "ocr-operation-plan-v1", workload_pdf_sha256=[pdf], minimum_soak_minutes=1,
                 minimum_runs=dict.fromkeys(release_gate.OPERATION_MODES, 2), recovery_scenarios=["export_interruption"])
    limits = dict(document_p50_seconds_max=31, document_p95_seconds_max=31, pages_per_second_min=.5,
                  peak_rss_mib_max=20, peak_vram_mib_max=20, cost_per_page_max=1,
                  retries_max=0, timeouts_max=0, oom_max=0)
    slos = write("slos.json", "ocr-operation-slos-v1", currency="VND",
                 modes=dict.fromkeys(release_gate.OPERATION_MODES, limits))
    drift_fields = dict(owner="reviewer", interval_days=7, minimum_documents=5, strata=["small_text"],
                        escalation_trigger="critical_error", independent_annotation_required=True)
    drift = write("drift.json", "ocr-drift-sampling-plan-v1", **drift_fields, status="LOCKED",
                  approved_by="curator", locked_at="2026-11-04T00:00:00+07:00")
    predictions = {"batches": [{"path": str(tmp_path / "candidate"), "runtime": runtime}],
                   "documents": [{"scheduler": {"gpu": gpu}}]}
    inputs = {"protocol": {"runtime": {"warm_cold_repeated_run_plan_sha256": plan["sha256"],
                                       "latency_resource_cost_slos_sha256": slos["sha256"]}},
              "predictions": {"baseline": {"batches": [{"path": str(tmp_path / "baseline")}]},
                              "candidate": predictions}}
    observed = {}
    runs = []
    for mode in (*release_gate.OPERATION_MODES, "recovery"):
        for i in range(1 if mode == "recovery" else 2):
            key = f"{mode}-{i}"
            batch = tmp_path / key
            observed[str(batch)] = {"batches": [{"runtime": runtime}],
                                    "documents": [{"id": "d", "pdf_sha256": pdf, "total_pages": 20,
                                                   "completion_sha256": key, "scheduler": {
                                                       "generation": "identity", "gpu": gpu,
                                                       "reused_phases": ["text"] if mode == "cache" else []}}]}
            trace = dict(run_id=key, batch_roots=[str(batch)], inventory_sha256=sha256_json_compact(observed[str(batch)]),
                         currency="VND", mode=mode, document_seconds={"d": 30}, elapsed_seconds=31,
                         peak_rss_mib=10, peak_vram_mib=12, cost=4, retries=0, timeouts=0, oom=0)
            if mode == "recovery":
                trace.update(scenario="export_interruption", interrupted_at="2026-11-04T00:00:00+07:00",
                             recovered_publication_verified=True)
            runs.append(write(f"{key}.json", "ocr-operation-trace-v1", **trace))
    monkeypatch.setattr(release_gate, "collect_predictions", lambda roots: observed[str(roots[0])])
    evidence_path = tmp_path / "evidence.json"
    evidence = {"operation_plan": plan, "slos": slos, "drift_sampling_plan": drift,
                "operator": "operator", "operational_runs": runs}
    report = release_gate._operations(inputs, evidence_path, evidence, tmp_path / "report.json")
    assert report["status"] == "PASS" and report["measured_minutes"] == pytest.approx(186 / 60)
    assert report["fresh_ocr_minutes"] == pytest.approx(124 / 60)
    assert report["modes"]["cold"]["pages"] == 40
    assert report["drift_plan_status"] == "PASS"
    evidence["drift_sampling_plan"] = write("drift-draft.json", "ocr-drift-sampling-plan-v1", **drift_fields, status="DRAFT")
    draft = release_gate._operations(inputs, evidence_path, evidence, tmp_path / "draft-report.json")
    assert draft["drift_plan_status"] == draft["status"] == "NOT_EVALUATED"
    evidence["drift_sampling_plan"] = drift
    evidence["operational_runs"] = runs[:-1]
    report = release_gate._operations(inputs, evidence_path, evidence, tmp_path / "report.json")
    assert report["status"] == "NOT_EVALUATED"
    assert report["missing_recovery_scenarios"] == ["export_interruption"]
    # The trace claims cache reuse while the verified scheduler shows fresh OCR.
    observed[str(tmp_path / "cache-0")]["documents"][0]["scheduler"]["reused_phases"] = []
    cached = json.loads((tmp_path / "cache-0.json").read_text(encoding="utf-8"))
    cached.pop("schema_version")
    cached["inventory_sha256"] = sha256_json_compact(observed[str(tmp_path / "cache-0")])
    evidence["operational_runs"][4] = write("cache-0.json", "ocr-operation-trace-v1", **cached)
    with pytest.raises(ValueError, match="recorded stage reuse"):
        release_gate._operations(inputs, evidence_path, evidence, tmp_path / "report.json")


def test_review_recomputes_original_inputs_and_rejects_changed_summary(tmp_path):
    import runpy
    from pathlib import Path

    from benchmark.scientific_evaluation.review_calibration import evaluate

    fixture = Path(__file__).with_name("test_review_calibration.py")
    create = runpy.run_path(str(fixture))["inputs"].__wrapped__(tmp_path)
    calibration_args, provenance = create("calibration")
    calibration = tmp_path / "calibration.json"
    calibration.write_text(json.dumps(evaluate(*calibration_args, **provenance, threshold=.9)), encoding="utf-8")
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps(dict(schema_version="review-threshold-lock-v1", status="LOCKED",
                                     approved_by="fixture", locked_at="2026-11-04T00:00:00+07:00", threshold=.9,
                                     calibration_report_sha256=sha256_file(calibration))), encoding="utf-8")
    args, _ = create("holdout")
    report = evaluate(*args, **provenance, policy=policy, calibration_report=calibration)
    output = tmp_path / "review.json"
    output.write_text(json.dumps(report), encoding="utf-8")
    candidate = {"documents": [{"id": "d", "pdf_sha256": "d" * 64, "total_pages": 1}]}
    files = dict(zip(("sample", "labels", "predictions"), args[:3]))
    files.update(provenance, policy=policy, calibration_report=calibration)
    index = tmp_path / "review-inputs.json"
    index.write_text(json.dumps(dict(schema_version="ocr-release-review-inputs-v1",
                                    prediction_manifest_sha256=sha256_json_compact(candidate),
                                    files={key: {"path": path.name, "sha256": sha256_file(path)}
                                           for key, path in files.items()})), encoding="utf-8")
    inputs = {"protocol": {"thresholds": {"automatic_acceptance_coverage_minimum": .3,
                                          "noncritical_review_miss_rate_maximum": .01,
                                          "critical_review_misses_maximum": 0}},
              "verification": {"verified_artifact_hashes": {"data.split_manifest_sha256": sha256_file(args[4]),
                                                            "review.calibrated_thresholds_sha256": sha256_file(policy),
                                                            "review.holdout_sample_sha256": sha256_file(args[0])}},
              "artifact_path": dict(zip(("data.input_manifest_sha256", "data.split_manifest_sha256",
                                        "data.near_duplicate_audit_sha256"), args[3:])).__getitem__,
              "split": json.loads(args[4].read_text(encoding="utf-8")), "predictions": {"candidate": candidate}}
    evidence = {"holdout_review": {"path": output.name, "sha256": sha256_file(output)},
                "review_inputs": {"path": index.name, "sha256": sha256_file(index)}}
    capacity = tmp_path / "capacity.json"
    capacity.write_text(json.dumps(dict(schema_version="ocr-review-capacity-v1", approved_by="fixture",
                                       locked_at="2026-11-04T00:00:00+07:00", expected_units_per_day=100,
                                       available_seconds_per_day=1000, cost_budget_per_day=10000, currency="VND",
                                       review_report_sha256=evidence["holdout_review"]["sha256"])), encoding="utf-8")
    evidence["review_capacity"] = {"path": capacity.name, "sha256": sha256_file(capacity)}
    result = release_gate._review(inputs, tmp_path / "evidence.json", evidence)
    assert result["status"] == "FAIL" and result["checks"]["critical_review_misses"] == "FAIL"
    assert result["checks"]["actual_review_cost_and_time"] == "NOT_EVALUATED"
    assert result["checks"]["holdout_source_binding"] == result["checks"]["calibration_source_binding"] == "NOT_EVALUATED"
    locked_hashes = inputs["verification"]["verified_artifact_hashes"]
    locked_hashes["review.holdout_sample_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="locked holdout sample"):
        release_gate._review(inputs, tmp_path / "evidence.json", evidence)
    locked_hashes["review.holdout_sample_sha256"] = sha256_file(args[0])
    report["routing"]["critical_review_misses"] = 0
    output.write_text(json.dumps(report), encoding="utf-8")
    evidence["holdout_review"]["sha256"] = sha256_file(output)
    with pytest.raises(ValueError, match="differs from recomputed"):
        release_gate._review(inputs, tmp_path / "evidence.json", evidence)


def test_gate_recomputes_calibration_from_separate_batches_and_same_configuration(tmp_path, monkeypatch):
    def write(name, payload):
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path, {"path": path.name, "sha256": sha256_file(path)}

    files = {field: write(f"calibration-{field}.json", {})[1] for field in
             ("sample", "labels", "predictions", "adjudication")}
    root = tmp_path / "calibration-batch"
    _, index = write("calibration-inputs.json", {"schema_version": "ocr-release-review-calibration-inputs-v1",
                                                "files": files, "batch_roots": [str(root)]})
    report = {"schema_version": release_gate.REPORT_SCHEMA, "canonical_source": {"fixture": True}}
    path, record = write("calibration-report.json", report)
    paths = {"calibration_report": path, "score_protocol": tmp_path / "protocol", "label_definition": tmp_path / "definition"}
    candidate = {"batches": [{"identity": "same"}]}
    inputs = {"predictions": {"candidate": candidate}, "artifact_path": lambda name: tmp_path / name}
    inventory = {"batches": [{"identity": "same"}]}

    def recompute(*args, **options):
        assert options["canonical_inventory"] == inventory and options["threshold"] == .9
        return report

    monkeypatch.setattr(release_gate, "collect_predictions", lambda roots: inventory if roots == [root] else None)
    monkeypatch.setattr(release_gate, "_extraction_identity", lambda batch: batch["identity"])
    monkeypatch.setattr(release_gate, "evaluate_review", recompute)
    assert release_gate._canonical_calibration(inputs, tmp_path / "index", {"calibration_inputs": index},
                                               paths, {"calibration_report": record}, .9) == "PASS"
    inventory["batches"][0]["identity"] = "changed"
    with pytest.raises(ValueError, match="differs from the holdout candidate"):
        release_gate._canonical_calibration(inputs, tmp_path / "index", {"calibration_inputs": index},
                                            paths, {"calibration_report": record}, .9)


def test_review_capacity_uses_recorded_review_cost_per_unit(tmp_path):
    capacity = tmp_path / "capacity.json"
    capacity.write_text(json.dumps(dict(schema_version="ocr-review-capacity-v1", approved_by="fixture",
                                       locked_at="2026-11-04T00:00:00+07:00", expected_units_per_day=100,
                                       available_seconds_per_day=1000, cost_budget_per_day=100, currency="VND",
                                       review_report_sha256="a" * 64)), encoding="utf-8")
    evidence = {"review_capacity": {"path": capacity.name, "sha256": sha256_file(capacity)},
                "holdout_review": {"sha256": "a" * 64}}
    report = {"definition": {"currency": "VND"}, "routing": {"units": 10, "review_required": 2},
              "actual_review": {"reviewed_units": 2, "total_seconds": 100, "total_cost": 20}}
    result = release_gate._review_capacity(tmp_path / "index.json", evidence, report)
    assert result["estimated_seconds_per_day"] == 1000
    assert result["estimated_cost_per_day"] == 200
    assert result["status"] == "FAIL"


def test_decision_is_bound_to_all_gates_and_independent_reviewer(tmp_path):
    drift = "1" * 64
    report = {"quality": {"status": "PASS"}, "review": {"status": "PASS"},
              "operations": {"status": "PASS", "drift_sampling_plan_sha256": drift}}
    inputs = {"protocol": {"approved_by": "author", "data": {"holdout_custodian": "custodian"},
                           "thresholds": {"observed_critical_numeric_errors_maximum": 0}}}
    evidence = {"operator": "operator"}
    args = SimpleNamespace(decision=None)
    pending = release_gate._decision(inputs, report, args, evidence)
    assert pending["release_status"] == "AWAITING_INDEPENDENT_DECISION"
    args.decision = tmp_path / "decision.json"
    decision = dict(schema_version="ocr-independent-release-decision-v1", reviewer="other",
                    reviewed_at="2026-11-04T00:00:00+07:00", status="APPROVED",
                    evidence_sha256=pending["evidence_sha256"], observed_critical_numeric_errors=0,
                    unresolved_critical_defects=0, independent_gt_checked=True, critical_scope_checked=True,
                    runtime_trace_checked=True, drift_sample_checked=True, drift_sampling_plan_sha256=drift)

    def evaluate():
        args.decision.write_text(json.dumps(decision), encoding="utf-8")
        return release_gate._decision(inputs, report, args, evidence)

    assert evaluate()["release_status"] == "APPROVED"
    decision["observed_critical_numeric_errors"] = 1
    assert evaluate()["release_status"] == "REJECTED"
    decision["reviewer"] = " OPERATOR "
    with pytest.raises(ValueError, match="independent"):
        evaluate()
    evidence["operator"] = "Opérateur"
    decision["reviewer"] = "Ope\u0301rateur"
    with pytest.raises(ValueError, match="independent"):
        evaluate()
    decision.update(reviewer="other", evidence_sha256="wrong")
    with pytest.raises(ValueError, match="exact evidence"):
        evaluate()
    report["operations"]["status"] = "NOT_EVALUATED"
    assert evaluate()["release_status"] == "NOT_EVALUATED"
