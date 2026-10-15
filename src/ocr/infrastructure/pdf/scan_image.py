"""Scan page image acquisition (proposal V6 C2.2(2)(3), review item R-08).

`full_page_image_info` records the source DPI of the image covering a page;
it is metadata only. Two opt-in settings (`scan_image` in the profile) change
how the OCR image is obtained, both off by default:

* `source: embedded` decodes the page image directly instead of rendering,
  only when that is lossless with respect to the rendered page: one upright
  image covering the crop box, no rotation, mask or vector drawing on top.
  Anything else renders as before and records why.
* `dpi_policy: source_clamp` processes at clamp(source_dpi * k, min, max).
  `k` has no default: it is chosen by experiment (C3.3a), not assumed.

The returned image always spans the page rect, so the existing pixel->point
scaling stays valid; the coordinate chain is recorded for provenance.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple
import math

import cv2
import numpy as np
import pymupdf

from src.ocr.infrastructure.pdf.coordinate_transform import render_coordinate_chain

METHOD = "scan-image-v1"
_COVER_TOLERANCE_PT = 1.0


def full_page_image_info(page) -> Optional[Dict[str, Any]]:
    """The largest image covering >= 80% of the page, with its source DPI."""
    rect = page.rect
    page_area = max(rect.width * rect.height, 1e-6)
    images = [info for info in page.get_image_info(xrefs=True) if info.get("width") and info.get("height")]
    covering = [info for info in images if pymupdf.Rect(info["bbox"]).get_area() / page_area >= 0.8]
    if not covering:
        return None
    info = max(covering, key=lambda i: pymupdf.Rect(i["bbox"]).get_area())
    box = pymupdf.Rect(info["bbox"])
    a, b, c, d, _, _ = info["transform"]
    upright = abs(b) < 1e-6 and abs(c) < 1e-6 and a > 0 and d > 0
    dpi_x, dpi_y = (info["width"] / (box.width / 72), info["height"] / (box.height / 72)) if upright else \
        (info["width"] / (box.height / 72), info["height"] / (box.width / 72))
    return {"xref": info.get("xref"), "width_px": info["width"], "height_px": info["height"],
            "bbox": [round(v, 2) for v in box], "upright": upright, "images_on_page": len(images),
            "has_mask": bool(info.get("has-mask")),
            "covers_page": all(abs(u - v) <= _COVER_TOLERANCE_PT for u, v in zip(box, rect)),
            "source_dpi": round(min(dpi_x, dpi_y), 1)}


def processing_dpi(source_dpi: float, k: float, min_dpi: int = 150, max_dpi: int = 300) -> int:
    return int(min(max(round(source_dpi * k), min_dpi), max_dpi))


def validate_settings(settings) -> None:
    """Raise ValueError for a malformed `scan_image` profile section."""
    if not isinstance(settings, dict) or set(settings) - {"source", "dpi_policy", "k", "min_dpi", "max_dpi"}:
        raise ValueError("scan_image accepts source, dpi_policy, k, min_dpi, max_dpi")
    if settings.get("source", "render") not in ("render", "embedded"):
        raise ValueError("scan_image.source must be render or embedded")
    policy = settings.get("dpi_policy", "fixed")
    if policy not in ("fixed", "source_clamp"):
        raise ValueError("scan_image.dpi_policy must be fixed or source_clamp")
    k = settings.get("k")
    if policy == "source_clamp" and (isinstance(k, bool) or not isinstance(k, (int, float))
                                      or not math.isfinite(k) or k <= 0):
        raise ValueError("scan_image.dpi_policy source_clamp needs an experimentally chosen k > 0")
    low, high = settings.get("min_dpi", 150), settings.get("max_dpi", 300)
    if type(low) is not int or type(high) is not int or not 72 <= low <= high <= 600:
        raise ValueError("scan_image.min_dpi/max_dpi must be integers with 72 <= min <= max <= 600")


def _embedded_refusal(page, info: Optional[Dict[str, Any]]) -> Optional[str]:
    if info is None:
        return "no full-page image"
    if getattr(page, "rotation", 0):
        return "page rotation"
    if not info["upright"]:
        return "image is rotated or flipped"
    if not info["covers_page"]:
        return "image does not span the page rect"
    if info["images_on_page"] != 1:
        return "other images on the page"
    if info["has_mask"]:
        return "image has a transparency mask"
    if info["xref"] is None or info["xref"] <= 0:
        return "inline image without xref"
    if page.get_drawings():
        return "vector drawings over the image"
    # A PDF can draw text over the scan as well as contain invisible OCR.
    # Decoding only the image would silently drop visible additions. Unknown
    # visibility is also insufficient evidence for this opt-in shortcut.
    try:
        if any(span.get("type") != 3 and span.get("chars") for span in page.get_texttrace()):
            return "visible text over the image"
    except (RuntimeError, ValueError, AttributeError):
        return "text visibility could not be inspected"
    return None


def _decode(doc, xref: int) -> np.ndarray:
    pixmap = pymupdf.Pixmap(doc, xref)
    if pixmap.alpha:
        pixmap = pymupdf.Pixmap(pixmap, 0)
    if pixmap.colorspace is None or pixmap.colorspace.n not in (1, 3):
        pixmap = pymupdf.Pixmap(pymupdf.csRGB, pixmap)
    image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.h, pixmap.w, pixmap.n)
    return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR if pixmap.n == 1 else cv2.COLOR_RGB2BGR)


def acquire_page_image(doc, page_num: int, renderer, render_dpi: int,
                       settings: Optional[Dict[str, Any]] = None) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Return (BGR image spanning the page rect, provenance record)."""
    settings = {} if settings is None else settings
    validate_settings(settings)
    page = doc[page_num - 1]
    info = full_page_image_info(page)
    record: Dict[str, Any] = {"method": METHOD, "source": "render", "source_dpi": info and info["source_dpi"],
                              "dpi_policy": settings.get("dpi_policy", "fixed")}
    dpi = render_dpi
    if record["dpi_policy"] == "source_clamp":
        if info is None:
            record["dpi_fallback_reason"] = "no full-page image; fixed render_dpi used"
        else:
            dpi = processing_dpi(info["source_dpi"], settings["k"], settings.get("min_dpi", 150),
                                 settings.get("max_dpi", 300))
    record["processing_dpi"] = dpi
    image = None
    if settings.get("source", "render") == "embedded":
        refusal = _embedded_refusal(page, info)
        if refusal is None:
            try:
                image = _decode(doc, info["xref"])
                target = (max(1, round(page.rect.width * dpi / 72)), max(1, round(page.rect.height * dpi / 72)))
                if (image.shape[1], image.shape[0]) != target:
                    shrink = target[0] < image.shape[1]
                    image = cv2.resize(image, target, interpolation=cv2.INTER_AREA if shrink else cv2.INTER_CUBIC)
                record["source"] = "embedded"
            except (RuntimeError, ValueError, cv2.error) as exc:
                image = None
                record["embedded_fallback_reason"] = f"image decode/resize failed: {type(exc).__name__}: {exc}"
        else:
            record["embedded_fallback_reason"] = refusal
    if image is None:
        image = renderer.render_page(page_num, dpi=dpi)
    # Embedded images are only used on unrotated pages, where this chain is
    # the plain scale that the OCR path inverts.
    record["coordinate_chain"] = render_coordinate_chain(page, image.shape).to_dict()
    return image, record
