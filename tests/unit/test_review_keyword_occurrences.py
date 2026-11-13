"""Occurrence review fixtures test custody and scoring, not human GT quality."""
import json
from pathlib import Path
import unicodedata

import pymupdf
import pytest

from ocr_artifacts.hashing import sha256_file
from ocr_artifacts.completion import write_completion_marker
from ocr_keywords.contract import count_report, dictionary_snapshot
from scripts import review_keyword_occurrences as review
from scripts import serve_review_sheets as serve


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def sheet(tmp_path):
    pdf = tmp_path / "DOC.pdf"
    with pymupdf.open() as document:
        for _ in range(10):
            document.new_page(width=100, height=100)
        document.save(pdf)
    words = tmp_path / "keywords.txt"
    words.write_text("O2O\n", encoding="utf-8")
    snapshot = dictionary_snapshot(words, version="fixture")
    dictionary = tmp_path / "dictionary.json"
    write(dictionary, snapshot)
    doc = tmp_path / "DOC"
    doc.mkdir()
    markdown = doc / "result.md"
    markdown.write_text("# Trang 2\nBa\u0309ng ß O2O </script>\n# Trang 10\nO2O", encoding="utf-8")
    write(doc / "keyword_counts.json", count_report("DOC", sha256_file(pdf), markdown, snapshot, [2, 10]))
    observed = review.acceptance.inventory(doc, snapshot)
    keyword = observed["keywords"][0]["id"]
    gt = {"schema_version": "keyword-source-gt-v1", "identity": {k: observed["identity"][k]
          for k in ("document_id", "pdf_sha256", "dictionary_sha256")}, "units": [
        {"unit_id": "u2", "physical_page": 2, "bbox": [1, 1, 90, 20], "coordinate_space": "pdf_points_top_left",
         "transcription": "O2O", "keyword_occurrences": [{"id": "r2", "keyword_id": keyword, "start": 0, "end": 3}]},
        {"unit_id": "u10", "physical_page": 10, "bbox": [1, 1, 90, 20], "coordinate_space": "pdf_points_top_left",
         "transcription": "O2O", "keyword_occurrences": [{"id": "r10", "keyword_id": keyword, "start": 0, "end": 3}]}]}
    gt_path = tmp_path / "gt.json"
    write(gt_path, gt)
    output = tmp_path / "sheet"
    data = review.prepare(doc, dictionary, gt_path, pdf, output)
    assert [row["observed_text"] for row in data["occurrences"]] == ["o2o", "o2o"]
    assert data["occurrences"][0]["context_before"].endswith("bảng ss ")
    state = {"sheet_id": data["sheet_id"], "reviewer": "CONTROL_NOT_A_HUMAN_REVIEW", "decisions": {
        row["id"]: {"occurrence_id": row["id"], "unit_id": f"u{page}", "reference_id": f"r{page}"}
        for row, page in zip(data["occurrences"], [2, 10])}}
    decisions = tmp_path / "decisions.json"
    write(decisions, state)
    return output, decisions, data, state


def test_roundtrip_matches_and_missing_are_scored_without_claiming_quality(sheet, tmp_path):
    folder, decisions, data, state = sheet
    report = review.export(folder, decisions, tmp_path / "result")
    assert report["status"] == "PASS" and report["eligible_for_quality_acceptance"] is False
    assert len(report["correct"]) == 2
    # Equal totals can still contain a duplicated link and a missing occurrence.
    second = data["occurrences"][1]["id"]
    state["decisions"][second].update(unit_id="u2", reference_id="r2")
    write(decisions, state)
    report = review.export(folder, decisions, tmp_path / "duplicate")
    assert report["status"] == "FAIL" and len(report["missing"]) == len(report["extra"]) == 1


@pytest.mark.parametrize("change", ["partial", "foreign", "gt", "image", "sheet", "outside", "reference", "publication"])
def test_invalid_or_incomplete_reviews_fail_closed(sheet, tmp_path, change):
    folder, decisions, data, state = sheet
    key = data["occurrences"][0]["id"]
    if change == "partial":
        state["decisions"].pop(key)
    elif change == "foreign":
        state["sheet_id"] = "foreign"
    elif change == "gt":
        with open(data["source_paths"]["ground_truth"], "a", encoding="utf-8") as stream:
            stream.write(" ")
    elif change == "image":
        (folder / "pages/2.png").write_bytes(b"changed")
    elif change == "sheet":
        altered = review.read(folder / "sheet.json")
        altered["occurrences"][0]["context"] = "changed"
        write(folder / "sheet.json", altered)
    elif change == "outside":
        state["decisions"][key].update(unit_id=None, reference_id=None)
    elif change == "reference":
        state["decisions"][key]["reference_id"] = "r10"
    else:
        (Path(data["document"]) / "result.md").write_text("changed", encoding="utf-8")
    write(decisions, state)
    with pytest.raises((ValueError, RuntimeError)):
        review.export(folder, decisions, tmp_path / "invalid")
    assert not (tmp_path / "invalid").exists()


def test_sheet_escapes_input_has_no_prefilled_decisions_and_autosaves(sheet):
    folder, _, data, state = sheet
    html = (folder / "index.html").read_text(encoding="utf-8")
    assert html.count("</script>") == 1 and "\\u003c/script>" in html
    assert 'decisions:{},revisions:{}' in html
    key = "keyword-occurrence:" + data["sheet_id"]
    serve.save_state(folder, key, json.dumps(state))
    assert json.loads(serve.saved_states(folder)[key]) == state
    assert "keyword-occurrence:" in serve.inject(html)


def test_pending_review_deduplicates_reference_coverage_and_keeps_source_identity(sheet, tmp_path):
    literal_sheet, decisions, data, state = sheet
    observed = data["observed"]
    document = Path(data["document"])
    identity = observed["identity"]
    keyword_id = observed["keywords"][0]["id"]
    # Leave one GT occurrence missing in the literal score. The two pending
    # candidates link to that same reference, so they can add at most one.
    second = data["occurrences"][1]["id"]
    state["decisions"][second].update(unit_id=None, reference_id=None, outside_scope_reason="fixture")
    write(decisions, state)
    literal = tmp_path / "literal"
    review.export(literal_sheet, decisions, literal)
    markdown = unicodedata.normalize("NFC", (document / "result.md").read_text(encoding="utf-8"))
    start = markdown.rindex("O2O")
    write(document / "keyword_two_tier.json", {
        "schema_version": "keyword-two-tier-v3", "document_id": identity["document_id"],
        "pdf_sha256": identity["pdf_sha256"], "result_md_sha256": identity["result_md_sha256"],
        "dictionary_snapshot_hash": identity["dictionary_sha256"], "resolutions": [],
        "confusable_candidates": [{"keyword_id": keyword_id, "observed_text": "O2O", "match_start": start,
                                    "match_end": start + 3, "offset_space": "nfc"}],
        "retained_line_status": "EVALUATED",
        "retained_line_occurrences": [{"keyword_id": keyword_id, "page": 10, "source_id": "source-line",
                                       "bbox": [1, 1, 90, 20], "line_text": "O2O", "match_start": 0, "match_end": 3}],
    })
    write_completion_marker(document, "NEEDS_REVIEW")
    paths = data["source_paths"]
    pending_sheet = tmp_path / "pending"
    pending = review.prepare(document, paths["dictionary"], paths["ground_truth"], paths["pdf"], pending_sheet,
                             pending=True, literal_alignment=literal / "alignment.json")
    pending_decisions = tmp_path / "pending-decisions.json"
    write(pending_decisions, {"sheet_id": pending["sheet_id"], "reviewer": "CONTROL", "decisions": {
        row["id"]: {"occurrence_id": row["id"], "unit_id": "u10", "reference_id": "r10"}
        for row in pending["occurrences"]}})
    report = review.export(pending_sheet, pending_decisions, tmp_path / "pending-score")
    assert report["added_reference_ids"] == ["r10"] and report["remaining_reference_ids"] == []
    assert len(report["duplicate_or_unlinked_candidates"]) == 1
    assert report["quality_acceptance"] == "NOT_EVALUATED"

    with (document / "keyword_two_tier.json").open("a", encoding="utf-8") as handle:
        handle.write(" ")
    with pytest.raises(ValueError, match="verified publication"):
        review.export(pending_sheet, pending_decisions, tmp_path / "changed-pending-score")
