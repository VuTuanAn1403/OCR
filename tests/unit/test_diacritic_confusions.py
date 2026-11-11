"""diacritic_confusions: per-kind diacritic confusions on adjudicated GT."""
from collections import Counter

from scripts import diacritic_confusions as dc


def _counts():
    return {name: Counter() for name in
            ("ref_slots", "slot_errors", "pairs", "reference_chars", "spurious", "deleted_slots", "base_mismatch_slots")}


def test_confusions_name_the_kind_and_the_value_pair():
    counts = _counts()
    dc.confusions("HĐQT đặc", "HDQT đắc", counts)
    assert counts["slot_errors"] == Counter({"stroke": 1, "tone": 1})
    assert counts["pairs"] == Counter({"stroke: bar -> none": 1, "tone: dot_below -> acute": 1})
    assert counts["reference_chars"] == Counter({"Đ": 1, "ặ": 1})
    assert counts["ref_slots"]["all"] == 4  # Đ stroke, đ stroke, ặ shape + tone


def test_deletions_base_mismatches_and_spurious_marks_are_kept_apart():
    counts = _counts()
    dc.confusions("năm ba", "nm bá", counts)
    assert counts["deleted_slots"]["all"] == 1  # ă deleted
    assert counts["spurious"] == Counter({"tone: none -> acute": 1})
    counts = _counts()
    dc.confusions("độ", "đẹ", counts)
    assert counts["base_mismatch_slots"]["all"] == 2 and not counts["slot_errors"]
