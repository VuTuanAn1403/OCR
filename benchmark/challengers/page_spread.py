"""Page orientation detection and 1-UP / 2-UP spread classification (P2, spec 12).

Adheres to:
- cai tien v2/12_HUONG_VA_XOAY_TRANG_1UP_2UP.md
- Canonical coordinate mapping and provenance preservation
- Safe fallback: UNCERTAIN defaults to 1-UP to avoid destructive text cutting.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List, Optional, Sequence, Tuple


class SpreadDecision(str, Enum):
    CONFIRMED_1UP = "CONFIRMED_1UP"
    CONFIRMED_2UP = "CONFIRMED_2UP"
    UNCERTAIN = "UNCERTAIN"


@dataclass(frozen=True)
class SpreadClassification:
    decision: SpreadDecision
    aspect_ratio: float
    center_words_count: int
    split_x: float
    gutter_score: float = 0.0
    reasons: Tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "aspect_ratio": round(self.aspect_ratio, 4),
            "center_words_count": self.center_words_count,
            "split_x": round(self.split_x, 2),
            "gutter_score": round(self.gutter_score, 4),
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class LogicalPageSpec:
    side: str  # "L" or "R" or "SINGLE"
    crop_box: Tuple[float, float, float, float]
    physical_page: int
    logical_page_id: str
    split_x: float = 0.0


def classify_page_spread(
    width: float,
    height: float,
    words_bbox: Sequence[Sequence[float]] = (),
    vertical_projection: Optional[Sequence[float]] = None,
    min_landscape_aspect: float = 1.25,
) -> SpreadClassification:
    """Classify a physical page into 1-UP, 2-UP candidate, or UNCERTAIN.

    Multi-signal fusion:
    1. Aspect Ratio: W / H >= 1.25 indicates landscape spread candidate.
    2. Text Layer: Words cutting across the central vertical strip [0.48W, 0.52W].
       If words cut across (e.g. wide tables spanning 0.40W-0.60W), confirm 1-UP.
       If zero words cut across and words exist on both halves, confirm 2-UP.
    3. Image Projection Profile (optional fallback for scan/no-text pages):
       Analyzes density valley in [0.45W, 0.55W].
    """
    if height <= 0 or width <= 0:
        raise ValueError(f"Invalid dimensions: width={width}, height={height}")

    aspect_ratio = width / height
    default_split = width / 2.0

    # Step 1: Check aspect ratio. Standard upright portrait pages are 1-UP.
    if aspect_ratio < min_landscape_aspect:
        return SpreadClassification(
            decision=SpreadDecision.CONFIRMED_1UP,
            aspect_ratio=aspect_ratio,
            center_words_count=0,
            split_x=default_split,
            reasons=("Aspect ratio below landscape threshold (portrait page)",),
        )

    # Step 2: Analyze text bounding boxes if present
    center_min_x = 0.48 * width
    center_max_x = 0.52 * width
    spanning_min_x = 0.40 * width
    spanning_max_x = 0.60 * width

    center_crossers = 0
    wide_spanners = 0
    left_words = 0
    right_words = 0

    for box in words_bbox:
        if len(box) != 4:
            continue
        x0, y0, x1, y1 = box[0], box[1], box[2], box[3]
        # Check if box straddles center strip
        if x0 < center_max_x and x1 > center_min_x:
            center_crossers += 1
        if x0 < spanning_min_x and x1 > spanning_max_x:
            wide_spanners += 1
        if x1 <= default_split:
            left_words += 1
        elif x0 >= default_split:
            right_words += 1

    total_words = len(words_bbox)

    # Case 2A: Born-digital or OCR text with clear wide spanners (wide tables)
    if wide_spanners > 0:
        return SpreadClassification(
            decision=SpreadDecision.CONFIRMED_1UP,
            aspect_ratio=aspect_ratio,
            center_words_count=center_crossers,
            split_x=default_split,
            reasons=(f"Detected {wide_spanners} wide text elements crossing center strip (wide table/banner)",),
        )

    # Case 2B: Born-digital or text with words on both sides and clean center gutter
    if total_words >= 10:
        if center_crossers == 0 and left_words > 0 and right_words > 0:
            return SpreadClassification(
                decision=SpreadDecision.CONFIRMED_2UP,
                aspect_ratio=aspect_ratio,
                center_words_count=0,
                split_x=default_split,
                reasons=("Zero words crossing center strip with balanced left/right text",),
            )
        elif center_crossers > 3:
            return SpreadClassification(
                decision=SpreadDecision.CONFIRMED_1UP,
                aspect_ratio=aspect_ratio,
                center_words_count=center_crossers,
                split_x=default_split,
                reasons=(f"Detected {center_crossers} words crossing center strip",),
            )

    # Step 3: Pure scan image / low text count fallback via projection profile
    if vertical_projection is not None and len(vertical_projection) > 0:
        n = len(vertical_projection)
        idx_min = int(0.45 * n)
        idx_max = int(0.55 * n)
        if idx_max > idx_min:
            central_slice = vertical_projection[idx_min:idx_max]
            min_val = min(central_slice)
            avg_val = sum(vertical_projection) / max(len(vertical_projection), 1)
            min_pos = idx_min + central_slice.index(min_val)
            split_x_computed = (min_pos / n) * width
            gutter_score = 1.0 - (min_val / (avg_val + 1e-6))

            if gutter_score >= 0.50:
                return SpreadClassification(
                    decision=SpreadDecision.CONFIRMED_2UP,
                    aspect_ratio=aspect_ratio,
                    center_words_count=center_crossers,
                    split_x=split_x_computed,
                    gutter_score=gutter_score,
                    reasons=(f"Visual gutter valley confirmed in projection (gutter_score={gutter_score:.2f})",),
                )

    # Fallback when evidence is ambiguous: UNCERTAIN (defaults safely to 1-UP)
    return SpreadClassification(
        decision=SpreadDecision.UNCERTAIN,
        aspect_ratio=aspect_ratio,
        center_words_count=center_crossers,
        split_x=default_split,
        reasons=("Insufficient text or projection contrast to confirm 2-UP split",),
    )


def split_2up_logical_pages(
    physical_page: int,
    width: float,
    height: float,
    split_x: Optional[float] = None,
) -> Tuple[LogicalPageSpec, LogicalPageSpec]:
    """Split a confirmed 2-UP physical canvas into Left and Right logical pages."""
    sx = split_x if split_x is not None else (width / 2.0)
    left = LogicalPageSpec(
        side="L",
        crop_box=(0.0, 0.0, sx, height),
        physical_page=physical_page,
        logical_page_id=f"{physical_page}_L",
        split_x=sx,
    )
    right = LogicalPageSpec(
        side="R",
        crop_box=(sx, 0.0, width, height),
        physical_page=physical_page,
        logical_page_id=f"{physical_page}_R",
        split_x=sx,
    )
    return left, right


def map_box_to_physical(
    local_bbox: Sequence[float],
    side: str,
    split_x: float,
) -> Tuple[float, float, float, float]:
    """Invert a logical page bounding box back to the physical canvas coordinates.

    Mathematical guarantee:
    - Left half (L):   [x0, y0, x1, y1] -> [x0, y0, x1, y1]
    - Right half (R):  [x0, y0, x1, y1] -> [x0 + split_x, y0, x1 + split_x, y1]
    """
    if len(local_bbox) != 4:
        raise ValueError(f"local_bbox must have 4 coordinates, got {local_bbox}")
    x0, y0, x1, y1 = float(local_bbox[0]), float(local_bbox[1]), float(local_bbox[2]), float(local_bbox[3])
    if side == "L" or side == "SINGLE":
        return (x0, y0, x1, y1)
    elif side == "R":
        return (x0 + split_x, y0, x1 + split_x, y1)
    raise ValueError(f"Unknown side: {side}, expected 'L', 'R', or 'SINGLE'")


def map_box_to_logical(
    physical_bbox: Sequence[float],
    split_x: float,
) -> Tuple[str, Tuple[float, float, float, float]]:
    """Determine which logical half a physical bounding box belongs to."""
    if len(physical_bbox) != 4:
        raise ValueError(f"physical_bbox must have 4 coordinates, got {physical_bbox}")
    x0, y0, x1, y1 = float(physical_bbox[0]), float(physical_bbox[1]), float(physical_bbox[2]), float(physical_bbox[3])
    center_x = (x0 + x1) / 2.0
    if center_x < split_x:
        return "L", (x0, y0, x1, y1)
    return "R", (x0 - split_x, y0, x1 - split_x, y1)

