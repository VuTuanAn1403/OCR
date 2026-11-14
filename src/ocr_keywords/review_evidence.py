"""Review-only keyword evidence beside the literal and alias tiers (V8-100, reviewer decisions Q6 B and Q7 A).

Nothing here changes a count. Both lists are evidence for the reviewer, in the same spirit as
``alias_map.find_single_word_variants``:

* ``find_confusable_candidates`` (Q7 A, promoted from ``benchmark/challengers/keyword_confusables.py``):
  keywords made of one token of letters and digits that contain the letter O or the digit 0
  (``O2O``) are listed where the text has the same token with the other of the two (``020``).
  On development the OCR read all 6 ``O2O`` of VIC 2020 as ``020``. A token touching a number or
  code separator next to a digit (``1.020``, ``1600169024-020``) is skipped.
* ``retained_line_keywords`` (Q6 B): literal keyword occurrences inside the OCR lines that the A1
  gate kept out of the reading text (``rejected_ocr_lines``, spec 13 §4.1), for example VIC 2020
  page 95 "số hóa tài liệu đào tạo" at confidence 0.535. They are reported per keyword as a
  separate pending column and never added to the literal or tier-2 counts.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import unicodedata

from ocr_keywords.counter import KeywordCounter

CONFUSABLE_POLICY = "keyword-confusable-candidates-v1"
CONFUSABLE_REASON = ("Alphanumeric keyword read with a look-alike character (letter O / digit 0); "
                     "listed for review, never counted")
RETAINED_LINE_POLICY = "retained-line-keywords-v1"
RETAINED_LINE_REASON = ("Literal keyword inside an OCR line the A1 gate kept out of the reading text; "
                        "separate pending column, never counted")
_CONFUSABLES = {"0": "o"}
_TOKEN = re.compile(r"[^\W_]+")
_SEPARATORS = ".,-/"


def _entries(dictionary) -> list[tuple[str, str]]:
    from ocr_keywords.alias_map import _canonical_entries
    return _canonical_entries(dictionary)


def _fold(token: str) -> str:
    return "".join(_CONFUSABLES.get(c, c) for c in unicodedata.normalize("NFC", token).casefold())


def _inside_number(text: str, start: int, end: int) -> bool:
    before = start >= 2 and text[start - 1] in _SEPARATORS and text[start - 2].isdigit()
    after = end + 1 < len(text) and text[end] in _SEPARATORS and text[end + 1].isdigit()
    return before or after


def find_confusable_candidates(text: str, dictionary) -> list[dict]:
    clean = unicodedata.normalize("NFC", text)
    targets: dict[str, list[tuple[str, str]]] = {}
    for keyword_id, keyword in _entries(dictionary):
        phrase = unicodedata.normalize("NFC", keyword.strip())
        if (_TOKEN.fullmatch(phrase) and any(c.isdigit() for c in phrase) and any(c.isalpha() for c in phrase)
                and any(_fold(c) == "o" for c in phrase)):
            targets.setdefault(_fold(phrase), []).append((keyword_id, phrase))
    rows = []
    for match in _TOKEN.finditer(clean):
        token = match.group()
        for keyword_id, phrase in targets.get(_fold(token), ()):
            if token.casefold() == phrase.casefold() or _inside_number(clean, match.start(), match.end()):
                continue
            rows.append({"keyword_id": keyword_id, "keyword": phrase, "observed_text": token,
                         "match_start": match.start(), "match_end": match.end(), "offset_space": "nfc",
                         "context": clean[max(0, match.start() - 60):match.end() + 60],
                         "review_status": "NOT_EVALUATED", "counted": False, "reason": CONFUSABLE_REASON})
    return rows


def retained_line_keywords(source_dir, dictionary) -> dict:
    """Literal occurrences in ``rejected_ocr_lines`` of ``<source_dir>/extraction.json``.

    Without an extraction the column is NOT_EVALUATED (null counts), never zero.
    """
    entries = _entries(dictionary)
    path = None if source_dir is None else Path(source_dir) / "extraction.json"
    if path is None or not path.is_file():
        return {"retained_line_policy": RETAINED_LINE_POLICY, "retained_line_status": "NOT_EVALUATED",
                "retained_line_counts": None, "retained_line_total": None, "retained_line_occurrences": []}
    ids = {unicodedata.normalize("NFC", keyword).casefold(): keyword_id for keyword_id, keyword in entries}
    keywords = [keyword for _, keyword in entries]
    counts = {keyword_id: 0 for keyword_id, _ in entries}
    rows = []
    for page in json.loads(path.read_text(encoding="utf-8")).get("pages", []):
        for line in (page.get("rejected_ocr_lines") or {}).get("items", []):
            text = unicodedata.normalize("NFC", line.get("text") or "")
            for keyword, start, end in KeywordCounter.iter_occurrences(text, keywords):
                keyword_id = ids[unicodedata.normalize("NFC", keyword).casefold()]
                counts[keyword_id] += 1
                rows.append({"keyword_id": keyword_id, "keyword": keyword, "page": page.get("page"),
                             "source_id": line.get("source_id"), "gate_status": line.get("gate_status"),
                             "confidence": line.get("confidence"), "bbox": line.get("bbox"), "line_text": text,
                             "match_start": start, "match_end": end, "offset_space": "nfc_casefold",
                             "review_status": "NOT_EVALUATED", "counted": False, "reason": RETAINED_LINE_REASON})
    return {"retained_line_policy": RETAINED_LINE_POLICY, "retained_line_status": "EVALUATED",
            "retained_line_counts": counts, "retained_line_total": sum(counts.values()),
            "retained_line_occurrences": rows}
