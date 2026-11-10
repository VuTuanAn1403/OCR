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
