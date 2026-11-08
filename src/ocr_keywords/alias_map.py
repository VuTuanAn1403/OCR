"""Two-tier keyword analytics and alias decision reconciliation.

Preserves `literal_v1` exact counts completely separate from diacritic alias
candidates and operator-reviewed decisions, per architecture document 13.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ocr_artifacts.atomic_io import atomic_write_json
from ocr_artifacts.digest import sha256_json_compact
from ocr_keywords.counter import KeywordCounter

DIACRITIC_REASON_PREFIX = "Vietnamese diacritic anomaly"
_WORDS = re.compile(r"(?:[^\W\d_]|[\u0300-\u036f])+", re.UNICODE)


def _fold(word: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", word.casefold())
                   if not unicodedata.combining(c)).replace("đ", "d")


SINGLE_WORD_VARIANT_POLICY = "single-word-variant-review-v1"
SINGLE_WORD_VARIANT_REASON = ("Single-word diacritic variant: Vietnamese homographs are common, "
                              "so it is listed for review and never counted")
ALIAS_DECISION_SCHEMA = "alias-decision-v2"
ALIAS_BUNDLE_SCHEMA = "alias-decisions-bundle-v2"
TWO_TIER_REPORT_SCHEMA = "keyword-two-tier-v2"


class AliasCandidate(BaseModel):
    """An unconfirmed diacritic variation detected by phonetic folding."""
    candidate_id: str
    keyword_id: str
    keyword: str
    observed_text: str
    match_start: int
    match_end: int
    reason: str
    scope: Literal["occurrence"] = "occurrence"
    offset_space: Literal["nfc"] = "nfc"


class AliasDecision(BaseModel):
    """An operator verification decision bound to a specific occurrence."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    decision_id: str
    schema_version: Literal["alias-decision-v2"] = ALIAS_DECISION_SCHEMA
    document_id: str
    pdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    keyword_id: str
    keyword: str
    observed_text: str
    match_start: int = Field(ge=0)
    match_end: int = Field(gt=0)
    status: Literal["ACCEPTED", "REJECTED", "REVOKED"] = "ACCEPTED"
    reviewer: str = Field(min_length=1)
    decided_at_utc: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    reason: str = ""
    dictionary_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_md_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    offset_space: Literal["nfc"] = "nfc"
    counting_policy: Literal["literal_v1"] = "literal_v1"

    @field_validator("decided_at_utc")
    @classmethod
    def aware_timestamp(cls, value):
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError("Decision timestamp requires a timezone")
        return value

    @field_validator("decision_id", "document_id", "reviewer")
    @classmethod
    def nonblank_identity(cls, value):
        if not value.strip():
            raise ValueError("Decision identity/reviewer cannot be blank")
        return value


def _candidate_id(keyword_id: str, start: int, end: int, observed: str) -> str:
    seed = f"{keyword_id}:{start}:{end}:{observed.casefold()}"
    return "cand-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _canonical_entries(keywords_or_snapshot) -> list[tuple[str, str]]:
    if isinstance(keywords_or_snapshot, dict) and "canonical_keywords" in keywords_or_snapshot:
        return [(k["id"], k["keyword"]) for k in keywords_or_snapshot["canonical_keywords"]]
    return [("kw-" + hashlib.sha256(k.casefold().encode()).hexdigest()[:16], k)
            for k in KeywordCounter.unique_keywords(keywords_or_snapshot)]


def find_single_word_variants(text: str, keywords_or_snapshot, max_examples: int = 3) -> list[dict]:
    """List words that fold to a one-word keyword but differ in diacritics (V8-031).

    Alias candidates need at least two words because one folded word is too often a
    different Vietnamese word ("ma", "má", "mà"). Without this list a one-word keyword
    read with a wrong accent disappears silently. Rows are review evidence only: they
    never change literal, alias or pending counts.
    """
    clean = unicodedata.normalize("NFC", text)
    by_fold = {}
    for match in _WORDS.finditer(clean):
        by_fold.setdefault(_fold(match.group()), []).append(match)
    variants = {}
    for keyword_id, keyword in _canonical_entries(keywords_or_snapshot):
        phrase = unicodedata.normalize("NFC", keyword.strip())
        if len(phrase.split()) != 1 or not _WORDS.fullmatch(phrase):
            continue
        term, exact = _fold(phrase), phrase.casefold()
        for match in by_fold.get(term, ()):
            observed = match.group()
            if observed.casefold() == exact:
                continue
            key = keyword_id, observed.casefold()
            row = variants.setdefault(key, {
                "keyword_id": keyword_id, "keyword": phrase, "observed_variant": observed.casefold(),
                "occurrences": 0, "examples": [], "review_status": "NOT_EVALUATED", "counted": False,
                "reason": SINGLE_WORD_VARIANT_REASON, "offset_space": "nfc"})
            row["occurrences"] += 1
            if len(row["examples"]) < max_examples:
                row["examples"].append({"observed_text": observed, "match_start": match.start(),
                                        "match_end": match.end(),
                                        "context": clean[max(0, match.start() - 60):match.end() + 60]})
    return [variants[key] for key in sorted(variants)]


def find_alias_candidates(text: str, keywords_or_snapshot,
                          literal_matches: list | None = None,
                          min_words: int = 2) -> list[AliasCandidate]:
    """Identify diacritic anomalies in `text` that match folded keywords.

    Guarantees:
    1. An exact match excludes only candidates of the same keyword.
    2. Only contiguous multi-word phrases (>= min_words) are inspected.
    3. Words must be separated only by whitespace (same boundary semantics as diacritics guard).
    4. Candidate offsets are in NFC; supplied literal offsets are NFC+casefold.
    """
    clean = unicodedata.normalize("NFC", text)
    canonical_entries = _canonical_entries(keywords_or_snapshot)

    # Collect literal match spans to prevent double counting
    literal_spans = {key: set() for key, _ in canonical_entries}
    keyword_ids = {unicodedata.normalize("NFC", word).casefold(): key for key, word in canonical_entries}
    folded_to_source = [i for i, char in enumerate(clean) for _ in char.casefold()]

    def add_literal(key, start, end):
        if key not in literal_spans or not 0 <= start < end <= len(folded_to_source):
            raise ValueError("Invalid literal keyword/offset for alias reconciliation")
        literal_spans[key].add((folded_to_source[start], folded_to_source[end - 1] + 1))
    if literal_matches is None:
        kw_strings = [k[1] for k in canonical_entries]
        for word, start, end in KeywordCounter.iter_occurrences(clean, kw_strings):
            add_literal(keyword_ids[word.casefold()], start, end)
    else:
        for item in literal_matches:
            if isinstance(item, (tuple, list)) and len(item) >= 3:
                key = keyword_ids.get(unicodedata.normalize("NFC", item[0]).casefold())
                add_literal(key, item[1], item[2])
            elif isinstance(item, dict) and "match_start" in item and "match_end" in item:
                key = item.get("keyword_id") or keyword_ids.get(unicodedata.normalize("NFC", item.get("keyword", "")).casefold())
                add_literal(key, item["match_start"], item["match_end"])
            else:
                raise ValueError("Literal matches must identify the keyword and folded span")

    def _overlaps_literal(key: str, s: int, e: int) -> bool:
        return any(not (e <= l_start or s >= l_end) for l_start, l_end in literal_spans[key])

    words = list(_WORDS.finditer(clean))
    folded = [_fold(m.group()) for m in words]
    candidates = []
    seen_candidates = set()

    for kw_id, phrase in canonical_entries:
        phrase_clean = unicodedata.normalize("NFC", phrase.strip())
        phrase_words = phrase_clean.split()
        if len(phrase_words) < min_words:
            continue
        term = tuple(map(_fold, phrase_words))
        size = len(term)
        for start in range(len(words) - size + 1):
            if tuple(folded[start:start + size]) != term:
                continue
            matches = words[start:start + size]
            if any(not clean[a.end():b.start()].isspace() for a, b in zip(matches, matches[1:])):
                continue
            match_start = matches[0].start()
            match_end = matches[-1].end()
            if _overlaps_literal(kw_id, match_start, match_end):
                continue
            observed = clean[match_start:match_end]
            if observed.casefold() == phrase_clean.casefold():
                continue
            cand_id = _candidate_id(kw_id, match_start, match_end, observed)
            if cand_id in seen_candidates:
                continue
            seen_candidates.add(cand_id)
            candidates.append(AliasCandidate(
                candidate_id=cand_id,
                keyword_id=kw_id,
                keyword=phrase_clean,
                observed_text=observed,
                match_start=match_start,
                match_end=match_end,
                reason=f"{DIACRITIC_REASON_PREFIX}: '{observed.casefold()}' (expected term: '{phrase_clean}')",
                scope="occurrence"
            ))

    return sorted(candidates, key=lambda c: (c.match_start, c.match_end, c.keyword_id))


def _validated_decisions(values):
    """Validate even model_copy/construct inputs; deduplicate immutable event IDs."""
    by_id = {}
    for value in values:
        if isinstance(value, dict) and not {"status", "decided_at_utc"}.issubset(value):
            raise ValueError("Imported decisions require explicit review status and timestamp")
        data = value.model_dump() if isinstance(value, AliasDecision) else value
        item = AliasDecision.model_validate(data)
        if item.match_end <= item.match_start:
            raise ValueError("Decision span is empty or reversed")
        old = by_id.get(item.decision_id)
        if old is not None and old != item:
            raise ValueError("Conflicting payloads for the same decision ID")
        by_id[item.decision_id] = item
    return [by_id[key] for key in sorted(by_id)]


def freeze_alias_decisions(value):
    """Capture validated decision bytes once; bind the frozen snapshot to a run."""
    if value is None:
        return None
    source_sha256 = None
    if isinstance(value, (str, Path)):
        raw = Path(value).read_bytes()  # A missing/unreadable file is an input error.
        source_sha256 = hashlib.sha256(raw).hexdigest()
        payload = json.loads(raw)
        if not isinstance(payload, dict) or payload.get("schema_version") != ALIAS_BUNDLE_SCHEMA:
            raise ValueError("Unsupported alias decisions schema; re-review unbound v1 decisions")
        values = payload.get("decisions")
        if not isinstance(values, list) or sha256_json_compact(values) != payload.get("bundle_sha256"):
            raise ValueError("Alias decisions checksum mismatch")
    elif isinstance(value, (list, tuple)):
        values = value
    else:
        raise ValueError("Alias decisions must be a bundle path or decision sequence")
    decisions = _validated_decisions(values)
    snapshot = {"schema_version": ALIAS_BUNDLE_SCHEMA,
                "decisions": [item.model_dump() for item in decisions],
                "source_sha256": source_sha256}
    snapshot["snapshot_sha256"] = sha256_json_compact(snapshot)
    return snapshot


def reconcile_keyword_tiers(report: dict, snapshot: dict,
                            candidates: list[AliasCandidate] | None = None,
                            decisions: list[AliasDecision] | None = None) -> dict:
    """Preserve literal counts and reconcile one latest event per occurrence.

    Incompatible source/dictionary decisions fail closed. Conflicting events at
    the same instant are rejected; bundle order never determines the winner.
    Missing candidate evaluation or review stays unknown, never inferred zero.
    """
    canonical = {row["id"]: row["keyword"] for row in snapshot["canonical_keywords"]}
    identity = report.get("identity", {})
    by_candidate = {}
    if candidates is not None:
        for value in candidates:
            cand = AliasCandidate.model_validate(value.model_dump())
            if (cand.keyword_id not in canonical or cand.keyword != canonical[cand.keyword_id]
                    or cand.match_start < 0 or cand.match_end <= cand.match_start
                    or cand.candidate_id != _candidate_id(cand.keyword_id, cand.match_start,
                                                          cand.match_end, cand.observed_text)):
                raise ValueError("Invalid alias candidate identity")
            old = by_candidate.get(cand.candidate_id)
            if old is not None and old != cand:
                raise ValueError("Ambiguous alias candidate identity")
            by_candidate[cand.candidate_id] = cand
    candidate_counts = None if candidates is None else dict.fromkeys(canonical, 0)
    if candidate_counts is not None:
        for cand in by_candidate.values():
            candidate_counts[cand.keyword_id] += 1

    effective = {}
    event_status = {}
    if decisions is not None:
        values = _validated_decisions(decisions)
        if candidates is None and values:
            raise ValueError("Cannot apply decisions without candidate evaluation")
        for item in values:
            if item.document_id != report.get("document_id"):
                continue  # Multi-document bundles are allowed.
            if (identity.get("dictionary_sha256") != snapshot["snapshot_sha256"]
                    or item.pdf_sha256 != report.get("pdf_sha256")
                    or item.dictionary_snapshot_hash != snapshot["snapshot_sha256"]
                    or item.result_md_sha256 != identity.get("result_md_sha256")
                    or item.counting_policy != identity.get("counting_policy")):
                raise ValueError("Alias decision source/dictionary/policy identity mismatch")
            key = _candidate_id(item.keyword_id, item.match_start, item.match_end, item.observed_text)
            cand = by_candidate.get(key)
            if (cand is None or item.keyword != cand.keyword
                    or item.observed_text != cand.observed_text):
                raise ValueError("Alias decision does not match an actual source candidate")
            moment = datetime.fromisoformat(item.decided_at_utc.replace("Z", "+00:00"))
            event_key = (key, moment)
            if event_key in event_status and event_status[event_key] != item.status:
                raise ValueError("Conflicting alias statuses at the same timestamp")
            event_status[event_key] = item.status
            old = effective.get(key)
            if old is not None:
                old_moment = datetime.fromisoformat(old.decided_at_utc.replace("Z", "+00:00"))
                if moment == old_moment and old.status != item.status:
                    raise ValueError("Conflicting alias statuses at the same timestamp")
                if (moment, item.decision_id) <= (old_moment, old.decision_id):
                    continue
            effective[key] = item

    reviewed = decisions is not None and candidates is not None
    reviewed_counts = dict.fromkeys(canonical, 0) if reviewed else None
    if reviewed:
        for item in effective.values():
            if item.status == "ACCEPTED":
                reviewed_counts[item.keyword_id] += 1
    tier1 = dict(report.get("canonical_counts", {}))
    return {
        "schema_version": TWO_TIER_REPORT_SCHEMA,
        "document_id": report.get("document_id", ""), "pdf_sha256": report.get("pdf_sha256"),
        "counting_policy": identity.get("counting_policy", "literal_v1"),
        "review_policy": "occurrence-latest-v2", "offset_space": "nfc",
        "dictionary_snapshot_hash": snapshot["snapshot_sha256"],
        "result_md_sha256": identity.get("result_md_sha256"),
        "tier1_literal_counts": tier1,
        "tier1_total_literal": report.get("total_canonical_matches", sum(tier1.values())),
        "tier2_candidate_status": "NOT_EVALUATED" if candidates is None else "EVALUATED",
        "tier2_candidate_counts": candidate_counts,
        "tier2_total_candidates": None if candidate_counts is None else sum(candidate_counts.values()),
        "tier2_review_status": "EVALUATED" if reviewed else "NOT_EVALUATED",
        "tier2_reviewed_counts": reviewed_counts,
        "tier2_total_reviewed": None if reviewed_counts is None else sum(reviewed_counts.values()),
        "candidates": [by_candidate[key].model_dump() for key in sorted(by_candidate)],
        "decisions": [effective[key].model_dump() for key in sorted(effective)],
        "reconciled_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def save_alias_decisions(path: str | Path, decisions: list[AliasDecision]) -> None:
    values = [item.model_dump() for item in _validated_decisions(decisions)]
    atomic_write_json(Path(path), {"schema_version": ALIAS_BUNDLE_SCHEMA, "decisions": values,
                                 "bundle_sha256": sha256_json_compact(values)})


def load_alias_decisions(path: str | Path) -> list[AliasDecision]:
    snapshot = freeze_alias_decisions(path)
    return [AliasDecision.model_validate(item) for item in snapshot["decisions"]]
