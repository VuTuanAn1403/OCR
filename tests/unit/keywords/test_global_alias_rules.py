"""Counterexamples for global alias rules and three independent count streams."""
from copy import deepcopy
import json
import unicodedata

import pytest

from ocr_keywords.alias_map import AliasDecision
from ocr_keywords.contract import count_report, dictionary_snapshot
from ocr_keywords.global_rules import freeze_rules, validate_frozen_rules
from ocr_keywords.tiered import build_tiered_report


def rules_data(approved=None, disallowed=None):
    return {"schema_version": "alias-rules-v1", "updated_at_utc": "2026-11-06T07:00:00Z", "curator": "test-only",
            "normalization_policy": "NFC_CASEFOLD", "approved_global_aliases": approved or {},
            "disallowed_false_positives": disallowed or {}}


def context(tmp_path, text, data):
    keys = tmp_path / "keys.txt"
    keys.write_text("Chuyển đổi số\nĐổi mới\ntài chính số\n", encoding="utf-8")
    dictionary = dictionary_snapshot(keys, "custom-global")
    md = tmp_path / "result.md"
    md.write_text("# Trang 1\n\n" + text, encoding="utf-8")
    report = count_report("doc", "a"*64, md, dictionary, [1])
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    frozen = freeze_rules(path, dictionary)
    return dictionary, report, frozen, md


def test_three_streams_preserve_literal_and_unknowns(tmp_path):
    data = rules_data({"Chuyển đổi số": ["chuyển đối số", "CHUYỂN ĐỐI SỐ"], "Đổi mới": ["đồi mới"]}, {"Đổi mới": ["đời mới"]})
    dictionary, report, frozen, md = context(tmp_path,
        "CHUYỂN ĐỐI SỐ; chuyển đổi số; chuyễn đổi số; đời mới; đồi mới; đối mói; tài chính\n\nSố 020", data)
    before, raw = deepcopy(report), md.read_bytes()
    result = build_tiered_report(report, dictionary, md.read_text(encoding="utf-8"), rules=frozen, source_dir=tmp_path)
    assert len(frozen["rules"]) == 3
    assert result["tier1_total_literal"] == 1
    assert result["tier2_total_reviewed"] == 2
    assert result["total_pending"] == 3
    assert [r["review_status"] for r in result["resolutions"]].count("REJECTED") == 1
    assert report == before and md.read_bytes() == raw
    assert result["tier2_review_status"] == "PARTIAL_PENDING"
    assert all(r["page_number"] == 1 and r["bbox"] is None for r in result["resolutions"])
    assert result["quality_acceptance"] == "NOT_EVALUATED"


def test_occurrence_revocation_overrides_global_acceptance(tmp_path):
    dictionary, report, frozen, md = context(tmp_path, "chuyển đối số", rules_data({"Chuyển đổi số": ["chuyển đối số"]}))
    initial = build_tiered_report(report, dictionary, md.read_text(encoding="utf-8"), rules=frozen, source_dir=tmp_path)
    candidate, = initial["candidates"]
    decision = AliasDecision(decision_id="revoke", document_id="doc", pdf_sha256=report["pdf_sha256"],
        keyword_id=candidate["keyword_id"], keyword=candidate["keyword"], observed_text=candidate["observed_text"],
        match_start=candidate["match_start"], match_end=candidate["match_end"], status="REVOKED", reviewer="test",
        result_md_sha256=report["identity"]["result_md_sha256"], dictionary_snapshot_hash=dictionary["snapshot_sha256"])
    result = build_tiered_report(report, dictionary, md.read_text(encoding="utf-8"), decisions=[decision], rules=frozen, source_dir=tmp_path)
    assert result["tier2_total_reviewed"] == result["total_pending"] == 0
    assert result["resolutions"][0]["resolution_source"] == "occurrence_decision"


@pytest.mark.parametrize("text, accepted", [("công tác đối mới công nghệ", 1), ("tác đối mới công nghệ", 0),
                                            ("công tác\n\nđối mới công nghệ", 0), ("công tác\r\n \r\nđối mới công nghệ", 0),
                                            ("công tác đối mới công nghệp", 0)])
def test_context_rule_requires_literal_tokens_in_same_paragraph(tmp_path, text, accepted):
    data = rules_data({"Đổi mới": [{"alias": "đối mới", "required_before": "công tác", "required_after": "công nghệ"}]})
    dictionary, report, frozen, md = context(tmp_path, text, data)
    result = build_tiered_report(report, dictionary, md.read_text(encoding="utf-8"), rules=frozen, source_dir=tmp_path)
    assert result["tier2_total_reviewed"] == accepted
    assert result["total_pending"] == 1-accepted


@pytest.mark.parametrize("kind", ["conflict", "unknown-target", "numeric", "literal", "schema", "naive-time", "extra", "policy"])
def test_invalid_rule_files_fail_closed(tmp_path, kind):
    data = rules_data({"Chuyển đổi số": ["chuyển đối số"]})
    if kind == "conflict": data["disallowed_false_positives"] = {"CHUYỂN ĐỔI SỐ": ["CHUYỂN ĐỐI SỐ"]}
    if kind == "unknown-target": data["approved_global_aliases"] = {"không tồn tại": ["khong tồn tai"]}
    if kind == "numeric": data["approved_global_aliases"] = {"Chuyển đổi số": ["chuyển đối số 020"]}
    if kind == "literal": data["approved_global_aliases"] = {"Chuyển đổi số": ["CHUYỂN ĐỔI SỐ"]}
    if kind == "schema": data["schema_version"] = "alias-rules-v99"
    if kind == "naive-time": data["updated_at_utc"] = "2026-11-06T07:00:00"
    if kind == "extra": data["unreviewed"] = True
    if kind == "policy": data["normalization_policy"] = "FUZZY"
    with pytest.raises(ValueError): context(tmp_path, "chuyển đối số", data)


def test_nfd_and_casefold_expansion_preserve_nfc_offsets(tmp_path):
    alias = unicodedata.normalize("NFD", "CHUYỂN ĐỐI SỐ")
    dictionary, report, frozen, md = context(tmp_path, "ßß " + alias, rules_data({"Chuyển đổi số": [alias]}))
    result = build_tiered_report(report, dictionary, md.read_text(encoding="utf-8"), rules=frozen, source_dir=tmp_path)
    row, = result["resolutions"]
    nfc = unicodedata.normalize("NFC", md.read_text(encoding="utf-8"))
    assert nfc[row["match_start"]:row["match_end"]] == row["observed_text"] == "CHUYỂN ĐỐI SỐ"
    assert result["tier2_total_reviewed"] == 1


def test_snapshot_tampering_and_dictionary_changes_are_rejected(tmp_path):
    dictionary, report, frozen, md = context(tmp_path, "chuyển đối số", rules_data({"Chuyển đổi số": ["chuyển đối số"]}))
    changed = deepcopy(frozen)
    changed["rules"][0]["status"] = "REJECTED"
    with pytest.raises(ValueError): validate_frozen_rules(changed, dictionary)
    with pytest.raises(ValueError): validate_frozen_rules(frozen, {**dictionary, "snapshot_sha256": "b"*64})


def test_missing_rules_are_not_an_empty_evaluation(tmp_path):
    with pytest.raises(FileNotFoundError): freeze_rules(tmp_path / "absent.json", {})


def test_duplicate_json_keys_are_rejected(tmp_path):
    path = tmp_path / "duplicates.json"
    path.write_text('{"schema_version":"alias-rules-v1","schema_version":"alias-rules-v1"}', encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate JSON"):
        freeze_rules(path, {})


def test_shipped_ambiguous_two_word_alias_needs_context(tmp_path):
    from pathlib import Path
    root = Path(__file__).resolve().parents[3]
    dictionary = dictionary_snapshot(root / "config/keywords.txt", "v1")
    rules = freeze_rules(root / "config/alias_rules.json", dictionary)
    text = "# Trang 1\n\nTreo hai câu đối mới. Một ngọn đồi mới. SÁNG TẠO ĐỒI MỚI. đồi mới tài sản"
    md = tmp_path / "result.md"
    md.write_text(text, encoding="utf-8")
    report = count_report("source", "a"*64, md, dictionary, [1])
    result = build_tiered_report(report, dictionary, text, rules=rules, source_dir=tmp_path)
    assert result["tier2_total_reviewed"] == 2
    assert result["total_pending"] == 2
