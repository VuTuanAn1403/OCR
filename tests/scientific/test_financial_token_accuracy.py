"""Token-level errors are counted at their original source slots."""
import json

import pytest

from benchmark.scientific_evaluation.financial_token_accuracy import INPUT_SCHEMA, evaluate, main


def test_stock_and_currency_case_sensitive_accuracy_counts_missed_occurrences():
    gt = {"a": "VNM", "b": "VCB", "c": "FPT", "d": "HPG", "e": "VND", "f": "USD", "g": "VNĐ", "h": "USD"}
    prediction = {"a": "VNM", "b": "Vcb", "c": "FPT", "d": "HPG", "e": "UND", "f": "", "g": "VNĐ"}
    result = evaluate(set(gt), gt, prediction)
    assert result["status"] == "EVALUATED"
    assert result["counts"] == {"EXACT": 4, "CASE_ONLY": 1, "MISMATCH": 1, "MISSING_OUTPUT": 2}
    assert result["accuracy"] == .5
    assert result["quality_acceptance_status"] == "NOT_EVALUATED"


def test_nfc_equivalence_and_unicode_lookalike_are_distinct():
    result = evaluate({"a", "b"}, {"a": "TỶ", "b": "USD"}, {"a": "TY\u0309", "b": "UſD"})
    assert [row["outcome"] for row in result["units"]] == ["EXACT", "MISMATCH"]


def test_missing_reference_and_unknown_prediction_do_not_yield_accuracy():
    result = evaluate({"a", "b"}, {"a": "USD"}, {"a": "USD", "x": "VND"})
    assert result["status"] == "NOT_EVALUATED" and result["accuracy"] is None
    assert result["missing_reference_ids"] == ["b"] and result["unexpected_ids"] == ["x"]


def test_cli_pins_input_and_rejects_duplicate_occurrence_keys(tmp_path, capsys):
    p = tmp_path / "input.json"
    payload = {"schema_version": INPUT_SCHEMA, "expected_ids": ["a"], "references": {"a": "USD"},
               "predictions": {"a": "usd"}}
    p.write_text(json.dumps(payload), encoding="utf-8")
    assert main([str(p)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert len(report["input_sha256"]) == 64 and report["accuracy"] == 0
    p.write_text(p.read_text(encoding="utf-8").replace('"a": "usd"', '"a": "usd", "a": "USD"'), encoding="utf-8")
    with pytest.raises(SystemExit) as error:
        main([str(p)])
    assert error.value.code == 2
    assert "Duplicate JSON key" in capsys.readouterr().err
