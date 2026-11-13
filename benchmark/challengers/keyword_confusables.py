"""Challenger: review candidates for alphanumeric keywords read with a look-alike character (V8-100).

On development, the screened text layer of VIC 2020 holds 6 occurrences of ``O2O`` (pages 24, 37,
52, 65, 66) and the OCR of baseline 006 read every one as ``020``: digit zero for the letter O.
``literal_v1`` counts 0 of 6, and the diacritic alias tier (``ocr_keywords.alias_map``) cannot list
them, because it only inspects phrases of two or more words made of letters
(``scratch/v8/v8_100_keywords_text_layer_006_vs_007_20261113.json``).

For each keyword that is one token of letters and digits with at least one of each (``B2B``,
``B2C``, ``C2B``, ``C2C``, ``O2O``), this challenger lists every token of the text that equals the
keyword once the pairs of ``CONFUSABLES`` are folded together, and that is not already a literal
match. Only the pair letter O / digit 0 is folded: it is the only confusion seen on development,
and a wider map (B/8, Z/2, I/1) would list more tokens that are real numbers or codes.

A token is a maximal run of letters and digits. A token next to a number or code separator
that touches a digit (``1.020``, ``020,5``, ``1600169024-020``, ``12/020``) is part of a number
or a code and is skipped, so ``2020`` and ``1.020`` are never candidates. The ``-`` and ``/``
separators were added after the first run on development listed ``1600169024-020`` (a
registration code in ASM 2022) as a candidate: the rule was adjusted once on development, so
its false-candidate rate there is not an unbiased estimate. Candidates are review evidence:
they are never counted and the text is not modified. Quality is NOT_EVALUATED until fix/harm
is measured on keyword GT.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Dict, Iterable, List

METHOD = "keyword-confusable-candidates-v1"
CONFUSABLES = {"0": "o"}  # applied after casefold, so the letter O and the digit 0 fold together
REASON = "Alphanumeric keyword read with a look-alike character (letter O / digit 0); listed for review, never counted"
_TOKEN = re.compile(r"[^\W_]+")
_NUMBER_SEPARATORS = ".,-/"


def _fold(token: str) -> str:
    return "".join(CONFUSABLES.get(char, char) for char in unicodedata.normalize("NFC", token).casefold())


def eligible_keywords(keywords: Iterable[str]) -> List[str]:
    """Keywords made of one token of letters and digits, with at least one letter and one digit."""
    chosen, seen = [], set()
    for keyword in keywords:
        phrase = unicodedata.normalize("NFC", keyword.strip())
        if (_TOKEN.fullmatch(phrase) and any(c.isdigit() for c in phrase) and any(c.isalpha() for c in phrase)
                and phrase.casefold() not in seen):
            seen.add(phrase.casefold())
            chosen.append(phrase)
    return chosen


def _inside_number(text: str, start: int, end: int) -> bool:
    before = start >= 2 and text[start - 1] in _NUMBER_SEPARATORS and text[start - 2].isdigit()
    after = end + 1 < len(text) and text[end] in _NUMBER_SEPARATORS and text[end + 1].isdigit()
    return before or after


def find_candidates(text: str, keywords: Iterable[str]) -> List[Dict]:
    """Return review candidates in NFC offsets of ``text``, sorted by position."""
    clean = unicodedata.normalize("NFC", text)
    targets: Dict[str, List[str]] = {}
    for keyword in eligible_keywords(keywords):
        if any(_fold(char) == "o" for char in keyword):  # only these keywords can be misread this way
            targets.setdefault(_fold(keyword), []).append(keyword)
    rows = []
    for match in _TOKEN.finditer(clean):
        token = match.group()
        for keyword in targets.get(_fold(token), ()):
            if token.casefold() == keyword.casefold() or _inside_number(clean, match.start(), match.end()):
                continue
            rows.append({"method": METHOD, "keyword": keyword, "observed_text": token,
                         "match_start": match.start(), "match_end": match.end(),
                         "context": clean[max(0, match.start() - 40):match.end() + 40],
                         "reason": REASON, "counted": False, "review_status": "NOT_EVALUATED"})
    return rows
