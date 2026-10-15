"""Hidden word layer for scanned tables: variant A of the C3.5(a) experiment
(proposal V6, review item R-10).

Builds a derived single-page PDF holding the original page plus the OCR
words as invisible text (render mode 3) in an embedded Unicode font with a
ToUnicode map, so a PDF text backend (Docling with `ocr: false`) can match
words into table cells. The source PDF is never modified.

VietOCR returns lines. Word boxes are estimated by splitting the line box in
proportion to the font's advance widths; every word carries that estimate
method, and words near a cell boundary are reported as uncertain. Not used by
the pipeline: adopting it needs the A/B/C comparison on L5 GT, and the flag,
font hash and coordinate transforms would then join the page cache key.
"""
from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Sequence

import pymupdf

METHOD = "hidden-word-layer-v1"
WORD_BOX_ESTIMATE = "line_split_font_advance"
_FONT_NAME = "ocrhidden"


@dataclass(frozen=True)
class Word:
    text: str
    bbox: tuple
    line_index: int


def font_record(font_path: Path) -> Dict[str, Any]:
    """Font identity and Vietnamese coverage; a font lacking a glyph would
    write unrecoverable text, so callers must check `covers_vietnamese`."""
    font_path = Path(font_path)
    font = pymupdf.Font(fontfile=str(font_path))
    sample = "ăâêôơưđĂÂÊÔƠƯĐáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ"
    return {"path": str(font_path), "name": font.name, "sha256": hashlib.sha256(font_path.read_bytes()).hexdigest(),
            "covers_vietnamese": all(font.has_glyph(ord(c)) for c in sample),
            "license": "verify the font's own license file (proposal suggests Noto Sans, OFL-1.1)"}


def estimate_words(text: str, bbox: Sequence[float], font: pymupdf.Font, line_index: int = 0) -> List[Word]:
    """Split a line box by advance width: one box per space-separated word."""
    text = " ".join(unicodedata.normalize("NFC", text).split())
    if (len(bbox) != 4 or not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                                 and math.isfinite(v) for v in bbox)
            or bbox[2] <= bbox[0] or bbox[3] <= bbox[1]):
        raise ValueError("OCR word estimation needs a finite, positive-area line bbox")
    total = font.text_length(text, fontsize=1)
    if not text or total <= 0:
        return []
    scale = (bbox[2] - bbox[0]) / total
    words, cursor = [], 0
    for token in text.split(" "):
        if token:
            start = font.text_length(text[:cursor], fontsize=1) * scale + bbox[0]
            end = start + font.text_length(token, fontsize=1) * scale
            words.append(Word(token, (round(start, 2), bbox[1], round(end, 2), bbox[3]), line_index))
        cursor += len(token) + 1
    return words


def build_derived_page(page: pymupdf.Page, lines: Sequence[Dict[str, Any]], font_path: Path):
    """Return (derived document, words, report). `lines` hold OCR `text` and a
    `bbox` in the page's PDF points (unrotated pages only)."""
    if page.rotation:
        raise ValueError("Hidden words need an unrotated page; rotated coordinates are not supported yet")
    font = pymupdf.Font(fontfile=str(font_path))
    if any(not font.has_glyph(ord(char)) for line in lines for char in line.get("text", "")
           if not char.isspace()):
        raise ValueError("Font lacks a glyph in the OCR evidence; hidden text would not round-trip")
    words = [word for index, line in enumerate(lines)
             for word in estimate_words(line.get("text", ""), line.get("bbox", []), font, index)]
    derived = pymupdf.open()
    derived.insert_pdf(page.parent, from_page=page.number, to_page=page.number)
    target = derived[0]
    existing_text = len(target.get_text("text").strip())
    target.insert_font(fontname=_FONT_NAME, fontfile=str(font_path))
    for word in words:
        x0, y0, x1, y1 = word.bbox
        height = y1 - y0
        size = min(height * 0.8, (x1 - x0) / max(font.text_length(word.text, fontsize=1), 1e-6))
        # Separate text operators alone do not guarantee word boundaries:
        # MuPDF can join adjacent glyph runs when an estimated gap is small.
        # An explicit space preserves the token boundary without shifting
        # any following word's independently positioned glyphs.
        target.insert_text((x0, y1 - height * 0.2), word.text + " ", fontname=_FONT_NAME, fontsize=max(size, 1.0),
                           render_mode=3)
    extracted = [w[4] for w in target.get_text("words")] if not existing_text else []
    inserted = [w.text for w in words]
    matched = sum((Counter(inserted) & Counter(extracted)).values())
    report = {"method": METHOD, "word_box_estimate": WORD_BOX_ESTIMATE, "lines": len(lines), "words": len(words),
              "existing_text_chars": existing_text,
              "reextracted_words_matched": matched,
              "reextraction_exact": Counter(inserted) == Counter(extracted) if not existing_text else None,
              # Re-extraction proves the ToUnicode round trip, Vietnamese included.
              "reextracted_word_match": round(matched / len(inserted), 4) if inserted and not existing_text
              else None}
    return derived, words, report


def assign_words_to_cells(words: Sequence[Word], tables, margin: float = 2.0) -> Dict[str, Any]:
    """Each inserted word should fall in exactly one cell; centres within
    `margin` of a cell edge are uncertain (proposal C3.5(a) checks)."""
    cell_refs = [(table, cell) for table in tables for cell in table.cells if cell.bbox and len(cell.bbox) == 4]
    cells = [cell.bbox for _, cell in cell_refs]
    table_boxes = [table.bbox for table in tables]
    counts = {"in_one_cell": 0, "in_several_cells": 0, "in_table_no_cell": 0, "outside_tables": 0,
              "uncertain_near_edge": 0}
    assigned = [[] for _ in cells]
    for word in words:
        cx, cy = (word.bbox[0] + word.bbox[2]) / 2, (word.bbox[1] + word.bbox[3]) / 2
        inside = [c for c in cells if c[0] <= cx <= c[2] and c[1] <= cy <= c[3]]
        if not any(t[0] <= cx <= t[2] and t[1] <= cy <= t[3] for t in table_boxes):
            counts["outside_tables"] += 1
            continue
        key = "in_one_cell" if len(inside) == 1 else "in_several_cells" if inside else "in_table_no_cell"
        counts[key] += 1
        if len(inside) == 1:
            assigned[next(i for i, c in enumerate(cells) if c is inside[0])].append(word.text)
        if any(min(cx - c[0], c[2] - cx, cy - c[1], c[3] - cy) < margin for c in inside):
            counts["uncertain_near_edge"] += 1
    checks = []
    for (table, cell), expected in zip(cell_refs, assigned):
        observed = " ".join(unicodedata.normalize("NFC", re.sub(r"<br\s*/?>", " ", cell.text)).split()).split()
        missing = Counter(expected) - Counter(observed)
        unexpected = Counter(observed) - Counter(expected)
        checks.append({"table_id": table.table_id, "row": cell.row_idx, "col": cell.col_idx,
                       "expected_words": expected, "observed_words": observed,
                       "missing_word_occurrences": sum(missing.values()),
                       "unexpected_word_occurrences": sum(unexpected.values())})
    without_boxes = sum(not cell.bbox or len(cell.bbox) != 4 for table in tables for cell in table.cells)
    mismatches = sum(bool(c["missing_word_occurrences"] or c["unexpected_word_occurrences"]) for c in checks)
    return {"words": len(words), "cells_with_boxes": len(cells), "cells_without_boxes": without_boxes, **counts,
            "cells_content_mismatch": mismatches, "cell_content_checks": checks,
            "needs_review": bool(without_boxes or mismatches or counts["in_several_cells"]
                                 or counts["in_table_no_cell"] or counts["uncertain_near_edge"]),
            "interpretation": "OCR-word consistency diagnostic; not accuracy against L5 ground truth"}
