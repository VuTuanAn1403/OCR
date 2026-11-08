"""Literal, case-insensitive counting adapted from OCR_pdf_backup.

``literal_v1`` (the product policy): each distinct phrase is counted independently,
including substring matches. Unicode NFC makes composed and decomposed Vietnamese
accents equivalent.

``literal_v2`` (V8-032, a benchmark challenger, not wired into the product CLI):
a match must start and end on word boundaries, and overlapping matches of different
keywords are resolved leftmost-longest so a nested phrase is not counted twice.
Suppressed overlaps are returned for review. Promotion needs paired evidence on GT.
"""
from pathlib import Path
import re
import unicodedata

from ocr_contracts.keyword import KeywordCount, KeywordReport


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _literal_matches(normalized_text: str, keyword: str):
    return re.finditer(re.escape(_normalize(keyword)), normalized_text)


COUNTING_POLICIES = ("literal_v1", "literal_v2")
# A letter, digit or combining mark continues a word; "_" does not occur in prose.
_WORD_CHAR = r"[^\W_]|[\u0300-\u036f]"


def _is_word_char(char: str) -> bool:
    return bool(re.fullmatch(_WORD_CHAR, char))


def _bounded_pattern(keyword: str) -> re.Pattern:
    """Require a boundary only on a side where the keyword itself ends in a word character."""
    normalized = _normalize(keyword)
    before = rf"(?<!{_WORD_CHAR})" if _is_word_char(normalized[0]) else ""
    after = rf"(?!{_WORD_CHAR})" if _is_word_char(normalized[-1]) else ""
    return re.compile(before + re.escape(normalized) + after)


def resolve_literal_v2(text: str, keywords: list[str]) -> tuple[list[tuple[str, int, int]], list[dict]]:
    """Return (kept, suppressed) bounded matches in NFC+casefold offsets.

    Among overlapping matches the leftmost wins; at the same start the longer phrase
    wins, then dictionary order. Each suppressed match names the match that kept it out.
    """
    normalized_text = _normalize(text)
    order = KeywordCounter.unique_keywords(keywords)
    candidates = []
    for rank, keyword in enumerate(order):
        pattern = _bounded_pattern(keyword)
        # A lookahead finds overlapping occurrences of one keyword ("aa" in "aaa").
        overlapping = re.compile(f"(?=({pattern.pattern}))")
        candidates.extend((match.start(1), match.end(1), rank, keyword)
                          for match in overlapping.finditer(normalized_text))
    candidates.sort(key=lambda row: (row[0], -(row[1] - row[0]), row[2]))
    kept, suppressed, frontier = [], [], None
    for start, end, _, keyword in candidates:
        if frontier is not None and start < frontier[2]:
            suppressed.append({"keyword": keyword, "match_start": start, "match_end": end,
                               "kept_keyword": frontier[0], "kept_start": frontier[1], "kept_end": frontier[2]})
            continue
        kept.append((keyword, start, end))
        frontier = (keyword, start, end)
    return kept, suppressed


class KeywordCounter:
    @staticmethod
    def unique_keywords(keywords: list[str]) -> list[str]:
        seen = set()
        result = []
        for keyword in keywords:
            keyword = unicodedata.normalize("NFC", keyword.strip())
            normalized = _normalize(keyword)
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(keyword)
        return result

    @classmethod
    def load_keywords(cls, keywords_file: str | Path) -> list[str]:
        # Accept a UTF-8 BOM written by Windows editors, without creating files.
        text = Path(keywords_file).expanduser().read_text(encoding="utf-8-sig")
        keywords = cls.unique_keywords(text.splitlines())
        if not keywords:
            raise ValueError(f"No keywords found in {keywords_file}")
        return keywords

    @classmethod
    def iter_occurrences(cls, text: str, keywords: list[str], policy: str = "literal_v1"):
        """Yield (keyword, start, end) in the NFC+casefold text under ``policy``."""
        if policy not in COUNTING_POLICIES:
            raise ValueError(f"Unsupported counting policy: {policy}")
        if policy == "literal_v2":
            yield from sorted(resolve_literal_v2(text, keywords)[0], key=lambda row: (row[1], row[2]))
            return
        normalized_text = _normalize(text)
        for keyword in cls.unique_keywords(keywords):
            for match in _literal_matches(normalized_text, keyword):
                yield keyword, match.start(), match.end()

    @classmethod
    def count_keywords(cls, text: str, keywords: list[str], document_id: str = "",
                       source_file: str = "", policy: str = "literal_v1") -> KeywordReport:
        if policy not in COUNTING_POLICIES:
            raise ValueError(f"Unsupported counting policy: {policy}")
        per_keyword = dict.fromkeys(cls.unique_keywords(keywords), 0)
        if policy == "literal_v2":
            for keyword, _, _ in resolve_literal_v2(text, keywords)[0]:
                per_keyword[keyword] += 1
        else:
            normalized_text = _normalize(text)
            for keyword in per_keyword:
                per_keyword[keyword] = sum(1 for _ in _literal_matches(normalized_text, keyword))
        counts = [KeywordCount(keyword=keyword, exact_count=count, count=count)
                  for keyword, count in per_keyword.items()]
        total = sum(item.count for item in counts)
        return KeywordReport(document_id=document_id, source_file=source_file, keywords=counts,
                             total_keywords_searched=len(counts), total_exact_matches=total,
                             total_matches=total)
