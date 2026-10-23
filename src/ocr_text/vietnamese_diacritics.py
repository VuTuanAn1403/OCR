"""Conservative Vietnamese diacritic review hints; never rewrite source text.

These common multiword terms provide context for otherwise valid syllables
(e.g. ``trị`` versus ``trí``). This is a small review vocabulary, not a spell
checker or proof that an arbitrary sentence has correct Vietnamese accents.
"""
import re
import unicodedata

DIACRITIC_REVIEW_CODE = "vietnamese_diacritic_suspect"
DIACRITIC_REASON_PREFIX = "Vietnamese diacritic anomaly"

_PHRASES = (
    "trí tuệ nhân tạo", "xử lý ngôn ngữ", "công nghệ thông tin",
    "báo cáo thường niên", "báo cáo tài chính", "công ty cổ phần",
    "hội đồng quản trị", "đại hội đồng cổ đông", "ban tổng giám đốc",
    "lợi nhuận sau thuế", "lợi nhuận trước thuế", "doanh thu thuần",
    "kết quả kinh doanh", "hoạt động kinh doanh", "vốn chủ sở hữu",
    "tài sản cố định", "lưu chuyển tiền tệ", "bất động sản",
)
_TONES = frozenset("\u0300\u0301\u0303\u0309\u0323")
_WORDS = re.compile(r"(?:[^\W\d_]|[\u0300-\u036f])+", re.UNICODE)
_SYLLABLE = re.compile(r"(?:ngh|ng|gh|ch|tr|ph|th|kh|nh|qu|gi|[bcdđghklmnpqrstvx])?[aeiouy]+(?:ng|nh|ch|[cmnpt])?\Z")


def _fold(word: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", word.casefold())
                   if not unicodedata.combining(c)).replace("đ", "d")


_TERMS = tuple((phrase, tuple(map(_fold, phrase.split()))) for phrase in _PHRASES)


def is_diacritic_only_change(original: str, candidate: str) -> bool:
    """Keep the base letters, punctuation and numbers of the entire line."""
    return " ".join(_fold(original).split()) == " ".join(_fold(candidate).split())


def diacritic_suspicions(text: str) -> list[str]:
    """Return review reasons for context mismatches or impossible tone stacks.

    Match whole words separated only by whitespace. Numbers, codes, punctuation,
    names and unrelated valid Vietnamese words are never used as replacements.
    NFC accepts canonically decomposed marks, including marks across PDF spans.
    """
    clean = unicodedata.normalize("NFC", text)
    words = list(_WORDS.finditer(clean))
    folded = [_fold(m.group()) for m in words]
    reasons = []
    for phrase, term in _TERMS:
        size = len(term)
        for start in range(len(words) - size + 1):
            if tuple(folded[start:start + size]) != term:
                continue
            matches = words[start:start + size]
            if any(not clean[a.end():b.start()].isspace() for a, b in zip(matches, matches[1:])):
                continue
            actual = " ".join(m.group().casefold() for m in matches)
            if actual != phrase:
                reasons.append(f"{DIACRITIC_REASON_PREFIX}: '{actual}' (expected term: '{phrase}')")

    # A Vietnamese syllable has at most one tone. Restrict this check to
    # accented Vietnamese-looking words to avoid penalizing foreign names.
    for match in words:
        word = match.group()
        nfd = unicodedata.normalize("NFD", word.casefold())
        if sum(c in _TONES for c in nfd) > 1 and _SYLLABLE.fullmatch(_fold(word)) and all(
            c in "abcdefghijklmnopqrstuvwxyzđ" or unicodedata.combining(c) for c in nfd
        ):
            reasons.append(f"{DIACRITIC_REASON_PREFIX}: multiple tone marks in '{word}'")
    return list(dict.fromkeys(reasons))
