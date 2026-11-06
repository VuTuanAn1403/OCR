"""Check paired denominators, missing output, blank GT and artifact custody."""
import copy
import hashlib
import json

import pytest

import benchmark.scientific_evaluation.degradation_metric as metric
from benchmark.scientific_evaluation.degradation_metric import INPUT_SCHEMA, evaluate, evaluate_bundle, main


def conditions():
    return [{"id": "upright", "kind": "control", "level": 0},
            *({"id": f"skew{angle}", "kind": "skew", "level": angle} for angle in (2, 5, 10)),
            {"id": "fade50", "kind": "contrast", "level": .5},
            {"id": "dust", "kind": "salt_pepper", "level": .01},
            {"id": "stain", "kind": "stain", "level": .1}]


def test_curves_count_errors_and_use_the_same_reference_at_every_level():
    refs = {"page1": "abcd", "page2": "12"}
    predictions = {c["id"]: dict(refs) for c in conditions()}
    predictions["skew2"]["page1"] = "abxd"  # One substitution.
    predictions["skew5"]["page1"] = "abcd!"  # One insertion.
    predictions["skew10"]["page2"] = ""  # Two deletions.
    predictions["fade50"]["page2"] = "13"
    predictions["dust"]["page1"] = "abcd.."
    predictions["stain"]["page1"] = "abcd."
    report = evaluate(list(refs), refs, predictions, conditions())
    points = {p["id"]: p for p in report["points"]}
    assert report["status"] == "EVALUATED" and report["quality_acceptance_status"] == "NOT_EVALUATED"
    assert {p["counts"]["reference_length"] for p in points.values()} == {6}
    assert points["skew2"]["counts"]["substitutions"] == 1
    assert points["skew5"]["cer_delta_from_control"] == 1 / 6
    assert points["skew5"]["cer_delta_per_abs_degree"] == (1 / 6) / 5
    assert points["skew10"]["counts"]["deletions"] == 2
    assert points["fade50"]["cer"] == 1 / 6
    assert points["dust"]["insertion_rate"] == 2 / 6
    assert points["stain"]["insertion_rate"] == 1 / 6
    assert points["dust"]["macro_unit_cer"] == .25


def test_missing_prediction_is_scored_as_deletion_instead_of_dropping_the_unit():
    report = evaluate(["a", "b"], {"a": "123", "b": "4"},
                      {"upright": {"a": "123", "b": "4"}, "skew2": {"a": None}}, conditions()[:2])
    point = report["points"][1]
    assert point["counts"]["reference_length"] == point["counts"]["deletions"] == 4
    assert point["cer"] == 1 and point["missing_output_ids"] == ["a", "b"]
    assert {u["status"] for u in point["units"]} == {"MISSING_OUTPUT"}


def test_missing_gt_cannot_create_a_rate_from_the_annotated_subset():
    report = evaluate(["a", "b"], {"a": "abc", "b": None}, {"upright": {"a": "abc"}}, conditions()[:2])
    assert report["status"] == "NOT_EVALUATED" and report["missing_reference_ids"] == ["b"]
    for point in report["points"]:
        assert point["counts"] is None and point["cer"] is None and point["cer_delta_from_control"] is None
        assert point["observed_counts"]["reference_length"] == 3
        assert point["units"][1]["counts"] is None
    empty = evaluate(["a"], {}, {}, conditions()[:2])
    assert all(p["observed_counts"] is None for p in empty["points"])


def test_annotated_empty_keeps_insertions_without_fabricating_a_zero_rate():
    report = evaluate(["blank"], {"blank": ""}, {"upright": {"blank": ""}, "skew2": {"blank": ".."}}, conditions()[:2])
    assert report["status"] == "EVALUATED"
    assert report["points"][0]["status"] == "EMPTY_REFERENCE"
    noisy = report["points"][1]
    assert noisy["status"] == "EMPTY_REFERENCE_INSERTIONS" and noisy["counts"]["insertions"] == 2
    assert noisy["insertion_rate"] is None and noisy["cer"] is None and noisy["cer_delta_per_abs_degree"] is None


def test_blank_page_insertions_are_kept_in_micro_counts_and_improvement_is_signed():
    refs = {"body": "abc", "blank": ""}
    predictions = {"upright": {"body": "xbc", "blank": ".."}, "skew2": dict(refs)}
    report = evaluate(list(refs), refs, predictions, conditions()[:2])
    before, after = report["points"]
    assert before["counts"]["insertions"] == 2 and before["counts"]["substitutions"] == 1
    assert before["cer"] == 1 and before["insertion_rate"] == 2 / 3
    assert before["macro_unit_denominator"] == 1
    assert after["cer_delta_from_control"] == -1 and after["cer_delta_per_abs_degree"] == -.5


def test_unknown_source_or_condition_cannot_be_silently_excluded():
    for prediction in ({"upright": {"extra": "x"}}, {"unregistered": {"a": "a"}}):
        report = evaluate(["a"], {"a": "a"}, prediction, conditions()[:2])
        assert report["status"] == "NOT_EVALUATED"
        assert all(p["counts"] is None and p["cer"] is None for p in report["points"])
    named = conditions()[:2]
    named[0]["id"] = "references"
    report = evaluate(["a"], {"a": "a", "outside": "b"}, {"references": {"a": "a"}}, named)
    assert report["status"] == "NOT_EVALUATED" and report["unexpected_reference_ids"] == ["outside"]


def test_strict_nfc_and_signed_angles_preserve_case_spacing_and_unclamped_errors():
    c = [{"id": "upright", "kind": "control", "level": 0}, {"id": "left", "kind": "skew", "level": -5}]
    report = evaluate(["a"], {"a": "Đ\u1ed5i"}, {"upright": {"a": "Đo\u0302\u0309i"}, "left": {"a": "Đổi!!!!"}}, c)
    assert report["points"][0]["cer"] == 0
    assert report["points"][1]["cer"] == 4 / 3 > 1
    assert report["points"][1]["cer_delta_per_abs_degree"] == (4 / 3) / 5
    report = evaluate(["a"], {"a": "Ab"}, {"upright": {"a": "ab"}, "left": {"a": " Ab"}}, c)
    assert report["points"][0]["counts"]["substitutions"] == 1
    assert report["points"][1]["counts"]["insertions"] == 1


def test_invalid_conditions_and_duplicate_source_ids_are_rejected():
    bad = [conditions()[:1], [conditions()[0], {"id": "x", "kind": "skew", "level": True}],
           [conditions()[0], {"id": "x", "kind": "contrast", "level": float("nan")}],
           [conditions()[0], {"id": "x", "kind": "contrast", "level": 1}],
           [conditions()[0], {"id": "x", "kind": "salt_pepper", "level": 0}],
           [conditions()[0], {"id": "x", "kind": "unknown", "level": 5}],
           conditions()[:2] + [copy.copy(conditions()[1])]]
    for rows in bad:
        with pytest.raises(ValueError):
            evaluate(["a"], {"a": "abc"}, {}, rows)
    with pytest.raises(ValueError, match="unique"):
        evaluate(["a", "a"], {"a": "abc"}, {}, conditions()[:2])


def bundle(tmp_path):
    def artifact(name, text):
        path = tmp_path / name
        path.write_bytes(text.encode("utf-8"))
        return {"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    gt = artifact("gt.txt", "Đổi\r\nmới")
    upright = artifact("upright.txt", "Đổi\nmới")
    noisy = artifact("noisy.txt", "Đổi\nmới.")
    payload = {"schema_version": INPUT_SCHEMA, "expected_ids": ["source:p1"], "conditions": conditions()[:2],
               "references": {"source:p1": gt}, "predictions": {"upright": {"source:p1": upright}, "skew2": {"source:p1": noisy}}}
    path = tmp_path / "input.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path, payload


def test_cli_checks_artifact_hashes_and_exposes_evaluator_identity(tmp_path, capsys):
    path, _ = bundle(tmp_path)
    output = tmp_path / "new" / "report.json"
    assert main([str(path), "--output", str(output)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report == json.loads(output.read_text(encoding="utf-8"))
    assert len(report["text_artifacts"]) == 3
    assert report["points"][0]["cer"] == 0 and report["points"][1]["counts"]["insertions"] == 1
    assert all(len(report[key]) == 64 for key in ("input_sha256", "evaluator_sha256", "text_metric_sha256"))
    (tmp_path / "noisy.txt").write_text("fixed output", encoding="utf-8")
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        evaluate_bundle(path)


def test_artifact_change_while_scoring_is_detected_and_report_is_not_overwritten(tmp_path, monkeypatch, capsys):
    path, _ = bundle(tmp_path)
    original = metric.compute_cer_detailed

    def change_during_score(*args, **kwargs):
        (tmp_path / "noisy.txt").write_text("changed after verification", encoding="utf-8")
        return original(*args, **kwargs)

    with monkeypatch.context() as context:
        context.setattr(metric, "compute_cer_detailed", change_during_score)
        with pytest.raises(ValueError, match="changed during evaluation"):
            evaluate_bundle(path)
    bundle(tmp_path)
    output = tmp_path / "existing.json"
    output.write_bytes(b"preserved")
    with pytest.raises(SystemExit) as exc:
        main([str(path), "--output", str(output)])
    assert exc.value.code == 2 and output.read_bytes() == b"preserved"
    capsys.readouterr()


def test_cli_rejects_duplicate_keys_and_returns_incomplete_for_null_gt(tmp_path, capsys):
    path, payload = bundle(tmp_path)
    payload["references"]["source:p1"] = None
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert main([str(path)]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "NOT_EVALUATED"
    path.write_text('{"schema_version":"x","schema_version":"y"}', encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        main([str(path)])
    assert exc.value.code == 2 and "Duplicate JSON key" in capsys.readouterr().err
