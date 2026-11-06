"""Contract tests for literal formula counts and critical review custody."""
import hashlib
import json

import pytest

from benchmark.scientific_evaluation import formula_alignment, formula_content as content


def _pair(key, ref, pred, pred_format="TEXT"):
    return {"id": key, "reference": ref, "reference_format": "TEXT",
            "prediction": pred, "prediction_format": pred_format}


def _write(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _review(pairs_hash, *, key="a", changes=None):
    categories = {name: {"status": "NOT_APPLICABLE", "reason": "Fixture scope"} for name in content.CRITICAL_CATEGORIES}
    for name, status in (changes or {}).items():
        categories[name] = {"status": status, "reason": "Fixture judgement"}
    return {"schema_version": content.REVIEW_SCHEMA, "pairs_sha256": pairs_hash, "alignment_sha256": None,
            "reviewer": "fixture reviewer", "reviewed_at": "2026-11-04T12:00:00+07:00",
            "pairs": [{"id": key, "categories": categories}]}


def test_text_literal_preserves_sign_zero_scripts_and_units_and_keeps_missing(tmp_path):
    pairs = tmp_path / "pairs.json"
    _write(pairs, [_pair("a", "−020 ≤ x² kW", "-20 ≥ x₂ KW"),
                   _pair("b", "x=1", None), _pair("c", "é=1", "e\u0301=1")])
    result = content.evaluate(pairs)
    a, b, c = [row["text"] for row in result["details"]]
    assert [(row["reference"], row["prediction"]) for row in a["edits"]] == [
        ("−", None), ("0", "-"), ("≤", "≥"), ("²", "₂"), ("k", "K")]
    assert b["counts"]["deletions"] == 3 and b["cer"] == 1.0 and b["reason"] == "MISSING_PREDICTION"
    assert c["exact"] and c["edits"] == []
    assert result["text"]["measured_pairs"] == 3 and result["text"]["exact_rate"] == pytest.approx(1/3)
    assert result["critical"]["status"] == result["acceptance_status"] == "NOT_EVALUATED"
    assert result["critical"]["pairs_with_observed_error"] is None


def test_mixed_formats_and_missing_gt_do_not_disappear_from_text_cohort(tmp_path):
    path = tmp_path / "pairs.json"
    _write(path, [_pair("a", "a=1", "a=1"), _pair("b", "x²", "x^2", "LATEX"), _pair("c", None, "x=1")])
    report = content.evaluate(path)
    assert report["text"]["status"] == "NOT_EVALUATED"
    assert report["text"]["unscorable_pairs"] == 2 and report["text"]["exact_rate"] is None and report["text"]["micro_cer"] is None
    assert report["text"]["measured_subset_counts"]["hits"] == 3
    assert report["details"][2]["text"]["counts"] is None


def test_declared_critical_reviews_are_hash_bound_and_account_for_every_category(tmp_path):
    pairs_path, review_path = tmp_path / "pairs.json", tmp_path / "reviews.json"
    pair = _pair("a", "x²", "x₂")
    digest = _write(pairs_path, [pair])
    review = _review(digest, changes={"INDEX_OR_EXPONENT": "ERROR"})
    _write(review_path, review)
    report = content.evaluate(pairs_path, critical_review_path=review_path)
    assert report["critical"]["status"] == "MEASURED_DECLARED_REVIEWS"
    assert report["critical"]["categories"]["INDEX_OR_EXPONENT"]["observed_error_pairs"] == 1
    assert report["critical"]["categories"]["SIGN"]["observed_error_pairs"] is None
    assert not report["independent_ground_truth_verified"]
    _write(pairs_path, [{**pair, "prediction": "x"}])
    with pytest.raises(ValueError, match="identity"):
        content.evaluate(pairs_path, critical_review_path=review_path)
    _write(pairs_path, [pair])
    del review["pairs"][0]["categories"]["EQUATION_LABEL"]
    _write(review_path, review)
    with pytest.raises(ValueError, match="every category"):
        content.evaluate(pairs_path, critical_review_path=review_path)


def test_missing_prediction_and_printed_equation_label_cannot_be_reviewed_away(tmp_path):
    pairs_path, review_path = tmp_path / "pairs.json", tmp_path / "reviews.json"
    digest = _write(pairs_path, [{**_pair("a", "x=0", None), "reference_equation_label": "(2)"}])
    _write(review_path, _review(digest, changes={"RELATION": "MATCH"}))
    with pytest.raises(ValueError, match="cannot match"):
        content.evaluate(pairs_path, critical_review_path=review_path)
    _write(review_path, _review(digest, changes={"RELATION": "ERROR"}))
    with pytest.raises(ValueError, match="label assessment"):
        content.evaluate(pairs_path, critical_review_path=review_path)


def test_formula_content_binds_both_sides_to_generated_alignment(tmp_path):
    pairs_path, alignment_path = tmp_path / "cdm-pairs.json", tmp_path / "alignment.json"
    bbox = [1, 1, 20, 8]
    frame = {"page": 1, "coordinate_space": "pdf_points_top_left", "width": 30, "height": 30, "transforms": []}
    page = {**frame, "items": [{"id": "block", "kind": "b", "bbox": bbox, "text_raw": "(01 - 2)", "block_type": "formula"}]}
    ref = {"id": "ref", "bbox": bbox, "placement": "inline", "format": "TEXT", "content_raw": "(01 = 2)", "equation_label": None}
    aligned, pairs = formula_alignment._align_page("fixture", page, {**frame, "formulas": [ref]}, .5)
    alignment = {"schema_version": formula_alignment.REPORT_SCHEMA, "cdm_pair_count": 1,
                 "cdm_pairs_sha256": _write(pairs_path, pairs),
                 "documents": [{"document_id": "fixture", "pdf_sha256": "a"*64, "pages": [aligned]}]}
    _write(alignment_path, alignment)
    result = content.evaluate(pairs_path, alignment_path=alignment_path)
    assert result["details"][0]["source"]["prediction_id"] == "block"
    assert result["text"]["measured_subset_counts"]["substitutions"] == 1
    pairs[0]["prediction"] = "(01 = 2)"
    alignment["cdm_pairs_sha256"] = _write(pairs_path, pairs)
    _write(alignment_path, alignment)
    with pytest.raises(ValueError, match="prediction differs"):
        content.evaluate(pairs_path, alignment_path=alignment_path)


def test_holdout_critical_template_needs_a_submitted_human_image_declaration(tmp_path):
    pairs_path, alignment_path, reviews = (tmp_path / name for name in ("pairs.json", "alignment.json", "review.json"))
    frame = {"page": 1, "coordinate_space": "pdf_points_top_left", "width": 30, "height": 30, "transforms": []}
    ref = {"id": "ref", "bbox": [1, 1, 20, 8], "placement": "display", "format": "TEXT",
           "content_raw": "x²", "equation_label": "(2)"}
    page, pairs = formula_alignment._align_page("fixture", {**frame, "items": []}, {**frame, "formulas": [ref]}, .5)
    _write(alignment_path, {"schema_version": formula_alignment.REPORT_SCHEMA, "cdm_pair_count": len(pairs),
        "cdm_pairs_sha256": _write(pairs_path, pairs), "holdout_sample_sha256": "a" * 64,
        "documents": [{"document_id": "fixture", "pdf_sha256": "b" * 64, "pages": [page]}]})
    output = tmp_path / "template-output"
    assert content.main(["--pairs", str(pairs_path), "--alignment", str(alignment_path),
                         "--critical-template", "--output", str(output)]) == 0
    template = json.loads((output / "critical-template.json").read_bytes())
    assert template["reviewer"] is None and template["status"] == "BLANK"
    assert template["pairs"][0]["source"]["reference_equation_label"] == "(2)"
    assert all(row["status"] == "UNRESOLVED" for row in template["pairs"][0]["categories"].values())
    template.update(reviewer="fixture", reviewed_at="2026-11-04T12:00:00+07:00")
    _write(reviews, template)
    with pytest.raises(ValueError, match="human source-image declaration"):
        content.evaluate(pairs_path, alignment_path=alignment_path, critical_review_path=reviews)
    template.update(status="SUBMITTED", actor_type="HUMAN", source_images_checked=True)
    for row in template["pairs"][0]["categories"].values():
        row.update(status="ERROR", reason="Controlled missing-output fixture")
    _write(reviews, template)
    report = content.evaluate(pairs_path, alignment_path=alignment_path, critical_review_path=reviews)
    assert report["critical"]["status"] == "MEASURED_DECLARED_REVIEWS"
    assert report["critical"]["pairs_with_observed_error"] == 1
    assert report["acceptance_status"] == "NOT_EVALUATED"
