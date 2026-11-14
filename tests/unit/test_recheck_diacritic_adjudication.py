"""The §7.4 D recheck binds the sample and handles a third blind decision."""

from datetime import datetime, timedelta
import json

import pytest

from scripts import adjudicate_text_layer_diacritics as adjudicate
from scripts import recheck_diacritic_adjudication as recheck
from tests.unit.test_adjudicate_text_layer_diacritics import FONT, _answer, _measured, _seal_answers

pytestmark = pytest.mark.skipif(FONT is None, reason="no TrueType font with Vietnamese glyphs")


def _records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _write(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    return path


def _review_answers(manifest, records, at):
    return [{**r, "sheet_id": manifest["sheet_id"], "decided_at": at.isoformat(),
             "decision_id": r["decision_id"] + "-recheck"} for r in records]


@pytest.fixture
def rounds(tmp_path):
    source = tmp_path / "sheet"
    manifest = adjudicate.build_sheet(_measured(tmp_path), tmp_path / "pdfs", source, "reviewer")
    sealed = _seal_answers(tmp_path, "first", {"trị": ("TEXT_LAYER_CORRECT",), "Báo cáo năm": ("TEXT_LAYER_CORRECT",)})
    path = tmp_path / "sealed-first/seal.json"
    first = _records(path.parent / sealed["sealed_file"])
    reviewed = tmp_path / "blind"
    subset = recheck.build_recheck(source, path, reviewed)
    earliest = max(datetime.fromisoformat(row["decided_at"]) for row in first) + timedelta(days=7)
    assert subset["review_not_before"] == earliest.isoformat()
    return source, path, manifest, first, reviewed, subset, earliest


def test_recheck_does_not_show_old_choices_and_enforces_cooldown(rounds, tmp_path):
    source, seal, manifest, first, reviewed, second, earliest = rounds
    assert second["sheet_id"] != manifest["sheet_id"] and len(second["items"]) == 2
    html = (reviewed / "index.html").read_text(encoding="utf-8")
    assert "TEXT_LAYER" not in html and all(r["decision_id"] not in html for r in first)
    early = _write(tmp_path / "early.jsonl", _review_answers(second, first, earliest - timedelta(seconds=1)))
    with pytest.raises(ValueError, match="seven-day"):
        recheck.resolve_recheck(source, seal, early, tmp_path / "early-result")
    valid = _write(tmp_path / "second.jsonl", _review_answers(second, first, earliest))
    out = tmp_path / "result"
    result = recheck.resolve_recheck(source, seal, valid, out)
    assert result["status"] == "RECONCILED" and result["agreement"] == 1
    assert _records(out / "decisions-reconciled.jsonl") == first


def test_unresolved_after_a_third_different_decision(rounds, tmp_path):
    source, seal, manifest, first, _, second, earliest = rounds
    answers = _review_answers(second, first, earliest)
    answers[0].update(choice="BOTH_WRONG", corrected_text="Văn bản")
    second_path = _write(tmp_path / "second.jsonl", answers)
    followup = tmp_path / "third"
    review = recheck.resolve_recheck(source, seal, second_path, followup)
    assert review["status"] == "THIRD_REVIEW_REQUIRED" and review["agreement"] == .5
    third = json.loads((followup / "sheet.json").read_bytes())
    assert third["sheet_id"] not in (manifest["sheet_id"], second["sheet_id"])
    assert len(third["items"]) == 1
    changed = _review_answers(third, first[:1], earliest + timedelta(minutes=1))
    changed[0]["choice"] = "B_CORRECT" if first[0]["choice"] == "A_CORRECT" else "A_CORRECT"
    path = _write(tmp_path / "third.jsonl", changed)
    out = tmp_path / "resolved"
    report = recheck.resolve_recheck(source, seal, second_path, out, third_path=path)
    assert report["unresolved_after_third"] == [first[0]["item_id"]]
    decisions = _records(out / "decisions-reconciled.jsonl")
    assert adjudicate.check_records(manifest, decisions) == []
    assert {r["sheet_id"] for r in decisions} == {manifest["sheet_id"]}
    assert decisions[0]["choice"] == "UNRESOLVED"
    new = adjudicate.seal(source, [out / "decisions-reconciled.jsonl"], tmp_path / "new-seal")
    assert new["outcomes"]["UNRESOLVED"] == 1


def test_recheck_rejects_changed_sealed_bytes(rounds, tmp_path):
    source, seal, *_ = rounds
    report = json.loads(seal.read_bytes())
    records = seal.parent / report["sealed_file"]
    records.write_bytes(records.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="changed after sealing"):
        recheck.build_recheck(source, seal, tmp_path / "invalid")
