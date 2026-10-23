"""Pure bounding-box geometry shared by structure merging and document layout."""
from __future__ import annotations

from typing import Any


def block_is_covered(bbox: list[float], structures: list[Any], threshold: float = 0.8) -> bool:
    """Remove only blocks mostly contained in a successfully reconstructed item."""
    if len(bbox) != 4:
        return False
    x0, y0, x1, y1 = bbox
    area = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    if not area:
        return False
    for item in structures:
        if len(item.bbox) != 4:
            continue
        a, b, c, d = item.bbox
        intersection = max(0.0, min(x1, c) - max(x0, a)) * max(0.0, min(y1, d) - max(y0, b))
        if intersection / area >= threshold:
            return True
    return False
