"""compare_text_layer_runs.paired_units: per-unit DSER fix/harm between two runs."""
from scripts.compare_text_layer_runs import paired_units


def _unit(uid, reference, prediction, errors, slots=2):
    return {"unit_id": uid, "reference": reference, "prediction": prediction,
            "dser_strict": {"dser_errors": errors, "ref_slots": slots}}


def test_units_pair_by_id_and_reference_and_nothing_is_dropped():
    base = [_unit("u1", "Hội đồng", "Hội dồng", 1), _unit("u2", "quản trị", "quản trị", 0),
            _unit("u3", "năm", "năm", 0), _unit("u4", "tài", "tai", 1), _unit("u5", "x", "x", 0)]
    cand = [_unit("u1", "Hội đồng", "Hội đồng", 0), _unit("u2", "quản trị", "quan tri", 2),
            _unit("u3", "năm", "năm", 0), _unit("u4", "tài sản", "tai", 1), _unit("u6", "y", "y", 0)]
    effects, totals, changed = paired_units(base, cand)
    assert effects == {"fixed": 1, "harmed": 1, "preserved_correct": 1, "reference_differs": 1,
                       "only_baseline": 1, "only_candidate": 1}
    assert totals == {"baseline_errors": 1, "candidate_errors": 2, "slots": 6, "units": 3}
    assert {row["unit_id"] for row in changed} == {"u1", "u2"}
