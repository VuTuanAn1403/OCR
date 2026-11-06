"""Counterexamples for occurrence identity, lifecycle and Unicode spans."""
from copy import deepcopy
import json

import pytest

from ocr_keywords.alias_map import (AliasDecision, find_alias_candidates,
    reconcile_keyword_tiers, load_alias_decisions, ALIAS_BUNDLE_SCHEMA)
from ocr_artifacts.digest import sha256_json_compact
from ocr_keywords.contract import count_report, dictionary_snapshot
from ocr_keywords.counter import KeywordCounter


def context(tmp_path, text="Treo hai câu đối mới.", words="đổi mới\n"):
    keys = tmp_path / "keys.txt"
    keys.write_text(words, encoding="utf-8")
    snapshot = dictionary_snapshot(keys, "custom-integrity")
    md = tmp_path / "result.md"
    md.write_text(text, encoding="utf-8")
    report = count_report("doc", "a" * 64, md, snapshot, [1])
    candidates = find_alias_candidates(text, snapshot)
    return snapshot, report, candidates


def decision(snapshot, report, candidate, **changes):
    data = dict(decision_id="accept-1", document_id=report["document_id"],
        pdf_sha256=report["pdf_sha256"], keyword_id=candidate.keyword_id,
        keyword=candidate.keyword, observed_text=candidate.observed_text,
        match_start=candidate.match_start, match_end=candidate.match_end,
        dictionary_snapshot_hash=snapshot["snapshot_sha256"],
        result_md_sha256=report["identity"]["result_md_sha256"],
        reviewer="operator-test", decided_at_utc="2026-11-06T01:00:00Z")
    data.update(changes)
    return AliasDecision(**data)


@pytest.mark.parametrize("different_id", [False, True])
def test_one_occurrence_is_counted_once(tmp_path, different_id):
    snap, report, candidates = context(tmp_path)
    first = decision(snap, report, candidates[0])
    second = first.model_copy(update={"decision_id": "accept-2"}) if different_id else first
    before = deepcopy(report)
    result = reconcile_keyword_tiers(report, snap, candidates * 2, [first, second])
    assert result["tier2_total_candidates"] == result["tier2_total_reviewed"] == 1
    assert report == before


@pytest.mark.parametrize("status", ["REJECTED", "REVOKED"])
@pytest.mark.parametrize("reverse", [False, True])
def test_latest_decision_wins_independently_of_bundle_order(tmp_path, status, reverse):
    snap, report, candidates = context(tmp_path)
    first = decision(snap, report, candidates[0])
    latest = decision(snap, report, candidates[0], decision_id="later", status=status,
                      decided_at_utc="2026-11-06T02:00:00Z")
    values = [latest, first] if reverse else [first, latest]
    result = reconcile_keyword_tiers(report, snap, candidates, values)
    assert result["tier2_total_reviewed"] == 0
    assert result["decisions"][0]["status"] == status


@pytest.mark.parametrize("reuse_id", [False, True])
def test_conflicting_decisions_fail_closed(tmp_path, reuse_id):
    snap, report, candidates = context(tmp_path)
    first = decision(snap, report, candidates[0])
    second = decision(snap, report, candidates[0], decision_id=first.decision_id if reuse_id else "other",
                      status="REVOKED")
    with pytest.raises(ValueError):
        reconcile_keyword_tiers(report, snap, candidates, [first, second])


@pytest.mark.parametrize("field,value", [
    ("pdf_sha256", "b" * 64), ("pdf_sha256", None),
    ("dictionary_snapshot_hash", "b" * 64), ("dictionary_snapshot_hash", ""),
    ("result_md_sha256", "b" * 64), ("result_md_sha256", ""),
    ("offset_space", "raw"), ("counting_policy", "alias_v1"),
    ("schema_version", "unknown"), ("status", "MAYBE"),
    ("reviewer", ""), ("decided_at_utc", "2026-11-06T01:00:00"),
])
def test_invalid_or_mismatched_decision_is_rejected(tmp_path, field, value):
    snap, report, candidates = context(tmp_path)
    with pytest.raises(ValueError):
        item = decision(snap, report, candidates[0], **{field: value})
        reconcile_keyword_tiers(report, snap, candidates, [item])


def test_missing_file_is_not_an_evaluated_empty_review(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_alias_decisions(tmp_path / "missing.json")


def test_literal_of_another_keyword_does_not_hide_a_candidate(tmp_path):
    snap, report, candidates = context(tmp_path, "công nghệ thông tìn", "công nghệ\ncông nghệ thông tin\n")
    assert report["total_canonical_matches"] == 1
    assert len(candidates) == 1
    assert candidates[0].keyword == "công nghệ thông tin"


@pytest.mark.parametrize("prefix", ["AB", "ßß", "ﬃﬃ", "A\u0301"])
def test_casefold_offsets_are_mapped_to_nfc_source(tmp_path, prefix):
    snap, report, candidates = context(tmp_path, prefix + " đổi mới đối mới")
    assert report["total_canonical_matches"] == 1
    assert len(candidates) == 1
    assert candidates[0].observed_text == "đối mới"


def test_missing_candidate_evaluation_stays_unknown(tmp_path):
    snap, report, _ = context(tmp_path)
    result = reconcile_keyword_tiers(report, snap, candidates=None, decisions=[])
    assert result["tier2_review_status"] == "NOT_EVALUATED"
    assert result["tier2_total_reviewed"] is None


def test_unbound_v1_bundle_is_not_silently_upgraded(tmp_path):
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps({"schema_version": "alias-decisions-bundle-v1", "decisions": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="re-review"):
        load_alias_decisions(path)


@pytest.mark.parametrize("as_dict", [False, True])
def test_supplied_literal_offsets_keep_keyword_and_unicode_scope(tmp_path, as_dict):
    text = "ßß công nghệ thông tìn đổi mới đối mới"
    snap, _, _ = context(tmp_path, text, "công nghệ\ncông nghệ thông tin\nđổi mới\n")
    values = list(KeywordCounter.iter_occurrences(text, [row["keyword"] for row in snap["canonical_keywords"]]))
    if as_dict:
        values = [{"keyword": word, "match_start": a, "match_end": b} for word, a, b in values]
    candidates = find_alias_candidates(text, snap, literal_matches=values)
    assert {item.observed_text for item in candidates} == {"công nghệ thông tìn", "đối mới"}


def test_model_copy_does_not_bypass_decision_validation(tmp_path):
    snap, report, candidates = context(tmp_path)
    invalid = decision(snap, report, candidates[0]).model_copy(update={"pdf_sha256": None})
    with pytest.raises(ValueError):
        reconcile_keyword_tiers(report, snap, candidates, [invalid])


def test_timezone_equivalent_conflicting_events_are_rejected(tmp_path):
    snap, report, candidates = context(tmp_path)
    first = decision(snap, report, candidates[0])
    second = decision(snap, report, candidates[0], decision_id="other", status="REJECTED",
                      decided_at_utc="2026-11-06T08:00:00+07:00")
    with pytest.raises(ValueError, match="Conflicting"):
        reconcile_keyword_tiers(report, snap, candidates, [first, second])


@pytest.mark.parametrize("field", ["status", "decided_at_utc"])
def test_import_does_not_invent_an_acceptance_or_review_time(tmp_path, field):
    snap, report, candidates = context(tmp_path)
    data = decision(snap, report, candidates[0]).model_dump()
    del data[field]
    path = tmp_path / "incomplete.json"
    path.write_text(json.dumps({"schema_version": ALIAS_BUNDLE_SCHEMA, "decisions": [data],
                               "bundle_sha256": sha256_json_compact([data])}), encoding="utf-8")
    with pytest.raises(ValueError, match="explicit review status and timestamp"):
        load_alias_decisions(path)
