"""DSER_strict separates base-letter errors from diacritic errors (V8-020, spec 04 section 3)."""
import pytest

from benchmark.scientific_evaluation.evaluation_protocol import aggregate_text_metrics, text_metrics
from benchmark.scientific_evaluation.ocr_metric import (compute_der_detailed, compute_diacritic_metrics,
                                                        compute_dser_strict_detailed)


def test_base_letter_substitution_is_not_a_diacritic_error():
    # GT "ộ" read as "ẹ": the base letter changed, the dot below survived.
    v1 = compute_der_detailed("ộ", "ẹ")
    strict = compute_dser_strict_detailed("ộ", "ẹ")
    assert v1["diacritic_errors"] == 2 and v1["ref_diacritics"] == 2
    assert strict["dser_errors"] == 0 and strict["base_mismatch_slots"] == 2 and strict["ref_slots"] == 2


@pytest.mark.parametrize("reference,prediction,field", [
    ("má", "mà", "tone_errors"), ("mã", "ma", "tone_errors"), ("ơ", "o", "shape_errors"),
    ("đi", "di", "stroke_errors"), ("ă", "â", "shape_errors"),
])
def test_same_base_slot_changes_are_errors(reference, prediction, field):
    strict = compute_dser_strict_detailed(reference, prediction)
    assert strict[field] == 1 and strict["dser_errors"] == 1 and strict["base_mismatch_slots"] == 0


def test_deleted_reference_characters_keep_their_slots_as_errors():
    strict = compute_dser_strict_detailed("người", "ngi")
    assert strict["ref_slots"] == 3 and strict["deleted_slots"] == 3 and strict["dser_errors"] == 3


def test_spurious_and_uncomposed_marks_are_counted():
    spurious = compute_dser_strict_detailed("ma", "má")
    assert spurious["spurious_marks"] == 1 and spurious["dser_errors"] == 1 and spurious["dser"] is None
    detached = compute_dser_strict_detailed("đổi", "đổ\u0309i")
    assert detached["uncomposed_prediction_marks"] == 1 and detached["dser_errors"] == 1


def test_inserted_characters_are_character_errors_only():
    strict = compute_dser_strict_detailed("á", "áá")
    assert strict["inserted_char_marks"] == 1 and strict["dser_errors"] == 0


def test_nfc_differences_are_not_errors():
    decomposed = "Vie\u0302\u0323t"
    strict = compute_dser_strict_detailed("Việt", decomposed)
    assert strict["dser_errors"] == 0 and strict["ref_slots"] == 2


def test_both_metrics_share_one_alignment_and_keep_v1_unchanged():
    reference, prediction = "Báo cáo tài chính hợp nhất", "Bao cáo tải chính họp nhât"
    both = compute_diacritic_metrics(reference, prediction)
    assert both["der_vn_v1"] == compute_der_detailed(reference, prediction)
    assert both["dser_strict"] == compute_dser_strict_detailed(reference, prediction)
    assert both["dser_strict"]["dser_errors"] <= both["der_vn_v1"]["diacritic_errors"]


def test_text_metrics_aggregate_reports_dser_beside_der():
    records = [text_metrics("độ", "đẹ"), text_metrics("đổi", "đổi")]
    aggregate = aggregate_text_metrics(records)
    assert aggregate["counts"]["der"]["errors"] == 2
    strict = aggregate["counts"]["dser_strict"]
    assert strict["errors"] == 0 and strict["base_mismatch_slots"] == 2 and strict["reference_length"] == 6
    assert aggregate["micro_dser_strict"] == 0
