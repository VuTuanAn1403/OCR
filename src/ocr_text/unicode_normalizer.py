import unicodedata
import re
from typing import Dict, List

# Whitespace within one line: `\s` minus every character Python's str.splitlines() breaks on.
_SAME_LINE_SPACE = r'[^\S\n\r\v\f\x1c-\x1e\x85\u2028\u2029]+'

# V8-033 context: "c\u1ed5 \u00f4ng" stays when "c\u1ed5" is an antique ("\u0111\u1ed3 c\u1ed5 \u00f4ng n\u1ed9i") or "\u00f4ng" is a person
# followed by a pronoun or age word ("c\u1ed5 \u00f4ng \u1ea5y", "c\u1ed5 \u00f4ng gi\u00e0"). Words that can also follow
# "c\u1ed5 \u0111\u00f4ng" (n\u1ed9i b\u1ed9, b\u00e0 <t\u00ean>, c\u1ee5 th\u1ec3) are not listed, so those phrases are still restored.
_CO_ONG_ANTIQUE_BEFORE = frozenset({"\u0111\u1ed3"})
_CO_ONG_PERSON_AFTER = frozenset({"\u1ea5y", "ta", "gi\u00e0", "l\u00e3o", "n\u00f3"})
_LAST_WORD = re.compile(rf'(\w+){_SAME_LINE_SPACE}$')
_FIRST_WORD = re.compile(rf'{_SAME_LINE_SPACE}(\w+)')


def _restore_co_dong(stroke: str):
    """re.sub replacement for a lost-stroke "c\u1ed5 \u00f4ng" (groups: c\u1ed5, separator, \u00f4ng)."""
    def replace(match: "re.Match[str]") -> str:
        before = _LAST_WORD.search(match.string, max(0, match.start() - 32), match.start())
        after = _FIRST_WORD.match(match.string, match.end())
        if ((before and before.group(1).casefold() in _CO_ONG_ANTIQUE_BEFORE)
                or (after and after.group(1).casefold() in _CO_ONG_PERSON_AFTER)):
            return match.group(0)
        return f"{match.group(1)}{match.group(2)}{stroke}"
    return replace


class UnicodeNormalizer:
    """
    Normalizes text to Unicode NFC and cleans abnormal unicode whitespace/control characters
    while strictly preserving all Vietnamese diacritics and letters.
    """
    # Character replacement mappings
    REPLACEMENTS = {
        "\u00a0": " ",    # Non-breaking space
        "\u200b": "",     # Zero-width space
        "\u200c": "",     # Zero-width non-joiner
        "\u200d": "",     # Zero-width joiner
        "\ufeff": "",     # Byte order mark
        "\u00ad": "",     # Soft hyphen
        "\u2018": "'",    # Left single quote
        "\u2019": "'",    # Right single quote
        "\u201c": '"',    # Left double quote
        "\u201d": '"',    # Right double quote
        "\u2013": "-",    # En dash
        "\u2014": "-",    # Em dash
    }

    # These characters are rarely valid in a Vietnamese text layer. They are
    # common in PDFs whose font-to-Unicode map is broken (copy/paste produces
    # strings such as ``P Q+RS'T#'U+``). They are signals for OCR fallback,
    # not characters that can be safely replaced by a dictionary.
    SUSPICIOUS_SYMBOLS = set("|[]\\_`#$^~")

    @classmethod
    def fix_cmap_and_typography(cls, text: str) -> str:
        """
        Fixes missing 'đ'/'Đ' and erroneous Adobe InDesign typographic substitutions
        caused by non-standard font CMaps (e.g. HelveticaNeue, SVN-Gilroy).
        Strictly preserves clean native text.
        """
        if not text:
            return ""

        # 1. ASCII control characters mapped to đ / Đ
        # \x19 is uppercase Đ in HelveticaNeue-Medium (e.g. \x19iều hành, \x19ồng quản trị)
        text = text.replace("\x19", "Đ")
        # \x1d is lowercase đ in HelveticaNeue-LightItali
        text = text.replace("\x1d", "đ")
        # \x07 is lowercase đ in SVN-Gilroy
        text = text.replace("\x07", "đ")
        # \x04 is lowercase đ in SVN-GilroyBold
        text = text.replace("\x04", "đ")

        # \x17 in HelveticaNeue-Light:
        # Uppercase Đ if at start of string or after line break / bullet / sentence end / title
        def _rep_x17(m):
            prefix = m.group(1)
            next_c = m.group(2)
            if not prefix or re.search(r'(?:^|[\n.!?•\-–—*]|\b(?:Ban|Hội|Đại)\s+)$', prefix):
                return prefix + "Đ" + next_c
            return prefix + "đ" + next_c

        text = re.sub(r'(^|.*?[\n.!?•\-–—*()\[\]"“\s]|\b(?:Ban|Hội|Đại)\s+)\x17([a-zA-Z\u00C0-\u1EF9])', _rep_x17, text)
        text = text.replace("\x17", "đ")

        # \x0e in HelveticaNeue:
        def _rep_x0e(m):
            prefix = m.group(1)
            next_c = m.group(2)
            if not prefix or re.search(r'(?:^|[\n.!?•\-–—*]|\b(?:Ban|Hội|Đại)\s+)$', prefix):
                return prefix + "Đ" + next_c
            return prefix + "đ" + next_c

        text = re.sub(r'(^|.*?[\n.!?•\-–—*()\[\]"“\s]|\b(?:Ban|Hội|Đại)\s+)\x0e([a-zA-Z\u00C0-\u1EF9])', _rep_x0e, text)
        text = text.replace("\x0e", "đ")

        # \x84 (cp1252 '„') and \x8c (cp1252 'Œ')
        def _rep_cp1252_d(m):
            prefix = m.group(1)
            next_c = m.group(2)
            if not prefix or re.search(r'(?:^|[\n.!?•\-–—*]|\b(?:Ban|Hội|Đại)\s+)$', prefix):
                return prefix + "Đ" + next_c
            return prefix + "đ" + next_c

        text = re.sub(r'(^|.*?[\n.!?•\-–—*()\[\]"“\s]|\b(?:Ban|Hội|Đại)\s+)[\x84\x8c]([a-zA-Z\u00C0-\u1EF9])', _rep_cp1252_d, text)
        text = text.replace("\x84", "đ").replace("\x8c", "đ")

        # 2. Adobe InDesign typography corruption
        # „ (U+201E) -> đ or Đ when attached to a letter
        def _rep_low_quote(m):
            prefix = m.group(1)
            word = m.group(2)
            if not prefix or re.search(r'(?:^|[\n.!?•\-–—*]|\b(?:Ban|Hội|Đại)\s+)$', prefix):
                return prefix + "Đ" + word
            return prefix + "đ" + word

        text = re.sub(r'(^|.*?[\n.!?•\-–—*()\[\]"“\s]|\b(?:Ban|Hội|Đại)\s+)„([a-zA-Z\u00C0-\u1EF9])', _rep_low_quote, text)
        text = text.replace("„", "đ")

        # Œ (U+0152) -> Đ when followed by Vietnamese vowel or word char
        text = re.sub(r'Œ([a-zA-Z\u00C0-\u1EF9])', r'Đ\1', text)

        # 3. Context-aware Dictionary Fallback (for cases where control chars were already stripped)
        dict_patterns = [
            (r'\b([Bb]an|[Bb]ộ|[Tt]ổng|[Cc]hỉ)?\s*([iI]ều)\s+([hH]ành)\b',
             lambda m: f"{m.group(1) + ' ' if m.group(1) else ''}{'Điều' if (m.group(1) or m.group(2)[0].isupper()) else 'điều'} {m.group(3)}"),
            (r'\b([áÁ]nh)\s+([gG]iá)\b',
             lambda m: f"{'Đánh' if m.group(1)[0].isupper() else 'đánh'} {m.group(2)}"),
            (r'\b([hH]oạt)\s+([ộỘ]ng)\b',
             lambda m: f"{m.group(1)} {'Động' if m.group(2)[0].isupper() else 'động'}"),
            (r'\b([ơƠ]n)\s+([vV]ị)\b',
             lambda m: f"{'Đơn' if m.group(1)[0].isupper() else 'đơn'} {m.group(2)}"),
            (r'\b([qQ]uy)\s+([ịỊ]nh)\b',
             lambda m: f"{m.group(1)} {'Định' if m.group(2)[0].isupper() else 'định'}"),
            (r'\b([tT]ập)\s+([oO]àn)\b',
             lambda m: f"{m.group(1)} {'Đoàn' if m.group(2)[0].isupper() else 'đoàn'}"),
            (r'\b([tT]hẩm)\s+([ịỊ]nh)\b',
             lambda m: f"{m.group(1)} {'Định' if m.group(2)[0].isupper() else 'định'}"),
            (r'\b([bB]ất)\s+([ộỘ]ng)\s+([sS]ản)\b',
             lambda m: f"{m.group(1)} {'Động' if m.group(2)[0].isupper() else 'động'} {m.group(3)}"),
            (r'\b([hH]ội|[đĐ]ại\s+[hH]ội)\s+([ồỒ]ng)\b',
             lambda m: f"{m.group(1)} {'Đồng' if m.group(2)[0].isupper() else 'đồng'}"),
            # V8-033: "cổ đông" with a lost stroke. Title-case "Ông" stays: after a broken
            # "Công ty Cổ" line it is the honorific (Mr.), not "đông". The rule never crosses a
            # line break (an all-caps "CÔNG TY CỔ" heading line can precede "ÔNG <name>") and
            # keeps the original separator, so line structure is unchanged. Antique and person
            # contexts are left alone (_restore_co_dong).
            (rf'\b([cC]ổ)({_SAME_LINE_SPACE})(ông)\b', _restore_co_dong("đông")),
            (rf'\b(CỔ)({_SAME_LINE_SPACE})(ÔNG)\b', _restore_co_dong("ĐÔNG")),
            (r'\b([đĐ]ã)\s+([ưƯ]ợc)\b',
             lambda m: f"{m.group(1)} {'Được' if m.group(2)[0].isupper() else 'được'}"),
            (r'\b([ởỞ]|[tT]ại)\s+([đĐ]o)\b',
             lambda m: f"{m.group(1)} {'Đó' if m.group(2)[0].isupper() else 'đó'}"),
        ]

        for pattern, repl in dict_patterns:
            text = re.sub(pattern, repl, text)

        return text

    @classmethod
    def _normalize_basic(cls, text: str) -> str:
        return cls.normalize_ocr_text(cls.fix_cmap_and_typography(text))

    @classmethod
    def normalize_ocr_text(cls, text: str) -> str:
        """Clean OCR formatting without applying PDF font or dictionary guesses."""
        for old, new in cls.REPLACEMENTS.items():
            text = text.replace(old, new)

        nfc_text = unicodedata.normalize("NFC", text)
        return "".join(
            c for c in nfc_text
            if not (unicodedata.category(c).startswith("C") and c not in "\n\r\t")
        )

    @classmethod
    def normalize(cls, text: str) -> str:
        if not text:
            return ""
        return cls._normalize_basic(text)

    @classmethod
    def analyze(cls, text: str) -> Dict[str, object]:
        """Return conservative diagnostics for a potentially broken text layer.

        A PDF font encoding can map glyphs to printable but meaningless ASCII
        symbols. There is no reliable text-only mapping back to the original
        Vietnamese in that case, so this method deliberately reports the
        problem and lets the page router use the rendered image as authority.
        """
        clean = cls._normalize_basic(text or "")
        if not clean.strip():
            return {"is_corrupted": False, "score": 1.0, "reasons": []}

        visible = [c for c in clean if not c.isspace()]
        if not visible:
            return {"is_corrupted": False, "score": 1.0, "reasons": []}

        symbol_count = sum(c in cls.SUSPICIOUS_SYMBOLS for c in visible)
        alpha_count = sum(c.isalpha() for c in visible)
        replacement_count = clean.count("\ufffd")
        symbol_ratio = symbol_count / len(visible)
        alpha_ratio = alpha_count / len(visible)
        reasons: List[str] = []

        if replacement_count:
            reasons.append("replacement character U+FFFD")
        if symbol_count >= 2 and symbol_ratio >= 0.12:
            reasons.append("broken font encoding symbols")
        if re.search(r"[\[\]\\_`#^]{2,}", clean):
            reasons.append("repeated encoding markers")
        if len(clean) >= 12 and alpha_ratio < 0.55 and symbol_ratio > 0.08:
            reasons.append("low alphabetic content")

        penalty = min(0.85, replacement_count * 0.35 + symbol_ratio * 1.8)
        score = round(max(0.0, 1.0 - penalty), 4)
        return {
            "is_corrupted": bool(reasons),
            "score": score,
            "reasons": reasons,
            "symbol_ratio": round(symbol_ratio, 4),
            "alpha_ratio": round(alpha_ratio, 4),
        }
