"""Which pages a VLM fallback may see: only pages with a diagnostic (V8-090 gate).

The policy reads the product's own page diagnostics; it never reads GT and never ranks
by the VLM's output. Thresholds are a proposal (``POLICY``) and must be locked in the
experiment protocol before a model run. ``line_orientation_unverified`` and
``review_required_count`` are left out on purpose: on the key-003 output they are set on
every page, so they do not single out hard pages.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional

POLICY = {
    "name": "vlm-page-selection-v1",
    "low_page_confidence": 0.75,       # mean recogniser confidence of the page
    "low_confidence_line_share": 0.15,  # share of recognised lines flagged "Low engine confidence"
    "heuristic_table": True,            # a table whose structure came from the heuristic, not a model
    "unicode_corruption": True,
}
REASONS = ("LOW_PAGE_CONFIDENCE", "LOW_CONFIDENCE_LINES", "HEURISTIC_TABLE", "UNICODE_CORRUPTION")


def page_reasons(quality: Dict, extraction_page: Optional[Dict], policy: Dict = POLICY) -> List[str]:
    reasons = []
    lines = quality.get("recognized_lines") or 0
    confidence = quality.get("ocr_confidence")
    if lines and isinstance(confidence, (int, float)) and confidence < policy["low_page_confidence"]:
        reasons.append("LOW_PAGE_CONFIDENCE")
    flagged = sum("Low engine confidence" in str(line) for line in quality.get("suspicious_lines") or [])
    if lines and flagged / lines >= policy["low_confidence_line_share"]:
        reasons.append("LOW_CONFIDENCE_LINES")
    if policy["heuristic_table"] and extraction_page and any(
            item.get("kind") == "t" and item.get("source") == "heuristic" for item in extraction_page.get("items", ())):
        reasons.append("HEURISTIC_TABLE")
    if policy["unicode_corruption"] and quality.get("unicode_corruption_detected"):
        reasons.append("UNICODE_CORRUPTION")
    return reasons


def select_pages(pages: Iterable[Dict], extraction_pages: Dict[int, Dict], policy: Dict = POLICY) -> List[Dict]:
    """Pages with at least one diagnostic, in page order, with their reasons."""
    selected = []
    for page in sorted(pages, key=lambda p: p["page_num"]):
        reasons = page_reasons(page.get("quality") or {}, extraction_pages.get(page["page_num"]), policy)
        if reasons:
            selected.append({"page": page["page_num"], "reasons": reasons})
    return selected
