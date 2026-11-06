"""Adversarial tests for Tier 2 Alias Map and diacritic candidate reconciliation."""
from datetime import datetime, timezone
import json
from pathlib import Path
import pytest

from ocr_keywords.alias_map import (
    AliasCandidate,
    AliasDecision,
    find_alias_candidates,
    reconcile_keyword_tiers,
    save_alias_decisions,
    load_alias_decisions,
    TWO_TIER_REPORT_SCHEMA,
    ALIAS_DECISION_SCHEMA
)
from ocr_keywords.contract import dictionary_snapshot, count_report


ROOT = Path(__file__).resolve().parents[3]
KEYWORDS_FILE = ROOT / "config/keywords.txt"


def make_fixture(tmp_path, text, keywords="đổi mới\nchuyển đổi số\nchuyển đổi xanh\n"):
    key_file = tmp_path / "keys.txt"
    key_file.write_text(keywords, encoding="utf-8")
    snapshot = dictionary_snapshot(key_file, "custom-test")
    md_file = tmp_path / "result.md"
    md_file.write_text(text, encoding="utf-8")
    report = count_report("doc_01", "a" * 64, md_file, snapshot, [1])
    return snapshot, report, text


def test_anti_collision_exact_literal_matches_are_never_alias_candidates(tmp_path):
    text = "Doanh nghiệp đẩy mạnh đổi mới sáng tạo và chuyển đổi số toàn diện."
    snapshot, report, text = make_fixture(tmp_path, text)
    # Both "đổi mới" and "chuyển đổi số" match exactly literal_v1
    assert report["total_canonical_matches"] == 2
    candidates = find_alias_candidates(text, snapshot)
    # Since all occurrences are exact literal matches, candidates must be EMPTY
    assert len(candidates) == 0


def test_diacritic_anomaly_creates_candidate_without_modifying_literal_counts(tmp_path):
    text = "Doanh nghiệp đối mới quy trình và chuyển đổi xánh nông nghiệp."
    snapshot, report, text = make_fixture(tmp_path, text)
    # Literal count is 0 because "đối mới" != "đổi mới" and "chuyển đổi xánh" != "chuyển đổi xanh"
    assert report["total_canonical_matches"] == 0

    candidates = find_alias_candidates(text, snapshot)
    assert len(candidates) == 2
    observed = {c.observed_text: c.keyword for c in candidates}
    assert observed["đối mới"] == "đổi mới"
    assert observed["chuyển đổi xánh"] == "chuyển đổi xanh"

    # Reconcile tiers without any decisions (NOT_EVALUATED per document 13)
    two_tier = reconcile_keyword_tiers(report, snapshot, candidates)
    assert two_tier["schema_version"] == TWO_TIER_REPORT_SCHEMA
    assert two_tier["tier1_total_literal"] == 0
    assert two_tier["tier2_total_candidates"] == 2
    assert two_tier["tier2_review_status"] == "NOT_EVALUATED"
    assert two_tier["tier2_total_reviewed"] is None
    assert two_tier["tier2_reviewed_counts"] is None

    # Reconcile with evaluated empty decisions
    two_tier_empty = reconcile_keyword_tiers(report, snapshot, candidates, decisions=[])
    assert two_tier_empty["tier2_review_status"] == "EVALUATED"
    assert two_tier_empty["tier2_total_reviewed"] == 0
    assert all(v == 0 for v in two_tier_empty["tier2_reviewed_counts"].values())


def test_mixed_literal_and_anomaly_occurrence_separation(tmp_path):
    text = "Vừa đổi mới tư duy, vừa đối mới hành động trong thời kỳ mới."
    snapshot, report, text = make_fixture(tmp_path, text)
    # One literal match ("đổi mới")
    assert report["total_canonical_matches"] == 1

    candidates = find_alias_candidates(text, snapshot)
    # Only "đối mới" is a candidate; "đổi mới" is NOT a candidate
    assert len(candidates) == 1
    assert candidates[0].observed_text == "đối mới"
    assert candidates[0].keyword == "đổi mới"


def test_context_sentence_preservation_unconfirmed_stays_unreviewed(tmp_path):
    # "Treo hai câu đối mới." has valid Vietnamese meaning ("câu đối mới"),
    # but shares the folded skeleton of "đổi mới".
    text = "Nhân dịp Tết cổ truyền, gia đình treo hai câu đối mới trước cửa."
    snapshot, report, text = make_fixture(tmp_path, text)
    candidates = find_alias_candidates(text, snapshot)
    assert len(candidates) == 1
    assert candidates[0].observed_text == "đối mới"

    # Without human review, reviewed count remains NOT_EVALUATED!
    two_tier = reconcile_keyword_tiers(report, snapshot, candidates)
    assert two_tier["tier1_total_literal"] == 0
    assert two_tier["tier2_review_status"] == "NOT_EVALUATED"
    assert two_tier["tier2_total_reviewed"] is None
    assert two_tier["tier2_total_candidates"] == 1

    # When reviewed with zero accepted decisions, count is 0
    two_tier_reviewed = reconcile_keyword_tiers(report, snapshot, candidates, decisions=[])
    assert two_tier_reviewed["tier2_review_status"] == "EVALUATED"
    assert two_tier_reviewed["tier2_total_reviewed"] == 0


def test_operator_review_lifecycle_accepted_rejected_revoked(tmp_path):
    text = "Năm 2026 công ty tiếp tục đối mới phương thức quản trị."
    snapshot, report, text = make_fixture(tmp_path, text)
    candidates = find_alias_candidates(text, snapshot)
    assert len(candidates) == 1
    cand = candidates[0]

    # 1. Accept decision
    accepted_decision = AliasDecision(
        decision_id="dec_001",
        document_id="doc_01",
        pdf_sha256=report["pdf_sha256"],
        result_md_sha256=report["identity"]["result_md_sha256"],
        dictionary_snapshot_hash=snapshot["snapshot_sha256"],
        keyword_id=cand.keyword_id,
        keyword=cand.keyword,
        observed_text=cand.observed_text,
        match_start=cand.match_start,
        match_end=cand.match_end,
        status="ACCEPTED",
        reviewer="auditor_A",
        reason="OCR misread acute tone instead of hook"
    )
    res_accepted = reconcile_keyword_tiers(report, snapshot, candidates, [accepted_decision])
    assert res_accepted["tier1_total_literal"] == 0  # Tier 1 NEVER changes
    assert res_accepted["tier2_total_candidates"] == 1
    assert res_accepted["tier2_total_reviewed"] == 1

    # 2. Reject decision
    rejected_decision = accepted_decision.model_copy(update={"status": "REJECTED", "decision_id": "dec_002"})
    res_rejected = reconcile_keyword_tiers(report, snapshot, candidates, [rejected_decision])
    assert res_rejected["tier2_total_reviewed"] == 0

    # 3. Revoked decision
    revoked_decision = accepted_decision.model_copy(update={"status": "REVOKED", "decision_id": "dec_003"})
    res_revoked = reconcile_keyword_tiers(report, snapshot, candidates, [revoked_decision])
    assert res_revoked["tier2_total_reviewed"] == 0


def test_mismatched_locator_or_different_document_rejected(tmp_path):
    text = "Đối mới công nghệ."
    snapshot, report, text = make_fixture(tmp_path, text)
    candidates = find_alias_candidates(text, snapshot)
    cand = candidates[0]

    # Decision for a different document
    foreign_doc_decision = AliasDecision(
        decision_id="dec_wrong_doc",
        document_id="another_doc_99",
        pdf_sha256=report["pdf_sha256"],
        result_md_sha256=report["identity"]["result_md_sha256"],
        dictionary_snapshot_hash=snapshot["snapshot_sha256"],
        reviewer="operator-test",
        keyword_id=cand.keyword_id,
        keyword=cand.keyword,
        observed_text=cand.observed_text,
        match_start=cand.match_start,
        match_end=cand.match_end,
        status="ACCEPTED"
    )
    two_tier = reconcile_keyword_tiers(report, snapshot, candidates, [foreign_doc_decision])
    assert two_tier["tier2_total_reviewed"] == 0

    # Decision with corrupted offsets
    bad_offset_decision = AliasDecision(
        decision_id="dec_bad_offset",
        document_id="doc_01",
        pdf_sha256=report["pdf_sha256"],
        result_md_sha256=report["identity"]["result_md_sha256"],
        dictionary_snapshot_hash=snapshot["snapshot_sha256"],
        reviewer="operator-test",
        keyword_id=cand.keyword_id,
        keyword=cand.keyword,
        observed_text=cand.observed_text,
        match_start=999,
        match_end=1005,
        status="ACCEPTED"
    )
    with pytest.raises(ValueError, match="actual source candidate"):
        reconcile_keyword_tiers(report, snapshot, candidates, [bad_offset_decision])


def test_save_and_load_alias_decisions_with_tamper_detection(tmp_path):
    dec = AliasDecision(
        decision_id="dec_101",
        document_id="doc_01",
        pdf_sha256="a" * 64,
        result_md_sha256="b" * 64,
        dictionary_snapshot_hash="c" * 64,
        reviewer="operator-test",
        keyword_id="kw-test",
        keyword="đổi mới",
        observed_text="đối mới",
        match_start=10,
        match_end=17,
        status="ACCEPTED"
    )
    file_path = tmp_path / "decisions.json"
    save_alias_decisions(file_path, [dec])
    loaded = load_alias_decisions(file_path)
    assert len(loaded) == 1
    assert loaded[0].decision_id == "dec_101"
    assert loaded[0].observed_text == "đối mới"

    # Tamper with the file
    content = json.loads(file_path.read_text(encoding="utf-8"))
    content["decisions"][0]["status"] = "REJECTED"  # Tampered without updating bundle_sha256
    file_path.write_text(json.dumps(content), encoding="utf-8")

    with pytest.raises(ValueError, match="checksum mismatch"):
        load_alias_decisions(file_path)

