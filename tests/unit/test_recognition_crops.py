"""benchmark.challengers.recognition_crops: fixed-crop paired fix/harm (V8-065)."""
import pytest

from benchmark.challengers.recognition_crops import baseline_record, compare, eligible, predictions_by_crop

SHA = "a" * 64


def _crop(cid, reference, text):
    return {"crop_id": cid, "unit_id": f"u{cid}", "document_id": "DOC", "page": 1, "source_id": f"s{cid}",
            "bbox": [0, 0, 10, 5], "crop_sha256": SHA, "reference": reference, "baseline_text_raw": text,
            "baseline_confidence": 0.9, "baseline_engine": "vietnamese_seq2seq", "baseline_model_version": "LOCK"}


def test_eligible_needs_one_line_each_side_and_a_slot():
    unit = {"ocr_source_ids": ["a"], "reference_line_ids": ["r"], "dser_strict": {"ref_slots": 2}}
    assert eligible(unit)
    assert not eligible({**unit, "ocr_source_ids": ["a", "b"]})
    assert not eligible({**unit, "dser_strict": {"ref_slots": 0}})


def test_paired_effects_count_fixes_harms_and_missing_output():
    crops = [_crop("c1", "Hội đồng", "Hội dồng"), _crop("c2", "quản trị", "quản trị"), _crop("c3", "năm", "năm")]
    records = [baseline_record(c, "run") for c in crops]
    baseline = predictions_by_crop(records)
    candidate = {"c1": "Hội đồng", "c2": "quan tri", "c3": None}  # fix, harm, missing
    report = compare(crops, baseline, candidate)
    assert report["effects"]["dser_strict"] == {"fixed": 1, "harmed": 2, "still_wrong": 0, "preserved_correct": 0}
    assert report["totals"]["candidate"]["missing"] == 1 and report["rates"]["dser_strict"]["fix_rate"] == 1.0
    assert {row["crop_id"] for row in report["changed"]} == {"c1", "c2", "c3"}
    assert report["decision_options"] == ["INCONCLUSIVE"]


def test_changed_crop_bytes_and_non_canonical_records_stop_the_run():
    crop = _crop("c1", "Hội", "Hội")
    with pytest.raises(ValueError, match="crop bytes differ"):
        compare([crop], {"c1": "Hội"}, {"c1": "Hội"}, crop_sha256={"c1": "b" * 64})
    record = baseline_record(crop, "run")
    with pytest.raises(ValueError, match="non-canonical"):
        predictions_by_crop([{**record, "crop_sha256": "x"}])
    with pytest.raises(ValueError, match="duplicate"):
        predictions_by_crop([record, record])
