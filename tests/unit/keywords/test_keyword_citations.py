"""Counterexamples for citation fidelity; these do not measure OCR accuracy."""
import copy
import hashlib
import json
from pathlib import Path
import unicodedata

import pytest

from ocr_keywords.contract import count_report, dictionary_snapshot, validate_report

ROOT = Path(__file__).resolve().parents[3]


def fixture_report(tmp_path, text, keywords="học máy\n", pages=None, document=None):
    dictionary = tmp_path / "keys.txt"
    dictionary.write_text(keywords, encoding="utf-8")
    snapshot = dictionary_snapshot(dictionary, "test-citations")
    source = tmp_path / "result.md"
    source.write_text(text, encoding="utf-8")
    if document is not None:
        (tmp_path / "document.json").write_text(json.dumps(document), encoding="utf-8")
    report = count_report("doc", None, source, snapshot, [1] if pages is None else pages)
    assert validate_report(report, snapshot, source)
    return source, snapshot, report


def test_active_v1_matches_latest_user_list_and_preserves_original():
    active = ROOT / "config/keywords.txt"
    snapshot = dictionary_snapshot(active)
    assert hashlib.sha256(active.read_bytes()).hexdigest() == "63737b33615213aa2c640b87febd556fef6d47d69a7fee2f2cec3d15f30b9800"
    assert snapshot["keyword_set_version"] == "v1" and snapshot["keyword_set_revision"] == "2026-11-06"
    assert len(snapshot["display_columns"]) == len(snapshot["canonical_keywords"]) == 86
    words = snapshot["display_columns"]
    assert "điện toán" not in words and words.count("Internet di động") == 1
    assert len([w for w in words if w.startswith("điện toán ")]) == 9
    assert words[:4] == ["An ninh mạng", "B2B", "B2C", "blockchain"]
    assert words[-2:] == ["đồng thời cấp tỷ", "Đổi mới"]
    original = ROOT / "config/keywords-v1-original.txt"
    assert hashlib.sha256(original.read_bytes()).hexdigest() == "9a3b8c2bf02906d8abed56cc71e8869f51c497baa576d3f930a83b1cc436be1d"
    assert "keyword_set_revision" not in dictionary_snapshot(original)


def test_unicode_fold_expansion_and_nfd_keep_the_matched_source_spelling(tmp_path):
    _, _, report = fixture_report(tmp_path, "# Trang 1\nStraße " + unicodedata.normalize("NFD", "HỌC MÁY"),
                                  "SS\nhọc máy\n")
    assert [c["citation_keyword"] for c in report["citations"]] == ["ß", "HỌC MÁY"]
    assert [c["page_number"] for c in report["citations"]] == [1, 1]


def test_full_markdown_literal_matches_are_not_cleaned_or_double_counted(tmp_path):
    _, _, report = fixture_report(tmp_path, "# Trang 1\nhọc máy ![học máy](images/học máy.png) học  máy", "học máy\nHỌC MÁY\n")
    assert report["display_counts"] == [3, 3]
    assert report["total_display_matches"] == 6
    assert report["total_canonical_matches"] == len(report["citations"]) == 3


@pytest.mark.parametrize("text,pages", [
    ("học máy", [1]),
    ("# Trang 1\nhọc máy\n# Trang 1\nhọc máy", [1]),
    ("# Trang 1\nhọc máy", [2]),
])
def test_missing_ambiguous_or_inconsistent_page_markers_never_guess_page(tmp_path, text, pages):
    _, _, report = fixture_report(tmp_path, text, pages=pages)
    assert all(c["page_number"] is None and c["page_numbers"] == [] for c in report["citations"])


def test_context_stays_on_the_verified_physical_page(tmp_path):
    _, _, report = fixture_report(tmp_path, "# Trang 1\nendpage\n# Trang 2\nhọc máy suffix", pages=[1, 2])
    citation = report["citations"][0]
    assert citation["page_number"] == 2
    assert "endpage" not in citation["citation_before"]
    assert citation["citation_after"] == "suffix"


def test_logical_table_cites_all_source_pages_instead_of_rendered_first_page(tmp_path):
    document = {"table_stitch": {"logical_tables": [{"logical_table_id": "logical-0001",
        "html_path": "structures/tables/logical-0001.html",
        "projection": {"fragments": [{"page": 1}, {"page": 2}]}}]}}
    text = ("# Trang 1\n| label | value |\n| --- | --- |\n| học máy | 2 |\n\n"
            "*Bảng nối. [HTML đầy đủ](structures/tables/logical-0001.html)*\n\n# Trang 2\nother")
    _, _, report = fixture_report(tmp_path, text, pages=[1, 2], document=document)
    citation = report["citations"][0]
    assert citation["page_number"] is None and citation["page_numbers"] == [1, 2]
    assert citation["page_status"] == "LOGICAL_TABLE_SOURCE_PAGES"


@pytest.mark.parametrize("change", ["text", "page", "offset", "missing", "extra", "context", "revision"])
def test_tampered_citation_or_provenance_is_rejected(tmp_path, change):
    source, snapshot, report = fixture_report(tmp_path, "# Trang 1\nhọc máy")
    broken = copy.deepcopy(report)
    if change == "text":
        broken["citations"][0]["citation_keyword"] = "invented"
    elif change == "page":
        broken["citations"][0]["page_number"] = True
    elif change == "offset":
        broken["citations"][0]["match_start"] += 1
    elif change == "missing":
        broken["citations"] = []
    elif change == "extra":
        broken["citations"] *= 2
    elif change == "context":
        broken["citation_context"]["document_json_sha256"] = "f" * 64
    else:
        broken["keyword_set_revision"] = "invented"
    with pytest.raises(ValueError):
        validate_report(broken, snapshot, source)


def test_separate_analysis_text_uses_verified_extraction_context(tmp_path):
    source, snapshot, report = fixture_report(tmp_path, "# Trang 1\nhọc máy", document={})
    imported = tmp_path / "analysis/result.md"
    imported.parent.mkdir()
    imported.write_bytes(source.read_bytes())
    with pytest.raises(ValueError, match="provenance"):
        validate_report(report, snapshot, imported)
    assert validate_report(report, snapshot, imported, citation_source_dir=source.parent)
    (source.parent / "document.json").write_text('{"changed":true}', encoding="utf-8")
    with pytest.raises(ValueError, match="provenance"):
        validate_report(report, snapshot, imported, citation_source_dir=source.parent)
