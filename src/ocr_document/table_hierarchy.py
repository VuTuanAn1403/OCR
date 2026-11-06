"""Infer partial row trees from placed table labels and explicit numbering."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import re

from ocr_document.source_identity import valid_bbox
from ocr_text.numeric_guard import preserves_numeric_evidence


METHOD = "table-row-numbering-indent-v1"
MIN_INDENT_PT = 4.0
LEFT_TOLERANCE_PT = 2.5
_CODE = r"(?:[A-Z]|[IVX]{2,6}|[0-9]{1,2}(?:\.[0-9]{1,2}){0,3})"
_INLINE = re.compile(rf"^({_CODE})[.)]\s+(?=\S)")
_SEPARATE = re.compile(rf"(?:({_CODE})[.)]|([0-9]{{1,2}}(?:\.[0-9]{{1,2}}){{1,3}}))")
_ROMAN = re.compile(r"(?=[IVX]+$)X{0,3}(?:IX|IV|V?I{0,3})")
_BULLET = re.compile(r"^[-–•+]\s+(?=[^\W\d_])")


@dataclass(frozen=True)
class _Anchor:
    row: int
    label_col: int
    marker_col: int
    box: list[float]
    rank: int | None
    number: tuple[int, ...] = ()


def _placed(cell):
    return (cell["row_span"] == 1 and cell["bbox_source"] == "cell" and valid_bbox(cell["bbox"]))


def _anchor(row, cells):
    first, *remaining = cells
    label = first
    text = first["text_corrected"].strip()
    separate = _SEPARATE.fullmatch(text)
    inline = _INLINE.match(text)
    if separate:
        if not remaining or first["col_span"] != 1 or not _placed(first):
            return None
        label = remaining[0]
        if label["col"] != first["col"] + 1 or not _placed(label):
            return None
        a, b = first["bbox"], label["bbox"]
        if a[2] > b[0] + LEFT_TOLERANCE_PT or min(a[3], b[3]) <= max(a[1], b[1]):
            return None
        body = label["text_corrected"].strip()
        code = separate[1] or separate[2]
    elif inline:
        code, body = inline[1], text[inline.end():]
    elif bullet := _BULLET.match(text):
        code, body = None, text[bullet.end():]
        if not preserves_numeric_evidence(text, body):
            return None
    else:
        return None
    if not _placed(label) or not body or not body[0].isalpha():
        return None
    if code is None:
        rank, number = None, ()
    elif code[0].isdigit():
        number = tuple(map(int, code.split(".")))
        rank = len(number) + 1
    elif _ROMAN.fullmatch(code):
        rank, number = 1, ()
    elif len(code) == 1:
        rank, number = 0, ()
    else:
        return None
    return _Anchor(row, label["col"], first["col"], label["bbox"], rank, number)


def _indent(parent, child):
    a, b = parent.box, child.box
    if b[1] <= a[1] or a[3] - b[1] > .3 * min(a[3] - a[1], b[3] - b[1]):
        return None
    delta = round(b[0] - a[0], 2)
    return delta if delta >= -LEFT_TOLERANCE_PT else None


def infer_row_hierarchy(cells: list[dict]) -> dict | None:
    """Describe only rows in supported chains, in the original row coordinates."""
    positions = {(cell["row"], cell["col"]) for cell in cells}
    if len(positions) != len(cells) or len({col for _, col in positions}) < 2:
        return None
    by_row = defaultdict(list)
    for cell in cells:
        if cell["text_corrected"].strip():
            by_row[cell["row"]].append(cell)

    stack: list[_Anchor] = []
    nodes: dict[int, dict] = {}
    previous_row = None
    for row, entries in sorted(by_row.items()):
        child = _anchor(row, sorted(entries, key=lambda cell: cell["col"]))
        if (child is None or (previous_row is not None and row != previous_row + 1)
                or (stack and stack[-1].label_col != child.label_col)):
            stack.clear()
        previous_row = row
        if child is None:
            continue

        if child.rank is not None:
            while stack and stack[-1].rank >= child.rank:
                stack.pop()
        if stack:
            parent = stack[-1]
            indent = _indent(parent, child)
            numbered = (child.rank is not None and child.rank == parent.rank + 1
                        and (len(child.number) < 2 or child.number[:-1] == parent.number))
            bullet = child.rank is None and indent is not None and indent >= MIN_INDENT_PT
            if indent is not None and (numbered or bullet):
                root = nodes.setdefault(parent.row, {"row": parent.row, "label_col": parent.label_col,
                                                      "marker_col": parent.marker_col, "parent_row": None, "depth": 0,
                                                      "signal": "OBSERVED_ROOT", "indent_pt": None})
                signal = ("INDENTED_BULLET" if bullet else
                          "NUMBERING_AND_INDENTATION" if indent >= MIN_INDENT_PT else "NUMBERING")
                nodes[row] = {"row": row, "label_col": child.label_col, "marker_col": child.marker_col,
                              "parent_row": parent.row, "depth": root["depth"] + 1, "signal": signal, "indent_pt": indent}
            else:
                stack.clear()
        if child.rank is not None:
            stack.append(child)
    return {"method": METHOD, "nodes": [nodes[row] for row in sorted(nodes)]} if nodes else None
