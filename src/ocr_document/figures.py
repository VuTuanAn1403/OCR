"""Link captions and text to placed document objects.

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
from collections import defaultdict
from typing import Any, Dict, List, Optional

from ocr_document.source_identity import valid_bbox

METHOD = "figure-geometry-keyword-v1"
TABLE_CAPTION_METHOD = "table-caption-adjacency-v1"
MAX_CAPTION_GAP_PT = 36.0
MAX_TABLE_CAPTION_GAP_WITH_UNIT_PT = 54.0
MIN_HORIZONTAL_OVERLAP = 0.3
_CAPTION_START = re.compile(r"^\s*(?:hình|biểu đồ|sơ đồ|đồ thị|ảnh|figure|fig\.|chart|diagram|graph)(?:\s|\d|$|[.:])",
                            re.IGNORECASE)
_TEXT_TYPES = ("paragraph", "list_item")
_TABLE_CAPTION = re.compile(r"^\s*(?:bảng|table)(?:\s+\d+(?:\.\d+)*)?\s*[:：.\-–]\s*\S", re.I)
_CHART_CAPTION = re.compile(r"^\s*(?:biểu đồ|chart)\s+\d+(?:\.\d+)*\s*[:：.\-–]\s*\S", re.I)
_TABLE_UNIT = re.compile(r"^\s*(?:đơn vị(?: tính)?|đvt|units?)\s*[:：]\s*\S[^\n]{0,39}$", re.I)


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
    text_chunks = [(c, s) for c in chunks if c["type"] in _TEXT_TYPES and not c.get("callout_id")
                   for s in [_single_span(c)] if s]
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


def table_caption_geometry(caption, frame, *, max_gap=MAX_CAPTION_GAP_PT):
    """Return side and gap for a caption primarily aligned with the frame."""
    if not (valid_bbox(caption) and valid_bbox(frame)):
        return None
    overlap = min(caption[2], frame[2]) - max(caption[0], frame[0])
    if overlap < .5 * (caption[2] - caption[0]):
        return None
    position, gap = ("below", caption[1] - frame[3]) if caption[1] >= frame[3] else (
        "above", frame[1] - caption[3])
    return (position, round(gap, 2)) if gap >= 0 and round(gap, 2) <= max_gap else None


def table_caption_unit(text, unit, caption, frame):
    """A short unit line may sit between an upper caption and its table."""
    geometry = table_caption_geometry(unit, frame)
    return bool(geometry and geometry[0] == "above" and unit[1] >= caption[3] and _TABLE_UNIT.fullmatch(text))


def _intervening_content(caption, frame, position, obstacles):
    left, right = max(caption[0], frame[0]), min(caption[2], frame[2])
    top, bottom = (caption[3], frame[1]) if position == "above" else (frame[3], caption[1])
    return top < bottom and any(
        min(right, box[2]) > max(left, box[0]) and min(bottom, box[3]) > max(top, box[1])
        for box in obstacles
    )


def link_table_captions(chunks: List[Dict[str, Any]], tables: List[Dict[str, Any]]) -> None:
    """Attach unambiguous source references without moving or repeating text."""
    if not tables:
        return
    placed_by_page = defaultdict(list)
    table_chunks = {table["chunk_id"]: table for table in tables}
    for chunk in chunks:
        span = _single_span(chunk)
        if span and valid_bbox(span["bbox"]):
            placed_by_page[span["page"]].append((chunk, span))

    for entries in placed_by_page.values():
        frames = [(chunk, span["bbox"]) for chunk, span in entries if chunk["chunk_id"] in table_chunks]
        if not frames:
            continue
        image_boxes = [span["bbox"] for chunk, span in entries if chunk["type"] == "image"]
        matches = defaultdict(list)
        for caption, span in entries:
            if (caption["type"] != "paragraph" or caption.get("role") or caption.get("callout_id")
                    or len(span["block_ids"]) != 1):
                continue
            label = caption["text_corrected"]
            table_label = bool(_TABLE_CAPTION.match(label))
            if not table_label and not _CHART_CAPTION.match(label):
                continue
            box = span["bbox"]
            if not table_label and any(table_caption_geometry(box, image) for image in image_boxes):
                continue
            candidates = []
            for table, frame in frames:
                if table["section_id"] != caption["section_id"]:
                    continue
                geometry = table_caption_geometry(box, frame, max_gap=MAX_TABLE_CAPTION_GAP_WITH_UNIT_PT)
                if geometry is None:
                    continue
                position, gap = geometry
                unit = None
                if position == "above":
                    units = [chunk for chunk, other in entries if chunk["type"] == "paragraph" and not chunk.get("role")
                             and chunk["section_id"] == caption["section_id"] and len(other["block_ids"]) == 1
                             and table_caption_unit(chunk["text_corrected"], other["bbox"], box, frame)]
                    if len(units) == 1:
                        unit = units[0]
                if gap > MAX_CAPTION_GAP_PT and unit is None:
                    continue
                obstacles = (other["bbox"] for chunk, other in entries
                             if chunk is not caption and chunk is not table and chunk is not unit)
                if not _intervening_content(box, frame, position, obstacles):
                    candidates.append((table["chunk_id"], position, gap, unit))
            if len(candidates) == 1:
                table_id, position, gap, unit = candidates[0]
                link = {"chunk_id": caption["chunk_id"], "position": position, "gap_pt": gap,
                        "method": TABLE_CAPTION_METHOD, "label": "table" if table_label else "chart"}
                if unit is not None:
                    link["unit_chunk_id"] = unit["chunk_id"]
                matches[table_id].append(link)
        for table_id, captions in matches.items():
            if len(captions) == 1:
                table_chunks[table_id]["caption"] = captions[0]
