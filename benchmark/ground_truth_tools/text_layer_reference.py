"""Text-layer reference units for the v8 diacritic gate (GROUND_TRUTH_PROTOCOL section 7).

The protocol uses the text layer of born-digital PDFs as the reference (source b of
spec 04). This module turns one PDF page into deterministic units:

* lines and words of the text layer, in PyMuPDF extraction order, with bboxes in
  unrotated page points (the frame of ``page.get_text``) and character offsets into a
  canonical page string whose sha256 is recorded;
* a visibility verdict per word. Section 7.3 condition 3 admits only glyphs that are
  visible on the rendered page: not render mode 3, inside the CropBox, not covered by
  an image and not drawn in the background colour. All four cases have the same
  effect on pixels, so the check renders the page twice, as is and with every glyph
  removed by a redaction that keeps images and vector graphics, and counts the pixels
  that differ inside each character box.

Nothing here reads OCR output. The module only prepares material; the reviewer
decides every label (section 7.4 A and B).
"""
from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from benchmark.scientific_evaluation.ocr_metric import _extract_vietnamese_diacritic_slots

SCHEMA = "ocr-v8-text-layer-units-v1"
VISIBILITY_METHOD = "render-diff-redact-text-v1"
VISIBILITY_ZOOM = 2.0  # 144 DPI
MIN_CHANGED_PIXELS = 2  # per base character box


def diacritic_slots(text: str) -> int:
    """Shape, tone and stroke slots after NFC, the unit of DSER_strict (spec 04)."""
    total = 0
    for char in unicodedata.normalize("NFC", text):
        _, shape, tone, stroke = _extract_vietnamese_diacritic_slots(char)
        total += (shape is not None) + (tone is not None) + (stroke is not None)
    return total


@dataclass
class Char:
    text: str
    bbox: Tuple[float, float, float, float]
    offset: int  # into the canonical page string


@dataclass
class Word:
    word_id: str
    line_id: str
    text: str  # NFC
    bbox: Tuple[float, float, float, float]
    char_start: int
    char_end: int
    slots: int
    chars: List[Char] = field(repr=False, default_factory=list)
    visibility: str = "NOT_CHECKED"
    changed_pixels: Optional[int] = None


@dataclass
class Line:
    line_id: str
    block: int
    index: int
    text: str  # NFC
    bbox: Tuple[float, float, float, float]
    words: List[Word]

    @property
    def slots(self) -> int:
        return sum(word.slots for word in self.words)


def _union(boxes: Iterable[Sequence[float]]) -> Tuple[float, float, float, float]:
    boxes = list(boxes)
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def _round_box(box: Sequence[float]) -> Tuple[float, float, float, float]:
    return tuple(round(float(value), 3) for value in box)


def extract_lines(page) -> Tuple[List[Line], str]:
    """Lines and words of the text layer and the canonical page string.

    The canonical string joins the characters of each line in extraction order and
    separates lines with ``\\n``. Offsets refer to that string before NFC, so a
    reviewer's record can be traced back to the exact characters of the PDF.
    """
    import pymupdf

    raw = page.get_text("rawdict", flags=pymupdf.TEXTFLAGS_TEXT)
    pieces: List[str] = []
    cursor = 0
    lines: List[Line] = []
    for block_index, block in enumerate(raw.get("blocks", ())):
        if block.get("type") != 0:
            continue
        for line_index, line in enumerate(block.get("lines", ())):
            chars = [Char(c["c"], _round_box(c["bbox"]), 0) for span in line.get("spans", ()) for c in span.get("chars", ())]
            if not chars:
                continue
            if pieces:
                pieces.append("\n")
                cursor += 1
            for char in chars:
                char.offset = cursor
                cursor += len(char.text)
            pieces.append("".join(char.text for char in chars))
            line_id = f"b{block_index:03d}l{line_index:03d}"
            words = _split_words(line_id, chars)
            lines.append(Line(line_id, block_index, line_index, unicodedata.normalize("NFC", "".join(c.text for c in chars)),
                              _union(c.bbox for c in chars), words))
    return lines, "".join(pieces)


def _split_words(line_id: str, chars: List[Char]) -> List[Word]:
    words: List[Word] = []
    current: List[Char] = []

    def flush():
        if not current:
            return
        text = unicodedata.normalize("NFC", "".join(c.text for c in current))
        words.append(Word(f"{line_id}w{len(words):03d}", line_id, text, _union(c.bbox for c in current),
                          current[0].offset, current[-1].offset + len(current[-1].text), diacritic_slots(text),
                          list(current)))
        current.clear()

    for char in chars:
        if char.text.isspace():
            flush()
        else:
            current.append(char)
    flush()
    return words


def canonical_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _pixmap_array(page, zoom: float):
    import numpy
    import pymupdf

    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False, colorspace=pymupdf.csRGB)
    return numpy.frombuffer(pixmap.samples, dtype=numpy.uint8).reshape(pixmap.height, pixmap.width, pixmap.n)


def render_with_and_without_text(pdf_bytes: bytes, page_index: int, zoom: float = VISIBILITY_ZOOM):
    """RGB arrays of the page as drawn and with every glyph removed (images and vectors kept).

    Both renders come from fresh in-memory copies; the PDF on disk is never written.
    """
    import pymupdf

    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as document:
        page = document[page_index]
        drawn = _pixmap_array(page, zoom)
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as document:
        page = document[page_index]
        page.add_redact_annot(page.rect, fill=False, cross_out=False)
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                              text=pymupdf.PDF_REDACT_TEXT_REMOVE)
        stripped = _pixmap_array(page, zoom)
    return drawn, stripped


def pixel_box(page, bbox: Sequence[float], zoom: float, width: int, height: int) -> Optional[Tuple[int, int, int, int]]:
    """Pixel rectangle of an unrotated page-point bbox on the rendered (rotated, cropped) page."""
    import math
    import pymupdf

    rect = (pymupdf.Rect(bbox) * page.rotation_matrix) * pymupdf.Matrix(zoom, zoom)
    x0, y0 = max(0, math.floor(rect.x0)), max(0, math.floor(rect.y0))
    x1, y1 = min(width, math.ceil(rect.x1)), min(height, math.ceil(rect.y1))
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1, y1


def mark_visibility(page, words: Iterable[Word], drawn, stripped, zoom: float = VISIBILITY_ZOOM) -> Dict[str, int]:
    """Label each word VISIBLE, PARTIAL or INVISIBLE from the pixels its base characters change.

    A base character (not a space, not a combining mark) is visible when at least
    ``MIN_CHANGED_PIXELS`` pixels inside its box differ between the two renders. A
    character whose box has no width is a ligature component (``Th`` drawn as one
    glyph gives ``h`` an empty box) and takes the verdict of the base character
    before it. A word is VISIBLE only when all its base characters are visible.
    """
    import numpy

    changed = numpy.any(drawn != stripped, axis=2)
    height, width = changed.shape
    counts = {"VISIBLE": 0, "PARTIAL": 0, "INVISIBLE": 0}
    for word in words:
        seen = total = pixels = 0
        previous: Optional[bool] = None
        for char in word.chars:
            if char.text.isspace() or unicodedata.combining(char.text[:1] or " "):
                continue
            total += 1
            if char.bbox[2] - char.bbox[0] < 0.01 and previous is not None:
                seen += previous
                continue
            box = pixel_box(page, char.bbox, zoom, width, height)
            count = int(changed[box[1]:box[3], box[0]:box[2]].sum()) if box else 0
            pixels += count
            previous = count >= MIN_CHANGED_PIXELS
            seen += previous
        word.changed_pixels = pixels
        word.visibility = "VISIBLE" if total and seen == total else "PARTIAL" if seen else "INVISIBLE"
        counts[word.visibility] += 1
    return counts


def page_units(pdf_bytes: bytes, page_number: int, *, check_visibility: bool = True) -> Dict:
    """Lines, words and visibility for one 1-based page, as plain data."""
    import pymupdf

    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as document:
        page = document[page_number - 1]
        lines, canonical = extract_lines(page)
        words = [word for line in lines for word in line.words]
        visibility = None
        if check_visibility:
            drawn, stripped = render_with_and_without_text(pdf_bytes, page_number - 1)
            visibility = mark_visibility(page, words, drawn, stripped)
        frame = {"rotation": page.rotation, "rect": _round_box(page.rect), "mediabox": _round_box(page.mediabox),
                 "cropbox": _round_box(page.cropbox)}
    return {"schema_version": SCHEMA, "page": page_number, "frame": frame,
            "canonical_text_sha256": canonical_sha256(canonical), "canonical_chars": len(canonical),
            "visibility_method": VISIBILITY_METHOD if check_visibility else None,
            "visibility_counts": visibility, "lines": lines, "slots": sum(word.slots for word in words),
            "visible_slots": sum(word.slots for word in words if word.visibility == "VISIBLE") if check_visibility else None}
