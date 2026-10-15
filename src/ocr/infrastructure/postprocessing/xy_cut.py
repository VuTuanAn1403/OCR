"""Recursive XY-cut reading order (proposal V6 C3.4, [R22]).

Each node is split at the widest whitespace valley of its x- or
y-projection: a vertical valley separates columns (read left to right), a
horizontal one separates bands (read top to bottom); ties go to the band
split. A node without a valley of at least `min_gap` points is read line by
line by `leaf_sort`.

Splitting only at the widest valley keeps two columns together when their
line gaps happen to align. Known weakness: key/value lines with a wide gap
read as a key column, then a value column. Experimental and selected only by
`reading_order.method: xycut` until measured on L3 GT (edit distance and
Kendall tau against the current sorter).
"""
from __future__ import annotations

from typing import Callable, List, Optional, Sequence, Tuple

from src.ocr.domain.models.text_block import TextBlock

METHOD = "xycut-widest-valley-v1"


def _widest_gap(intervals: Sequence[Tuple[float, float]]) -> Optional[Tuple[float, float]]:
    best: Optional[Tuple[float, float]] = None
    ordered = sorted(intervals)
    covered_to = ordered[0][1]
    for start, end in ordered[1:]:
        if start > covered_to and (best is None or start - covered_to > best[1] - best[0]):
            best = (covered_to, start)
        covered_to = max(covered_to, end)
    return best


def _split(blocks: List[TextBlock], min_gap: float) -> Optional[Tuple[List[TextBlock], List[TextBlock]]]:
    if len(blocks) < 2:
        return None
    x_gap = _widest_gap([(b.bbox[0], b.bbox[2]) for b in blocks])
    y_gap = _widest_gap([(b.bbox[1], b.bbox[3]) for b in blocks])
    x_width = x_gap[1] - x_gap[0] if x_gap else 0.0
    y_width = y_gap[1] - y_gap[0] if y_gap else 0.0
    if max(x_width, y_width) < min_gap:
        return None
    if x_width > y_width:
        first = [b for b in blocks if b.bbox[2] <= x_gap[0]]
    else:
        first = [b for b in blocks if b.bbox[3] <= y_gap[0]]
    taken = {id(b) for b in first}
    return first, [b for b in blocks if id(b) not in taken]


def xy_cut_order(blocks: Sequence[TextBlock], leaf_sort: Callable[[List[TextBlock]], List[TextBlock]],
                 min_gap: float = 3.0) -> List[TextBlock]:
    """Blocks without a 4-value bbox keep their relative order at the end."""
    placed = [b for b in blocks if b.bbox and len(b.bbox) >= 4]
    unplaced = [b for b in blocks if not (b.bbox and len(b.bbox) >= 4)]
    result: List[TextBlock] = []
    stack = [placed] if placed else []
    while stack:  # iterative depth-first: dense pages exceed the recursion limit
        node = stack.pop()
        parts = _split(node, min_gap)
        if parts is None:
            result.extend(leaf_sort(node))
        else:
            stack.append(parts[1])
            stack.append(parts[0])
    return result + unplaced
