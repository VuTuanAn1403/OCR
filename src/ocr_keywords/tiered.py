"""Three-stream analytics: literal, resolved aliases, and explicitly pending occurrences."""
from bisect import bisect_right
import unicodedata

from ocr_keywords.alias_map import (SINGLE_WORD_VARIANT_POLICY, _candidate_id, find_alias_candidates,
                                    find_single_word_variants, reconcile_keyword_tiers)
from ocr_keywords.citations import _context
from ocr_keywords.global_rules import match_rule, validate_frozen_rules


def build_tiered_report(report, dictionary, text, *, decisions=None, decision_snapshot=None, rules=None, source_dir=None):
    clean = unicodedata.normalize("NFC", text)
    candidates = find_alias_candidates(clean, dictionary)
    result = reconcile_keyword_tiers(report, dictionary, candidates, decisions)
    result["decision_snapshot_sha256"] = None if decision_snapshot is None else decision_snapshot["snapshot_sha256"]
    # V8-031: one-word keywords read with another accent are listed, never counted.
    variants = find_single_word_variants(clean, dictionary)
    result.update(single_word_variant_policy=SINGLE_WORD_VARIANT_POLICY, single_word_variants=variants,
                  single_word_variant_occurrences=sum(row["occurrences"] for row in variants))
    if rules is None:
        return result
    validate_frozen_rules(rules, dictionary)
    events = {_candidate_id(e["keyword_id"], e["match_start"], e["match_end"], e["observed_text"]): e for e in result["decisions"]}
    context, markers = _context(clean, report["selected_pages"], source_dir)
    starts = [m.start() for m in markers]
    counts, pending, resolutions = dict.fromkeys(result["tier1_literal_counts"], 0), dict.fromkeys(result["tier1_literal_counts"], 0), []
    for candidate in candidates:
        event = events.get(candidate.candidate_id)
        rule = None if event else match_rule(candidate, clean, rules)
        status = event["status"] if event else rule["status"] if rule else "NOT_EVALUATED"
        source = "occurrence_decision" if event else "auto_alias_rule" if rule and status == "ACCEPTED" else "auto_disallow_rule" if rule else None
        if status == "ACCEPTED":
            counts[candidate.keyword_id] += 1
        elif status == "NOT_EVALUATED":
            pending[candidate.keyword_id] += 1
        page_numbers, page_status = [], "UNRESOLVED_PAGE"
        spans = [span for span in context["logical_table_ranges"] if span["start"] <= candidate.match_start and candidate.match_end <= span["end"]]
        if len(spans) == 1:
            page_numbers, page_status = spans[0]["pages"], "LOGICAL_TABLE_SOURCE_PAGES"
        elif context["page_markers_verified"] and not context["projection_locations_unresolved"]:
            index = bisect_right(starts, candidate.match_start) - 1
            if index >= 0 and candidate.match_end <= (starts[index+1] if index+1 < len(starts) else len(clean)):
                page_numbers, page_status = [report["selected_pages"][index]], "PHYSICAL_PAGE_MARKER"
        resolutions.append({**candidate.model_dump(), "document_id": report["document_id"], "pdf_sha256": report["pdf_sha256"],
                            "result_md_sha256": result["result_md_sha256"], "dictionary_snapshot_hash": dictionary["snapshot_sha256"],
                            "review_status": status, "resolution_source": source, "rule_id": None if rule is None else rule["rule_id"],
                            "decision_id": None if event is None else event["decision_id"], "alias_rules_sha256": rules["source_sha256"],
                            "page_number": page_numbers[0] if len(page_numbers) == 1 else None, "page_numbers": page_numbers, "page_status": page_status,
                            "bbox": None, "placement_status": "MARKDOWN_OFFSET_ONLY", "context": clean[max(0, candidate.match_start-100):candidate.match_end+100]})
    result.update(schema_version="keyword-two-tier-v3", alias_rules_sha256=rules["source_sha256"],
                  alias_rules_snapshot_sha256=rules["snapshot_sha256"], resolutions=resolutions,
                  tier2_reviewed_counts=counts, tier2_total_reviewed=sum(counts.values()),
                  tier2_review_status="PARTIAL_PENDING" if sum(pending.values()) else "EVALUATED",
                  pending_counts=pending, total_pending=sum(pending.values()), pending_status="EVALUATED",
                  quality_acceptance="NOT_EVALUATED")
    return result
