"""Agreement between a scan's hidden OCR text layer and our OCR (proposal V6
C2.1, review item R-07).

3-5 OCR lines are sampled deterministically; for each, the hidden-layer
words whose centre falls in the line box are compared with the OCR text. The
result is a character disagreement rate between two predictions, not a CER:
neither side is ground truth. It is measurement only. Routing keeps OCR-ing
these pages until a threshold has been chosen on dev GT, after which a gate
could OCR only the sampled lines and reuse an agreeing layer.
"""
from __future__ import annotations

import logging
import unicodedata
from typing import Any, Dict, List, Sequence

from ocr_contracts.text_block import TextBlock

METHOD = "ocr-layer-line-sample-v1"
MIN_SAMPLE_CHARS = 8


def _normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


def edit_distance(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, 1):
        current = [i]
        for j, char_b in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (char_a != char_b)))
        previous = current
    return previous[-1]


def sample_lines(blocks: Sequence[TextBlock], count: int) -> List[TextBlock]:
    """Evenly spaced over top-to-bottom order; same OCR output, same sample."""
    candidates = sorted((b for b in blocks if len(b.bbox) == 4 and len(_normalize(b.text)) >= MIN_SAMPLE_CHARS),
                        key=lambda b: (b.bbox[1], b.bbox[0]))
    if len(candidates) <= count:
        return candidates
    if count == 1:
        return [candidates[len(candidates) // 2]]
    return [candidates[round(i * (len(candidates) - 1) / (count - 1))] for i in range(count)]


def measure_agreement(page, blocks: Sequence[TextBlock], sample_size: int = 5) -> Dict[str, Any]:
    if not 3 <= sample_size <= 5:
        raise ValueError("The C2.1 agreement check samples 3-5 lines")
    words = page.get_text("words")  # includes render-mode-3 (invisible) text
    samples = []
    for block in sample_lines(blocks, sample_size):
        x0, y0, x1, y1 = block.bbox
        inside = sorted((w for w in words if x0 <= (w[0] + w[2]) / 2 <= x1 and y0 <= (w[1] + w[3]) / 2 <= y1),
                        key=lambda w: (w[5], w[6], w[7]))
        ocr_text, layer_text = _normalize(block.text), _normalize(" ".join(w[4] for w in inside))
        samples.append({"bbox": list(block.bbox), "ocr_text": ocr_text, "layer_text": layer_text,
                        "disagreement": round(edit_distance(ocr_text, layer_text)
                                              / max(len(ocr_text), len(layer_text), 1), 4)})
    rates = [s["disagreement"] for s in samples]
    return {"method": METHOD, "status": "MEASURED" if samples else "NO_SAMPLE", "sample_size": sample_size,
            "sampled_lines": len(samples), "mean_disagreement": round(sum(rates) / len(rates), 4) if rates else None,
            "max_disagreement": max(rates) if rates else None, "samples": samples,
            "comparison": "prediction_vs_prediction_not_GT", "threshold": None,
            "decision": "NOT_APPLIED_NO_DEV_THRESHOLD", "additional_ocr_calls": 0}

logger = logging.getLogger(__name__)


# Moved verbatim from ProcessPageUseCase._ocr_layer_agreement (P09b).
def page_layer_agreement(doc_page, blocks, meta, sample_lines) -> Dict[str, Any]:
    # "orientation_uncertain" keeps the original image; only rotate_* labels
    # (also per region, "<id>:rotate_90_cw") move OCR boxes.
    if ("rotate" in str(meta.get("orientation_fallback") or "") or meta.get("is_1up_landscape")
            or meta.get("is_180_rotated") or getattr(doc_page, "rotation", 0)):
        # OCR boxes are then in an upright space, not the layer's PDF space.
        return {"method": METHOD, "status": "SKIPPED_COORDINATE_TRANSFORM_REQUIRED"}
    try:
        return measure_agreement(
            doc_page, blocks, sample_lines)
    except Exception as exc:
        logger.warning("OCR-layer agreement check failed: %s", exc, exc_info=True)
        return {"method": METHOD, "status": "FAILED", "error": f"{type(exc).__name__}: {exc}"}
