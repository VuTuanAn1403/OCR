"""Figure captions and text inside figures (proposal V6 C3.6, review R-09).

Works on document.json chunks and images, after the section tree:

* `figure_text`: a paragraph/list chunk on the image's page whose box centre
  lies inside the image box (typically OCR of text drawn in a chart).
* caption: the closest single-page paragraph directly above or below the
  image, overlapping it horizontally and starting with a figure caption word
  ("Hình 3", "Biểu đồ", "Figure 2", ...). Keyword-gated for precision: an
  unlabelled caption stays unlinked rather than guessed. Table captions
  ("Bảng ...") belong to tables and are not linked here.

Nothing is moved or deleted; chunks only gain `role` and `figure_id`.
Precision/recall need L2/L3 GT.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

METHOD = "figure-geometry-keyword-v1"
MAX_CAPTION_GAP_PT = 36.0
MIN_HORIZONTAL_OVERLAP = 0.3
_CAPTION_START = re.compile(r"^\s*(?:hình|biểu đồ|sơ đồ|đồ thị|ảnh|figure|fig\.|chart|diagram|graph)(?:\s|\d|$|[.:])",
                            re.IGNORECASE)
_TEXT_TYPES = ("paragraph", "list_item")


def _single_span(chunk: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    spans = chunk["spans"]
    return spans[0] if len(spans) == 1 and len(spans[0]["bbox"]) == 4 else None


def _centre_inside(box, frame, tolerance: float = 2.0) -> bool:
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return frame[0] - tolerance <= cx <= frame[2] + tolerance and frame[1] - tolerance <= cy <= frame[3] + tolerance


def _horizontal_overlap(a, b) -> float:
    overlap = min(a[2], b[2]) - max(a[0], b[0])
    narrower = min(a[2] - a[0], b[2] - b[0])
    return overlap / narrower if narrower > 0 else 0.0


def link_figures(chunks: List[Dict[str, Any]], images: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_id = {chunk["chunk_id"]: chunk for chunk in chunks}
    text_chunks = [(c, s) for c in chunks if c["type"] in _TEXT_TYPES for s in [_single_span(c)] if s]
    frames = []
    for image in images:
        image["caption"], image["figure_text_chunk_ids"] = None, []
        span = _single_span(by_id[image["chunk_id"]])
        if span is not None:
            frames.append((image, span["page"], span["bbox"]))
    # Pass 1: text inside any figure, so no caption is taken from inside one.
    for chunk, span in text_chunks:
        for image, page, frame in frames:
            if span["page"] == page and _centre_inside(span["bbox"], frame):
                chunk["role"], chunk["figure_id"] = "figure_text", image["image_id"]
                image["figure_text_chunk_ids"].append(chunk["chunk_id"])
                break
    # Pass 2: one keyword caption per figure, nearest first, never shared.
    captions = 0
    for image, page, frame in frames:
        nearest = None
        for chunk, span in text_chunks:
            box = span["bbox"]
            if span["page"] != page or "role" in chunk or not _CAPTION_START.match(chunk["text_corrected"]) \
                    or _horizontal_overlap(box, frame) < MIN_HORIZONTAL_OVERLAP:
                continue
            gap, position = (box[1] - frame[3], "below") if box[1] >= frame[3] else (frame[1] - box[3], "above")
            if 0 <= gap <= MAX_CAPTION_GAP_PT and (nearest is None or gap < nearest[0]):
                nearest = (gap, position, chunk)
        if nearest is not None:
            gap, position, chunk = nearest
            chunk["role"], chunk["figure_id"] = "caption", image["image_id"]
            image["caption"] = {"chunk_id": chunk["chunk_id"], "position": position, "gap_pt": round(gap, 2)}
            captions += 1
    return {"method": METHOD, "status": "COMPLETED", "images": len(images), "captions_linked": captions,
            "figure_text_chunks": sum(len(image["figure_text_chunk_ids"]) for image in images),
            "evaluation": "NOT_EVALUATED"}
