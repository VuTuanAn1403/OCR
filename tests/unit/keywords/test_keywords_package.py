"""ocr_keywords: literal_v1 semantics, snapshot/report contract and the keyword
group validation. Imports only ocr_* packages, so it runs in an environment
with pydantic and pytest alone (no openpyxl, PyMuPDF, models or GPU)."""
import hashlib
import json
from pathlib import Path
import unicodedata

import pytest

from ocr_artifacts.hashing import sha256_file
from ocr_contracts.processing import KEYWORD_ARTIFACTS
from ocr_keywords.contract import count_report, dictionary_snapshot, validate_report, validate_snapshot
from ocr_keywords.counter import KeywordCounter
from ocr_keywords.validation import validate_keyword_group

ROOT = Path(__file__).resolve().parents[3]
V1 = ROOT / "config/keywords.txt"


def counts(text, keywords):
    return [item.count for item in KeywordCounter.count_keywords(text, keywords).keywords]


@pytest.mark.parametrize("text,keyword,expected", [
    ("CHUYỂN ĐỔI SỐ chuyển đổi số Chuyển Đổi Số", "chuyển đổi số", 3),          # case
    (unicodedata.normalize("NFD", "Dữ liệu lớn"), "dữ liệu lớn", 1),               # NFD text
    ("Dữ liệu lớn", unicodedata.normalize("NFD", "DỮ LIỆU LỚN"), 1),              # NFD keyword
    ("du lieu lon, dữ liệu lơn", "dữ liệu lớn", 0),                                # accents matter
    ("C++ và C++; (AI) [AI]", "c++", 2),                                            # regex metacharacters
    ("giá trị a.b và axb", "a.b", 1),                                               # '.' is literal
    ("chuyển\nđổi số; chuyển  đổi số", "chuyển đổi số", 0),                       # no whitespace joining
    ("Internet di động, Internet di độngx", "internet di động", 2),               # substring matches
    ("aaaa", "aa", 2),                                                              # non-overlapping
])
def test_literal_v1_counting(text, keyword, expected):
    assert counts(text, [keyword]) == [expected]


def test_distinct_keywords_count_independently_and_duplicates_collapse():
    report = KeywordCounter.count_keywords("số hóa, chuyển đổi số hóa", ["số hóa", "chuyển đổi số", "Số Hóa"])
    assert [(k.keyword, k.count) for k in report.keywords] == [("số hóa", 2), ("chuyển đổi số", 1)]


def test_v1_snapshot_keeps_88_display_and_87_canonical():
    snapshot = dictionary_snapshot(V1, "v1")
    validate_snapshot(snapshot)
    assert len(snapshot["display_columns"]) == 88 and len(snapshot["canonical_keywords"]) == 87
    duplicate = [i for i, word in enumerate(snapshot["display_columns"]) if word == "Internet di động"]
    assert len(duplicate) == 2
    assert snapshot["display_to_canonical"][duplicate[0]] == snapshot["display_to_canonical"][duplicate[1]]


def test_v1_rejects_another_dictionary_but_custom_versions_are_allowed(tmp_path):
    custom = tmp_path / "custom.txt"
    custom.write_text("Chuyển đổi số\nDữ liệu lớn\n", encoding="utf-8")
    with pytest.raises(ValueError, match="88 display"):
        dictionary_snapshot(custom, "v1")
    assert len(dictionary_snapshot(custom, "custom-2026")["canonical_keywords"]) == 2


def test_tampered_snapshot_is_rejected():
    snapshot = dictionary_snapshot(V1, "v1")
    snapshot["display_columns"][0] = "khác"
    with pytest.raises(ValueError, match="checksum"):
        validate_snapshot(snapshot)


def test_report_totals_and_display_mapping(tmp_path):
    snapshot = dictionary_snapshot(V1, "v1")
    text = tmp_path / "result.md"
    text.write_text("Internet di động. INTERNET DI ĐỘNG.", encoding="utf-8")
    report = count_report("doc", "0" * 64, text, snapshot, [1])
    validate_report(report, snapshot, text, "doc", "0" * 64)
    assert report["total_display_matches"] == report["total_canonical_matches"] + 2  # duplicated column
    assert sum(report["display_counts"]) == report["total_display_matches"]


@pytest.mark.parametrize("mutate", [
    lambda r: r["display_counts"].__setitem__(0, r["display_counts"][0] + 1),
    lambda r: r.__setitem__("total_canonical_matches", r["total_canonical_matches"] + 1),
    lambda r: r["canonical_counts"].pop(next(iter(r["canonical_counts"]))),
    lambda r: r.__setitem__("schema_version", "other"),
])
def test_modified_report_is_rejected(tmp_path, mutate):
    snapshot = dictionary_snapshot(V1, "v1")
    text = tmp_path / "result.md"
    text.write_text("Chuyển đổi số", encoding="utf-8")
    report = count_report("doc", None, text, snapshot, [1])
    mutate(report)
    with pytest.raises(ValueError):
        validate_report(report, snapshot, text)


def test_report_is_bound_to_result_md_bytes(tmp_path):
    snapshot = dictionary_snapshot(V1, "v1")
    text = tmp_path / "result.md"
    text.write_text("Chuyển đổi số", encoding="utf-8")
    report = count_report("doc", None, text, snapshot, [1])
    text.write_text("Chuyển đổi số ", encoding="utf-8")
    with pytest.raises(ValueError, match="identity"):
        validate_report(report, snapshot, text)


def keyword_group(tmp_path):
    snapshot = dictionary_snapshot(V1, "v1")
    out = tmp_path / "doc"
    out.mkdir()
    (out / "result.md").write_text("Chuyển đổi số", encoding="utf-8")
    report = count_report("doc", None, out / "result.md", snapshot, [1])
    (out / "keyword_counts.json").write_text(json.dumps(report), encoding="utf-8")
    seal = {"report_sha256": sha256_file(out / "keyword_counts.json")}
    (out / "keyword_receipt.json").write_text(json.dumps(seal), encoding="utf-8")
    (out / "keyword_validation.json").write_text(json.dumps({**seal, "status": "PASS"}), encoding="utf-8")
    (out / "count_keywords.xlsx").write_bytes(b"workbook checked by reporting")
    manifest = {"selected_pages": [1], "keyword_contract": {"schema_version": "keyword-contract-v1",
                "required_artifacts": list(KEYWORD_ARTIFACTS), "dictionary": snapshot}}
    return out, manifest


def test_complete_keyword_group_validates(tmp_path):
    out, manifest = keyword_group(tmp_path)
    report, snapshot = validate_keyword_group(out, manifest)
    assert report["document_id"] == "doc" and snapshot["keyword_set_version"] == "v1"


@pytest.mark.parametrize("name", KEYWORD_ARTIFACTS)
def test_losing_any_keyword_file_fails(tmp_path, name):
    out, manifest = keyword_group(tmp_path)
    (out / name).unlink()
    with pytest.raises(ValueError, match="missing"):
        validate_keyword_group(out, manifest)


def test_receipt_mismatch_and_v63_without_contract_fail(tmp_path):
    out, manifest = keyword_group(tmp_path)
    (out / "keyword_receipt.json").write_text(json.dumps({"report_sha256": hashlib.sha256(b"x").hexdigest()}),
                                              encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        validate_keyword_group(out, manifest)
    with pytest.raises(ValueError, match="missing"):
        validate_keyword_group(out, {"configuration": {"ocr_source_policy": "gpu_ocr_only_v1"}})
    assert validate_keyword_group(out, {"configuration": {}}) is None  # legacy output declares no group
