"""A 99.99% point gate uses raw counts and complete source coverage."""
import pytest

from benchmark.scientific_evaluation import diacritic_acceptance as gate


def test_extra_accent_on_unaccented_reference_contributes_to_corpus_errors():
    result = gate.evaluate_diacritic_acceptance(
        {"marked", "unmarked"}, {"marked": "đổi", "unmarked": "ma"},
        {"marked": "đổi", "unmarked": "má"},
    )
    assert result["status"] == "FAIL"
    assert result["counts"]["ref_diacritics"] == 3
    assert result["counts"]["insertion_errors"] == result["counts"]["diacritic_errors"] == 1


@pytest.mark.parametrize("reference,prediction", [({}, {}), ({"a": "đổi"}, {"a": None}),
    ({"a": None}, {"a": "đổi"}), ({"a": "ma"}, {"a": "má"}),
    ({"a": "đổi"}, {"a": "đổi", "untracked": "đổi"})])
def test_missing_coverage_or_denominator_cannot_pass(reference, prediction):
    assert gate.evaluate_diacritic_acceptance({"a"}, reference, prediction)["status"] == "NOT_EVALUATED"


@pytest.mark.parametrize("slots,expected", [(9_999, "FAIL"), (10_000, "PASS")])
def test_threshold_uses_integer_counts(monkeypatch, slots, expected):
    detail = gate.compute_der_detailed("đ", "d")
    monkeypatch.setattr(gate, "compute_der_detailed", lambda *_: {**detail, "ref_diacritics": slots})
    assert gate.evaluate_diacritic_acceptance({"a"}, {"a": "đ"}, {"a": "d"})["status"] == expected


def test_empty_transcription_is_counted_as_a_deletion():
    result = gate.evaluate_diacritic_acceptance({"a"}, {"a": "đ"}, {"a": ""})
    assert result["status"] == "FAIL" and result["compared_units"] == 1


def test_extra_combining_mark_cannot_disappear_from_gate():
    result = gate.evaluate_diacritic_acceptance({"a"}, {"a": "đổi"}, {"a": "đổ\u0309i"})
    assert result["status"] == "FAIL" and result["gate_errors"] == 1


def test_bad_reference_mark_requires_adjudication():
    result = gate.evaluate_diacritic_acceptance({"a"}, {"a": "đổ\u0309i"}, {"a": "đổi"})
    assert result["status"] == "NOT_EVALUATED" and result["invalid_reference_ids"] == ["a"]
