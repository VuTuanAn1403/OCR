"""Distinguish matching depth from choosing the right immediate parent."""
import json

import pytest

from benchmark.scientific_evaluation.table_hierarchy_metric import INPUT_SCHEMA, evaluate, main


def node(depth, parent=None):
    return {"depth": depth, "parent_id": parent}


def test_wrong_parent_and_missing_output_are_distinct_errors():
    labels = {"a": node(0), "b": node(0), "c": node(1, "a"), "d": node(2, "c")}
    predictions = {"a": node(0), "b": node(0), "c": node(1, "b")}
    result = evaluate(list(labels), labels, predictions)
    assert result["status"] == "EVALUATED"
    assert result["depth_accuracy"] == .75 and result["parent_accuracy"] == result["joint_accuracy"] == .5
    assert result["missing_prediction_ids"] == ["d"]


def test_unlabelled_row_or_outside_parent_keeps_accuracy_unknown():
    result = evaluate(["a", "b"], {"a": node(0)}, {"a": node(1, "x")})
    assert result["status"] == "NOT_EVALUATED" and result["depth_accuracy"] is None
    assert result["missing_reference_ids"] == ["b"] and result["unexpected_ids"] == ["x"]


def test_inconsistent_parent_depth_is_rejected():
    with pytest.raises(ValueError, match="disagrees with parent"):
        evaluate(["a", "b"], {"a": node(0), "b": node(2, "a")}, {})


def test_cli_reports_missing_reference_with_pinned_input(tmp_path, capsys):
    path = tmp_path / "example.json"
    path.write_text(json.dumps({"schema_version": INPUT_SCHEMA, "expected_ids": ["a"],
                                "references": {"a": None}, "predictions": {"a": node(0)}}), encoding="utf-8")
    assert main([str(path)]) == 1
    report = json.loads(capsys.readouterr().out)
    assert len(report["input_sha256"]) == 64 and report["quality_acceptance_status"] == "NOT_EVALUATED"
