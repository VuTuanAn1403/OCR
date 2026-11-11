"""Challenger: restore the stroke of Đ in uppercase Vietnamese business acronyms (V8-030 track).

On the adjudicated development GT (AAA, AGR 2020; ``scripts/diacritic_confusions.py``) 350 of 354
stroke errors are an uppercase Đ read as D, about 209 of them ``HĐQT`` read as ``HDQT``. This
challenger rewrites a whole token only when, with its D letters, it equals the D-form of an
acronym in a short fixed list; nothing else is touched, and the input string is not modified
(it returns a new string and the list of edits, so ``text_raw`` stays available).

Two-letter forms (``GĐ``, ``HĐ``) are left out on purpose: ``GD``/``HD`` have other readings.
The list is written from domain knowledge before the evaluation, not fitted to it. Quality is
NOT_EVALUATED until fix/harm is measured on GT outside the development set.
"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

METHOD = "acronym-stroke-restore-v1"
ACRONYMS = (
    "HĐQT",    # Hội đồng quản trị
    "HĐTV",    # Hội đồng thành viên
    "BĐH",     # Ban điều hành
    "ĐHĐCĐ",   # Đại hội đồng cổ đông
    "ĐHCĐ",    # Đại hội cổ đông
    "TGĐ",     # Tổng giám đốc
    "PTGĐ",    # Phó tổng giám đốc
    "BGĐ",     # Ban giám đốc
    "ĐVT",     # Đơn vị tính
    "CĐKT",    # Cân đối kế toán
    "BCĐKT",   # Bảng cân đối kế toán
    "HĐKD",    # Hoạt động kinh doanh
    "TSCĐ",    # Tài sản cố định
)
D_FORMS: Dict[str, str] = {acronym.replace("Đ", "D"): acronym for acronym in ACRONYMS}


def restore(text: str) -> Tuple[str, List[Dict]]:
    """Return the text with known acronyms restored and the edits made (offsets in the input)."""
    edits: List[Dict] = []

    def replace(match: re.Match) -> str:
        token = match.group(0)
        target = D_FORMS.get(token)
        if target is None or target == token:
            return token
        edits.append({"start": match.start(), "end": match.end(), "from": token, "to": target})
        return target

    # Only whole tokens: the acronym must not be part of a longer word.
    pattern = re.compile(r"(?<![A-Za-zÀ-ỹĐđ])[A-ZĐ]{3,}(?![A-Za-zÀ-ỹĐđ])")
    return pattern.sub(replace, text), edits
