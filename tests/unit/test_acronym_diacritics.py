"""acronym_diacritics challenger: restore Đ only in whole, listed uppercase acronyms."""
from benchmark.challengers import acronym_diacritics as challenger


def test_listed_acronyms_get_their_stroke_back_and_edits_are_reported():
    text, edits = challenger.restore("Chủ tịch HDQT, thành viên BDH và DHDCD.")
    assert text == "Chủ tịch HĐQT, thành viên BĐH và ĐHĐCĐ."
    assert [(e["from"], e["to"]) for e in edits] == [("HDQT", "HĐQT"), ("BDH", "BĐH"), ("DHDCD", "ĐHĐCĐ")]
    assert edits[0]["start"] == 9 and edits[0]["end"] == 13


def test_other_tokens_are_left_alone():
    for text in ("HDQTX và AHDQT", "GD và HD", "HĐQT đã đúng", "hdqt", "Hội đồng"):
        assert challenger.restore(text) == (text, [])
    assert all(len(acronym) >= 3 and "Đ" in acronym for acronym in challenger.ACRONYMS)


def test_the_runner_counts_fix_and_harm_per_pdf(monkeypatch):
    from pathlib import Path

    from scripts import run_acronym_challenger as runner

    rows = [({"pdf": "a.pdf"}, {"prediction": "Chủ tịch HDQT"}, "Chủ tịch HĐQT"),
            ({"pdf": "b.pdf"}, {"prediction": "Chủ tịch HDQT"}, "Chủ tịch HDQT"),
            ({"pdf": "b.pdf"}, {"prediction": "không đổi"}, "không đổi")]
    monkeypatch.setattr(runner, "adjudicated_units", lambda path: ({}, ["a.pdf", "b.pdf"], rows))
    report = runner.evaluate(Path("seal.json"))
    assert report["by_pdf"]["a.pdf"]["units_fixed"] == 1 and report["by_pdf"]["a.pdf"]["units_harmed"] == 0
    assert report["by_pdf"]["b.pdf"]["units_harmed"] == 1 and report["by_pdf"]["b.pdf"]["units"] == 2
    assert report["totals"]["units_fixed"] == 1 and report["totals"]["units_harmed"] == 1
    assert report["totals"]["errors_before"] == sum(p["errors_before"] for p in report["by_pdf"].values())
