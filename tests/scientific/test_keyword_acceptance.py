import hashlib
import json
import sys

import pytest

from benchmark.scientific_evaluation.keyword_acceptance import evaluate, inventory, main
from ocr_keywords.contract import count_report, dictionary_snapshot


@pytest.fixture
def example(tmp_path):
    dictionary = tmp_path / "keywords.txt"
    dictionary.write_text("trí tuệ\nO2O\n020\n", encoding="utf-8")
    snapshot = dictionary_snapshot(dictionary, version="fixture")
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    doc = tmp_path / "DOC"
    doc.mkdir()
    markdown = doc / "result.md"
    markdown.write_bytes("# Trang 1\r\nTRI\u0301 TUỆ o2o\r\n# Trang 2\r\ntrí tuệ 020".encode("utf-8-sig"))
    report = count_report(doc.name, "a" * 64, markdown, snapshot, [1, 2])
    (doc / "keyword_counts.json").write_text(json.dumps(report), encoding="utf-8")
    observed = inventory(doc, snapshot)
    keys = {row["keyword"]: row["id"] for row in observed["keywords"]}
    unit1 = {"unit_id": "region-1", "physical_page": 1, "bbox": [0, 0, 80, 16],
             "coordinate_space": "pdf_points_top_left", "transcription": "trí tuệ O2O",
             "keyword_occurrences": [{"id": "ref-1", "keyword_id": keys["trí tuệ"], "start": 0, "end": 7},
                                     {"id": "ref-2", "keyword_id": keys["O2O"], "start": 8, "end": 11}]}
    unit2 = {"unit_id": "cell-2", "physical_page": 2, "bbox": [0, 15, 90, 28],
             "coordinate_space": "pdf_points_top_left", "table_cell_id": "t1:0:0",
             "transcription": "trí tuệ 020",
             "keyword_occurrences": [{"id": "ref-3", "keyword_id": keys["trí tuệ"], "start": 0, "end": 7},
                                     {"id": "ref-4", "keyword_id": keys["020"], "start": 8, "end": 11}]}
    gt = {"schema_version": "keyword-source-gt-v1", "units": [unit1, unit2], "identity": {
        key: observed["identity"][key] for key in ("document_id", "pdf_sha256", "dictionary_sha256")}}
    attribution = [{**row, "unit_id": unit, "reference_id": f"ref-{number}"}
                   for number, (row, unit) in enumerate(zip(observed["occurrences"],
                                                          ("region-1", "region-1", "cell-2", "cell-2")), 1)]
    alignment = {"schema_version": "keyword-source-occurrences-v1", "identity": observed["identity"],
                 "reviewed_by": "fixture", "attributions": attribution}
    return doc, snapshot_path, observed, gt, alignment, keys


def test_cli_counts_matches_from_published_markdown_and_binds_frozen_gt(example, tmp_path, monkeypatch, capsys):
    doc, snapshot_path, observed, gt, alignment, keys = example
    assert observed["occurrences"][0] == {"keyword_id": keys["trí tuệ"], "start": 10, "end": 17}
    gt_path, alignment_path = tmp_path / "gt.json", tmp_path / "alignment.json"
    gt_path.write_text(json.dumps(gt), encoding="utf-8")
    alignment["ground_truth_sha256"] = hashlib.sha256(gt_path.read_bytes()).hexdigest()
    alignment_path.write_text(json.dumps(alignment), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["keyword_acceptance", str(doc), str(snapshot_path),
                                      "--ground-truth", str(gt_path), "--alignment", str(alignment_path)])
    assert main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "PASS" and len(result["correct"]) == 4
    assert result["unit_locations"]["cell-2"]["table_cell_id"] == "t1:0:0"
    gt_path.write_text(json.dumps(gt, indent=2), encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert "checksum mismatch" in capsys.readouterr().err


def test_equal_totals_with_a_repeated_reference_still_fail(example):
    _, _, observed, gt, alignment, keys = example
    alignment["attributions"][2].update(unit_id="region-1", reference_id="ref-1")
    result = evaluate(observed, gt, alignment)
    assert result["status"] == "FAIL"
    assert result["by_keyword"][keys["trí tuệ"]] == {
        "keyword": "trí tuệ", "correct": 1, "missing": 1, "extra": 1, "net_delta": 0}
    assert result["missing"][0]["id"] == "ref-3"


def test_unreviewed_unit_or_unattributed_match_prevents_pass(example):
    _, _, observed, gt, alignment, keys = example
    gt["units"][1]["keyword_occurrences"] = None
    alignment["attributions"][2]["reference_id"] = None
    alignment["attributions"].pop()
    result = evaluate(observed, gt, alignment)
    assert result["status"] == "NOT_EVALUATED"
    assert result["unannotated_unit_ids"] == ["cell-2"]
    assert len(result["unscored"]) == len(result["unattributed"]) == 1
    assert result["by_keyword"][keys["020"]]["net_delta"] is None


def test_empty_annotation_cannot_hide_a_transcribed_occurrence(example):
    _, _, observed, gt, alignment, _ = example
    gt["units"][1]["keyword_occurrences"] = []
    with pytest.raises(ValueError, match="adjudicated transcription"):
        evaluate(observed, gt, alignment)
