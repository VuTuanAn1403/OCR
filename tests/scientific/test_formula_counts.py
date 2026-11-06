"""Global formula counts retain source units and share the whole comparison family."""
from copy import deepcopy
import csv
import hashlib
import json

import pytest

from benchmark.scientific_evaluation import formula_alignment, formula_counts
from benchmark.scientific_evaluation.stratified_scorecard import evaluate
from src.ocr.collect.catalog import V1_FIELDS


def _write(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def projection(tmp_path):
    frame = {"coordinate_space": "pdf_points_top_left", "transforms": [], "width": 100, "height": 100}
    boxes = ([2, 2, 20, 10], [30, 2, 50, 10])
    labels = [{"id": kind, "bbox": box, "format": fmt, "content_raw": text, "placement": kind, "equation_label": None}
              for kind, box, fmt, text in (("inline", boxes[0], "TEXT", "−02=1"), ("display", boxes[1], "LATEX", "x=1"))]
    sample, units, catalog, documents = {"schema_version": "ocr-formula-scorecard-sample-v1", "documents": []}, [], [], []
    reports = {side: {"documents": [], "pairs": []} for side in ("baseline", "candidate")}
    for i in range(6):
        key, digest = f"doc{i}", f"{i:064x}"
        sample["documents"].append({"document_id": key, "pdf_sha256": digest, "pages": [1, 2]})
        catalog.append({"document_id": key, "relative_path": f"{key}.pdf", "company_id": f"c{i // 2}",
                        "sha256": digest, "pages": 2, "status": "OK"})
        documents.append({"document_id": key, "sha256": digest, "company_id": f"c{i // 2}", "split": "holdout"})
        for page, region, strata, metrics in (
            (1, "page", [], ["cer", "formula_detection_errors_per_gt"]),
            (2, "page", [], ["formula_detection_errors_per_gt", "formula_detection_recall"]),
            (1, "formula:inline", ["inline"], ["formula_detection_recall", "formula_text_cer", "formula_text_exact", "formula_critical_error_rate"]),
            (1, "formula:display", ["display"], ["formula_detection_recall", "formula_cdm_mean", "formula_critical_error_rate"])):
            units.append({"unit_id": f"{key}/{page}/{region}", "document_id": key, "pdf_sha256": digest,
                          "page": page, "region_id": region, "strata": strata, "metrics": metrics})
        for side, report in reports.items():
            present = i % 3 != 0 if side == "candidate" else i == 0
            items = [{"id": "prediction", "kind": "b", "block_type": "formula", "bbox": boxes[0], "text_raw": "−02=1"}] if present else []
            one, pairs = formula_alignment._align_page(key, {**frame, "page": 1, "items": items}, {**frame, "formulas": labels}, .5)
            negative, _ = formula_alignment._align_page(key, {**frame, "page": 2, "items": [
                {"id": "extra", "kind": "f", "latex": "x", "text_raw": "x", "bbox": boxes[0]}] if side == "baseline" else []},
                {**frame, "formulas": []}, .5)
            report["documents"].append({"document_id": key, "pdf_sha256": digest, "total_pages": 2,
                                        "completion_sha256": side, "pages": [one, negative]})
            report["pairs"].extend(pairs)
    sources, formula_sample, global_sample = (tmp_path / name for name in ("sources.csv", "formula-sample.json", "global-sample.json"))
    with sources.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, V1_FIELDS)
        writer.writeheader()
        writer.writerows(catalog)
    formula_hash = _write(formula_sample, sample)
    global_value = {"schema_version": "ocr-holdout-scorecard-sample-v1", "units": units}
    global_hash = _write(global_sample, global_value)
    paths = {}
    for side, report in reports.items():
        alignment, pairs = formula_alignment.write_alignment(tmp_path / side, {"schema_version": formula_alignment.REPORT_SCHEMA,
            "annotation_sha256": "a" * 64, "iou_threshold": .5, "localization_scope": "fixture",
            "holdout_sample_sha256": formula_hash, "documents": report["documents"], "cdm_pair_count": len(report["pairs"])}, report["pairs"])
        paths.update({f"{side}_alignment": alignment, f"{side}_pairs": pairs, f"{side}_critical": None, f"{side}_cdm": None})
    return global_sample, global_hash, sources, formula_sample, paths, global_value, documents, catalog


def test_projection_keeps_negative_false_positives_and_missing_formula_units(projection):
    args = projection[:5]
    counts = formula_counts.project_replay(*args)
    left = counts["baseline"]["records_by_metric"]
    right = counts["candidate"]["records_by_metric"]
    assert len(left["formula_detection_recall"]) == 18
    assert sum(row["denominator"] for row in left["formula_detection_recall"]) == 12
    negative = next(row for row in left["formula_detection_errors_per_gt"] if row["unit_id"] == "doc0/2/page")
    assert (negative["numerator"], negative["denominator"]) == (1, 0)
    assert sum(row["numerator"] for row in right["formula_detection_errors_per_gt"]) == 8
    missing = next(row for row in right["formula_text_cer"] if row["unit_id"] == "doc0/1/formula:inline")
    assert missing["status"] == "MISSING_OUTPUT" and missing["numerator"] == missing["denominator"] == 5
    assert all(row["status"] == "NOT_EVALUATED" for row in right["formula_cdm_mean"])


def test_projection_rejects_repinned_omission_stratum_and_denominator_duplication(projection):
    sample_path, _, sources, formula_sample, paths, sample, *_ = projection
    for transform in (lambda rows: rows.pop(), lambda rows: rows[-1].update(strata=["inline"]),
                      lambda rows: rows[0]["metrics"].append("formula_detection_recall")):
        changed = deepcopy(sample)
        transform(changed["units"])
        digest = _write(sample_path, changed)
        with pytest.raises(ValueError, match="sample must include|coverage or inline/display"):
            formula_counts.project_replay(sample_path, digest, sources, formula_sample, paths)


def test_formula_and_text_metrics_use_one_holm_family(projection):
    projected = formula_counts.project_replay(*projection[:5])
    sample, documents, catalog = projection[5:]
    counts = {side: value["records_by_metric"] for side, value in projected.items()}
    for side in counts:
        counts[side]["cer"] = [{"unit_id": f"doc{i}/1/page", "status": "MEASURED", "numerator":
            20 + i + (4 if i == 4 else 0) if side == "baseline" else i, "denominator": 100} for i in range(6)]
    tests = {f"{metric}:{stratum}": {"metric": metric, "stratum": stratum}
             for metric in formula_counts.METRICS for stratum in
             (("overall",) if metric == "formula_detection_errors_per_gt" else ("overall", "inline", "display"))}
    tests["cer:overall"] = {"metric": "cer", "stratum": "overall"}
    design = {"minimum_companies": 2, "minimum_documents": 2, "minimum_denominator": 2, "maximum_ci_width": 1,
              "power": {"target": .8, "pilot_company_influence_sd": .005, "detectable_gap": .03, "pilot_sha256": "c" * 64}}
    plan = {"comparisons": {key: deepcopy(design) for key in tests}}
    thresholds = {"comparisons": {key: {"threshold": .1, "basis": "point"} for key in tests}}
    margins = {"comparisons": dict.fromkeys(tests, .01)}
    settings = {"seed": 7, "resamples": 500, "minimum_independent_clusters": 2, "confidence_level": .95}
    result = evaluate(sample, {"documents": documents}, catalog, plan, {"tests": tests}, thresholds, margins,
                      *({"records_by_metric": counts[side]} for side in ("baseline", "candidate")), settings)
    text = result["comparisons"]["cer:overall"]
    assert len(result["comparisons"]) == 17
    assert text["noninferiority"]["p_value_for_holm"] == pytest.approx(1 / 501)
    assert text["noninferiority"]["p_value_holm"] == pytest.approx(17 / 501)
    assert result["comparisons"]["formula_cdm_mean:overall"]["absolute"]["status"] == "NOT_EVALUATED"


def test_gate_rejects_a_replay_from_another_candidate_before_loading_counts(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from benchmark.scientific_evaluation import formula_holdout_replay

    pair = {"id": "fixture", "pdf_sha256": "a" * 64, "total_pages": 2,
            "baseline_completion_sha256": "old", "candidate_completion_sha256": "current"}
    wrong = {**pair, "candidate_completion_sha256": "other"}
    monkeypatch.setattr(formula_holdout_replay, "run_replay", lambda *_: {"predictions": [wrong], "protocol_sha256": "protocol"})
    inputs = {"predictions": {"pairs": [pair], "baseline": {"batches": []}, "candidate": {"batches": []}},
              "verification": {"protocol_sha256": "protocol"}}
    args = SimpleNamespace(protocol=None, artifact_index=None, sample=None, formula_pdf_root=tmp_path / "inputs",
                           formula_output=tmp_path / "replay", report=tmp_path / "gate.json")
    with pytest.raises(ValueError, match="gate protocol or paired prediction inventory"):
        formula_counts.recompute_for_gate(inputs, args)
