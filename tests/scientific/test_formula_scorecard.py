"""Formula summaries preserve the planned cohort and score custody."""
import csv
import hashlib
import json
from types import SimpleNamespace

import pytest

from benchmark.scientific_evaluation import formula_alignment, formula_cdm, formula_content, formula_scorecard as scorecard
from src.ocr.collect.catalog import V1_FIELDS


def _write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _label(key, bbox, fmt, text, placement):
    return {"id": key, "bbox": bbox, "format": fmt, "content_raw": text, "placement": placement, "equation_label": None}


def _prediction(key, bbox, text):
    return {"id": key, "kind": "b", "bbox": bbox, "block_type": "formula", "text_raw": text}


def _run(folder, *, baseline=False, leave_unlabelled=False):
    folder.mkdir()
    docs, pairs = [], []
    frame = {"coordinate_space": "pdf_points_top_left", "transforms": [], "width": 100, "height": 100}
    a, b = [2, 2, 10, 10], [20, 20, 35, 35]
    for name in ("one", "two", "three"):
        labels = [_label("inline", a, "TEXT", "−02=1", "inline"), _label("display", b, "LATEX", "x=1", "display")]
        observations = [] if baseline and name == "one" else [_prediction("p", a, "−02=1")]
        p1, pp = formula_alignment._align_page(name, {**frame, "page": 1, "items": observations},
                                               {**frame, "formulas": labels}, .5)
        p2, _ = formula_alignment._align_page(name, {**frame, "page": 2, "items": [_prediction("extra", a, "x")]},
                                             None if leave_unlabelled else {**frame, "formulas": []}, .5)
        pairs.extend(pp)
        docs.append({"document_id": name, "pdf_sha256": hashlib.sha256(name.encode()).hexdigest(), "total_pages": 2,
                     "completion_sha256": "a"*64 if baseline else "b"*64, "pages": [p1, p2]})
    pair_path, alignment_path = folder / "pairs.json", folder / "alignment.json"
    pair_hash = _write(pair_path, pairs)
    _write(alignment_path, {"schema_version": formula_alignment.REPORT_SCHEMA, "documents": docs, "annotation_sha256": "c"*64,
                            "iou_threshold": .5, "localization_scope": "fixture", "cdm_pairs_sha256": pair_hash,
                            "cdm_pair_count": len(pairs)})
    cdm = folder / "cdm"
    cdm.mkdir()
    runtime_hash = _write(cdm / "runtime.json", {"purpose": "count fixture only"})
    _write(cdm / "input.json", {"sha256": pair_hash})
    measured = {"status": "MEASURED", "reason": "MISSING_PREDICTION", "cdm_f1": 0.0,
                "tp": 0, "fp": 0, "fn": 3, "reference_characters": 3, "prediction_characters": 0}
    rows = [{"id": pair["id"], **(measured if pair["reference_format"] == "LATEX" else
                                  {"status": "NOT_EVALUATED", "cdm_f1": None})} for pair in pairs]
    _write(cdm / "comparison.json", {"schema_version": formula_cdm.SCHEMA, "method": formula_cdm.METHOD,
                                     "pairs": len(pairs), "runtime_sha256": runtime_hash, "details": rows})
    return alignment_path, pair_path, cdm, docs


def _args(tmp_path, *, partial=False, paired=True):
    candidate, pairs, cdm, docs = _run(tmp_path / "candidate", leave_unlabelled=partial)
    baseline, baseline_pairs, baseline_cdm = None, None, None
    if paired:
        baseline, baseline_pairs, baseline_cdm, _ = _run(tmp_path / "baseline", baseline=True, leave_unlabelled=partial)
    catalog = tmp_path / "sources.csv"
    with catalog.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=V1_FIELDS)
        writer.writeheader()
        for doc, issuer in zip(docs, ("issuer1", "issuer1", "issuer2")):
            name = doc["document_id"]
            writer.writerow({"document_id": name, "relative_path": f"{name}.pdf", "company_id": issuer,
                             "sha256": doc["pdf_sha256"], "pages": 2, "status": "OK"})
    return SimpleNamespace(sources=catalog, sample=None, seed=42, resamples=150, confidence=.95, min_companies=2,
                           candidate_alignment=candidate, candidate_pairs=pairs, candidate_critical=None, candidate_cdm=cdm,
                           baseline_alignment=baseline, baseline_pairs=baseline_pairs, baseline_critical=None, baseline_cdm=baseline_cdm)


def test_scorecard_keeps_negatives_and_pairs_by_company_not_document(tmp_path):
    args = _args(tmp_path)
    report = scorecard.evaluate(args)
    assert report["planned_pages"] == 6 and report["acceptance_status"] == "NOT_EVALUATED"
    assert report["candidate"]["localization"]["observed_counts"] == {"tp": 3, "fp": 3, "fn": 3}
    assert report["candidate"]["localization_by_company"]["issuer1"]["observed_counts"] == {"tp": 2, "fp": 2, "fn": 2}
    errors = report["comparisons"]["formula_detection_errors_per_gt:overall"]
    assert errors["candidate"]["micro"] == 1 and errors["baseline"]["micro"] == pytest.approx(7/6)
    bootstrap = errors["paired_bootstrap"]
    assert bootstrap["company_count"] == 2 and len(bootstrap["counts_by_document"]) == 3
    assert bootstrap["status"] == "MEASURED" and bootstrap["ci_unadjusted"] is not None
    inline = report["comparisons"]["formula_text_exact:inline"]
    assert inline["candidate"]["micro"] == 1 and inline["baseline"]["micro"] == pytest.approx(2/3)
    assert report["comparisons"]["formula_cdm_mean:display"]["candidate"]["micro"] == 0
    assert report["comparisons"]["formula_critical_error_rate:overall"]["candidate"]["micro"] is None


def test_unknown_page_blocks_complete_cohort_and_paired_ci(tmp_path):
    args = _args(tmp_path, partial=True)
    report = scorecard.evaluate(args)
    recall = report["comparisons"]["formula_detection_recall:inline"]
    assert recall["candidate"]["observed_numerator"] == 3 and recall["candidate"]["unscored_units"] == 3
    assert recall["candidate"]["micro"] is None
    assert recall["paired_bootstrap"]["status"] == "NOT_EVALUATED"
    assert report["candidate"]["localization"]["precision"] is None


def test_cdm_counts_and_pairing_identity_reject_changes(tmp_path):
    args = _args(tmp_path)
    artifact = args.candidate_cdm / "comparison.json"
    raw = json.loads(artifact.read_bytes())
    next(row for row in raw["details"] if row["status"] == "MEASURED")["cdm_f1"] = 1
    _write(artifact, raw)
    with pytest.raises(ValueError, match="differs from raw counts"):
        scorecard.evaluate(args)
    args.candidate_cdm = None
    args.baseline_alignment = args.candidate_alignment
    args.baseline_pairs = args.candidate_pairs
    args.baseline_cdm = None
    with pytest.raises(ValueError, match="distinct publications"):
        scorecard.evaluate(args)


def test_critical_counts_one_formula_even_if_several_categories_have_errors(tmp_path):
    args = _args(tmp_path, paired=False)
    pairs = json.loads(args.candidate_pairs.read_bytes())
    reviews = []
    for index, pair in enumerate(pairs):
        categories = {name: {"status": "NOT_APPLICABLE", "reason": "Fixture scope"}
                      for name in formula_content.CRITICAL_CATEGORIES}
        if index == 1:
            categories["RELATION"] = {"status": "ERROR", "reason": "Missing fixture relation"}
            categories["NUMBER"] = {"status": "ERROR", "reason": "Missing fixture number"}
        reviews.append({"id": pair["id"], "categories": categories})
    args.candidate_critical = tmp_path / "critical.json"
    _write(args.candidate_critical, {"schema_version": formula_content.REVIEW_SCHEMA,
            "pairs_sha256": hashlib.sha256(args.candidate_pairs.read_bytes()).hexdigest(),
            "alignment_sha256": hashlib.sha256(args.candidate_alignment.read_bytes()).hexdigest(),
            "reviewer": "fixture reviewer", "reviewed_at": "2026-11-04T12:00:00+07:00", "pairs": reviews})
    result = scorecard.evaluate(args)
    counts = result["comparisons"]["formula_critical_error_rate:overall"]["candidate"]
    assert counts["observed_numerator"] == 1 and counts["observed_denominator"] == 6
    assert result["acceptance_status"] == "NOT_EVALUATED"
