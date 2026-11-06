"""Citations of the exact literal_v1 occurrences, with conservative page scope."""
from bisect import bisect_left, bisect_right
import hashlib
import json
from pathlib import Path
import re
import unicodedata

from ocr_keywords.counter import KeywordCounter

SCHEMA = "literal-keyword-citations-v1"
_PAGE = re.compile(r"(?m)^# Trang ([1-9]\d*)[ \t]*\r?$")


def _context(text, pages, source_dir):
    if not isinstance(pages, list) or any(type(p) is not int or p < 1 for p in pages) or len(set(pages)) != len(pages):
        raise ValueError("Citation page scope must contain distinct physical page numbers")
    markers = list(_PAGE.finditer(text))
    valid = [int(m.group(1)) for m in markers] == pages and bool(markers)
    ranges, source_hash, unresolved = [], None, False
    path = Path(source_dir) / "document.json"
    if path.is_file():
        raw = path.read_bytes()
        source_hash = hashlib.sha256(raw).hexdigest()
        document = json.loads(raw)
        for group in document.get("table_stitch", {}).get("logical_tables", []):
            anchor = f"[HTML đầy đủ]({group['html_path']})"
            positions = [m.start() for m in re.finditer(re.escape(anchor), text)]
            if len(positions) != 1:
                unresolved = True
                continue
            note = text.rfind("\n", 0, positions[0]) + 1
            end = len(text[:note].rstrip("\r\n"))
            cursor, start = end, end
            while cursor > 0:
                line = text.rfind("\n", 0, cursor) + 1
                if not text[line:cursor].startswith("|"):
                    break
                start = line
                if line == 0:
                    break
                cursor = line - 1
            source_pages = sorted({fragment["page"] for fragment in group["projection"]["fragments"]})
            if start == end or not source_pages or any(p not in pages for p in source_pages):
                unresolved = True
                continue
            ranges.append({"start": start, "end": end, "pages": source_pages,
                           "logical_table_id": group["logical_table_id"]})
    return {"schema_version": SCHEMA, "document_json_sha256": source_hash,
            "page_markers_verified": valid, "projection_locations_unresolved": unresolved,
            "logical_table_ranges": ranges}, markers


def build_citations(raw_text, snapshot, pages, *, source_dir):
    """Keep one citation per canonical match; never recount cleaned page text."""
    text = unicodedata.normalize("NFC", raw_text)
    context, markers = _context(text, pages, source_dir)
    # Case folding can expand one character (ß -> ss); offsets must map back
    # to the NFC source rather than slicing the original at folded offsets.
    folded_to_source = [index for index, char in enumerate(text) for _ in char.casefold()]
    words = [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]
    starts, ends = [w[0] for w in words], [w[1] for w in words]
    page_starts = [m.start() for m in markers]
    by_word = {row["keyword"]: row for row in snapshot["canonical_keywords"]}
    citations = []
    for keyword, first, last in KeywordCounter.iter_occurrences(raw_text, list(by_word)):
        start, end = folded_to_source[first], folded_to_source[last - 1] + 1
        page_numbers, state, lower, upper = [], "UNRESOLVED_PAGE", 0, len(text)
        logical = [span for span in context["logical_table_ranges"] if span["start"] <= start and end <= span["end"]]
        if len(logical) == 1:
            scope = logical[0]
            page_numbers, state = scope["pages"], "LOGICAL_TABLE_SOURCE_PAGES"
            lower, upper = scope["start"], scope["end"]
        elif context["page_markers_verified"] and not context["projection_locations_unresolved"]:
            index = bisect_right(page_starts, start) - 1
            if index >= 0:
                lower = page_starts[index]
                upper = page_starts[index + 1] if index + 1 < len(markers) else len(text)
                if end <= upper:
                    page_numbers, state = [pages[index]], "PHYSICAL_PAGE_MARKER"
        before_stop = bisect_left(starts, start)
        after_start = bisect_right(ends, end)
        before = [text[max(a, lower):min(b, start)] for a, b in words[max(0, before_stop - 10):before_stop]
                  if b > lower]
        after = [text[max(a, end):min(b, upper)] for a, b in words[after_start:after_start + 10] if a < upper]
        citations.append({"keyword_id": by_word[keyword]["id"], "keyword": keyword,
                          "page_number": page_numbers[0] if len(page_numbers) == 1 else None,
                          "page_numbers": page_numbers, "page_status": state,
                          "match_start": first, "match_end": last,
                          "citation_before": " ".join(before), "citation_keyword": text[start:end],
                          "citation_after": " ".join(after)})
    return context, citations
