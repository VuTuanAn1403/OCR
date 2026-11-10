"""Blind A/B adjudication of OCR vs text-layer disagreements (GROUND_TRUTH_PROTOCOL 7.4 C)."""
import json

import pytest

from scripts import adjudicate_text_layer_diacritics as adjudicate
from scripts import measure_text_layer_diacritics as measure
from tests.unit.test_measure_text_layer_diacritics import FONT, _output, _seal, _setup, measurement_lock

pytestmark = pytest.mark.skipif(FONT is None, reason="no TrueType font with Vietnamese glyphs")


def _measured(tmp_path, sample=None, partial=False):
    pdf, sha, lock, boxes = _setup(tmp_path)
    seal = _seal(tmp_path, pdf, lock, "m")
    output, identity = _output(tmp_path, sha, [("Hội đồng quản tri", boxes["Hội đồng quản trị"])])
    report = measure.build(lock, [seal], identity, output, tmp_path / "pdfs", "text_corrected",
                           measurement_lock=measurement_lock(tmp_path, lock, sample=sample, partial=partial))
    path = tmp_path / "measurement.json"
    path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    return path


def test_sheet_refuses_a_measurement_whose_v2_lock_changed(tmp_path):
    path = _measured(tmp_path)
    report = json.loads(path.read_text(encoding="utf-8"))
    lock_path = tmp_path / "lock-v2-text_corrected.json"
    lock_path.write_text(lock_path.read_text(encoding="utf-8").replace('"reviewer": "reviewer"', '"reviewer": "other"'),
                         encoding="utf-8")
    with pytest.raises(adjudicate.measurement_lock_v2.LockError, match="lock bytes changed"):
        adjudicate.build_sheet(path, tmp_path / "pdfs", tmp_path / "adj-x", "reviewer")
    del report["measurement_lock"]
    path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(adjudicate.measurement_lock_v2.LockError, match="no v2 measurement lock"):
        adjudicate.build_sheet(path, tmp_path / "pdfs", tmp_path / "adj-y", "reviewer")


def _answer(sheet, key, item, outcome, corrected=None):
    side = key[item["item_id"]]["A"]
    choice = {"TEXT_LAYER_CORRECT": "A_CORRECT" if side == "TEXT_LAYER" else "B_CORRECT",
              "OCR_CORRECT": "B_CORRECT" if side == "TEXT_LAYER" else "A_CORRECT"}.get(outcome, outcome)
    return {"schema_version": adjudicate.RECORD_SCHEMA, "decision_id": item["item_id"] + "#r1", "sheet_id": sheet["sheet_id"],
            "item_id": item["item_id"], "crop_sha256": item["crop_sha256"], "a": item["a"], "b": item["b"],
            "choice": choice, "corrected_text": corrected, "reviewer": "reviewer",
            "decided_at": "2026-11-11T09:00:00+07:00", "tool_commit": None}


def _seal_answers(tmp_path, name, outcomes):
    sheet_dir = tmp_path / "sheet"
    sheet = json.loads((sheet_dir / "sheet.json").read_text(encoding="utf-8"))
    key = json.loads((sheet_dir / "ab_key.json").read_text(encoding="utf-8"))["items"]
    by_text = {key[item["item_id"]]["text_layer"]: item for item in sheet["items"]}
    records = [_answer(sheet, key, by_text[text], *outcome) for text, outcome in outcomes.items()]
    path = tmp_path / f"{name}.jsonl"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    return adjudicate.seal(sheet_dir, [path], tmp_path / f"sealed-{name}")


def test_sheet_hides_which_side_is_ocr(tmp_path):
    sheet = adjudicate.build_sheet(_measured(tmp_path), tmp_path / "pdfs", tmp_path / "sheet", "reviewer")
    key = json.loads((tmp_path / "sheet" / "ab_key.json").read_text(encoding="utf-8"))["items"]
    assert sorted(segment["text_layer"] for segment in key.values()) == ["Báo cáo năm", "trị"]
    assert {(segment["text_layer"], segment["ocr"]) for segment in key.values()} == {("trị", "tri"), ("Báo cáo năm", "")}
    html = (tmp_path / "sheet" / "index.html").read_text(encoding="utf-8")
    assert "TEXT_LAYER" not in html and "text_layer" not in html and sheet["sheet_id"] in html
    assert all({item["a"], item["b"]} == {key[item["item_id"]]["text_layer"], key[item["item_id"]]["ocr"]} for item in sheet["items"])


def test_seal_recounts_after_corrected_references(tmp_path):
    adjudicate.build_sheet(_measured(tmp_path), tmp_path / "pdfs", tmp_path / "sheet", "reviewer")
    report = _seal_answers(tmp_path, "one", {"trị": ("TEXT_LAYER_CORRECT",), "Báo cáo năm": ("OCR_CORRECT",)})
    # trị stays an OCR error; the reviewer says the second line is not on the image, so its slots leave the reference
    assert report["dser_strict_after_adjudication"] == {"errors": 1, "slots": 7, "rate": 1 / 7, "count": "every item adjudicated"}
    assert report["estimate"] is None and report["sample"]["size"] == report["sample"]["population"] == 2
    assert report["gt_error_items"] == 1 and report["outcomes"] == {"TEXT_LAYER_CORRECT": 1, "OCR_CORRECT": 1}
    report = _seal_answers(tmp_path, "two", {"trị": ("BOTH_WRONG", "trí"), "Báo cáo năm": ("UNRESOLVED",)})
    # both wrong: reference fixed to trí, OCR "tri" still misses the tone; unresolved keeps the 3 deleted slots
    assert report["dser_strict_after_adjudication"]["errors"] == 4
    assert report["gt_error_items"] == 1


def test_seal_requires_every_item_and_a_text_for_both_wrong(tmp_path):
    adjudicate.build_sheet(_measured(tmp_path), tmp_path / "pdfs", tmp_path / "sheet", "reviewer")
    with pytest.raises(ValueError, match="have no decision"):
        _seal_answers(tmp_path, "partial", {"trị": ("TEXT_LAYER_CORRECT",)})
    with pytest.raises(ValueError, match="BOTH_WRONG needs"):
        _seal_answers(tmp_path, "empty", {"trị": ("BOTH_WRONG", ""), "Báo cáo năm": ("UNRESOLVED",)})


def test_a_locked_sample_puts_seeded_items_on_the_sheet_and_counts_the_rest_as_errors(tmp_path):
    sheet = adjudicate.build_sheet(_measured(tmp_path, sample=1), tmp_path / "pdfs", tmp_path / "sheet", "reviewer")
    assert sheet["sample"] == {**sheet["sample"], "size": 1, "population": 2, "requested": 1}
    key_file = json.loads((tmp_path / "sheet" / "ab_key.json").read_text(encoding="utf-8"))
    assert len(key_file["items"]) == 1 and len(key_file["unsampled"]) == 1
    ranks = sorted(list(key_file["items"]) + list(key_file["unsampled"]),
                   key=lambda item_id: adjudicate.sample_rank(key_file["seed"], item_id))
    assert [item["item_id"] for item in sheet["items"]] == ranks[:1]  # the lowest seeded rank, not a choice
    item = sheet["items"][0]
    path = tmp_path / "sample.jsonl"
    record = _answer(sheet, key_file["items"], item, "TEXT_LAYER_CORRECT")
    path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    report = adjudicate.seal(tmp_path / "sheet", [path], tmp_path / "sealed-sample")
    assert report["outcomes"] == {"TEXT_LAYER_CORRECT": 1, "UNRESOLVED_NOT_SAMPLED": 1}
    assert report["dser_strict_after_adjudication"]["errors"] == 4  # nothing left out is forgiven
    assert report["estimate"]["status"] == "ESTIMATE_NOT_A_GATE"
    assert report["estimate"]["estimated_errors_after_full_adjudication"] == 4
    share = report["sample_shares"]["TEXT_LAYER_CORRECT"]
    assert (share["count"], share["of"], share["upper"]) == (1, 1, 1.0) and 0 < share["lower"] < 1


def _decide_first(tmp_path, sheet_dir, outcome):
    sheet = json.loads((sheet_dir / "sheet.json").read_text(encoding="utf-8"))
    key = json.loads((sheet_dir / "ab_key.json").read_text(encoding="utf-8"))["items"]
    path = sheet_dir.parent / f"{sheet_dir.name}-first.jsonl"
    record = _answer(sheet, key, sheet["items"][0], outcome)
    path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def test_a_partial_lock_seals_a_part_decided_sheet_and_counts_the_rest_as_errors(tmp_path):
    adjudicate.build_sheet(_measured(tmp_path, partial=True), tmp_path / "pdfs", tmp_path / "sheet", "reviewer")
    report = adjudicate.seal(tmp_path / "sheet", [_decide_first(tmp_path, tmp_path / "sheet", "OCR_CORRECT")],
                             tmp_path / "sealed-partial")
    assert report["outcomes"]["UNRESOLVED_NOT_DECIDED"] == 1 and report["estimate"]["status"] == "NOT_ESTIMATED"
    assert report["sample_shares_scope"] == "descriptive for the decided items only"
    document = report["documents"][0]
    assert (document["items"], document["decided"], document["fully_adjudicated"]) == (2, 1, False)
    assert document["errors"] == report["dser_strict_after_adjudication"]["errors"]


def test_without_a_partial_lock_every_item_needs_a_decision(tmp_path):
    adjudicate.build_sheet(_measured(tmp_path), tmp_path / "pdfs", tmp_path / "sheet", "reviewer")
    with pytest.raises(ValueError, match="1 items have no decision"):
        adjudicate.seal(tmp_path / "sheet", [_decide_first(tmp_path, tmp_path / "sheet", "OCR_CORRECT")], tmp_path / "sealed")


def test_decisions_move_to_a_rebuilt_sheet_only_when_the_items_are_identical(tmp_path):
    from scripts import migrate_adjudication_decisions as migrate
    measured = _measured(tmp_path, partial=True)
    adjudicate.build_sheet(measured, tmp_path / "pdfs", tmp_path / "old", "reviewer")
    adjudicate.build_sheet(measured, tmp_path / "pdfs", tmp_path / "new", "reviewer")  # same units, same seed
    decisions = _decide_first(tmp_path, tmp_path / "old", "OCR_CORRECT")
    result = migrate.migrate(tmp_path / "old", tmp_path / "new", [decisions])
    moved = result["records"][0]
    assert moved["migrated_from_sheet"] == result["from_sheet"] and moved["sheet_id"] == result["to_sheet"]
    new_sheet = json.loads((tmp_path / "new" / "sheet.json").read_text(encoding="utf-8"))
    assert adjudicate.check_records(new_sheet, [moved], allow_missing=True) == []
    record = json.loads(decisions.read_text(encoding="utf-8"))
    decisions.write_text(json.dumps({**record, "a": "other"}, ensure_ascii=False) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="other strings or another crop"):
        migrate.migrate(tmp_path / "old", tmp_path / "new", [decisions])
