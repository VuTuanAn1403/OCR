"""Bounded image-backed retries shared by native-first and GPU-only pages."""
import math

from ocr_recognition.fallback_engine import apply_reocr_result
from ocr_recognition.inference import predict_image_counted
from ocr_text.vietnamese_diacritics import DIACRITIC_REVIEW_CODE, diacritic_suspicions, is_diacritic_only_change


def diacritic_retry_settings(config):
    options = config.get("diacritic_retry", {})
    defaults = {"enabled": False, "upscale_dpi": 300, "max_regions_per_page": 5, "max_region_ratio": 0.15}
    if not isinstance(options, dict) or set(options) - defaults.keys():
        raise ValueError("diacritic_retry accepts enabled, upscale_dpi, max_regions_per_page, max_region_ratio")
    settings = {**defaults, **options}
    if (type(settings["enabled"]) is not bool
            or type(settings["upscale_dpi"]) is not int or not 72 <= settings["upscale_dpi"] <= 600
            or type(settings["max_regions_per_page"]) is not int or not 0 <= settings["max_regions_per_page"] <= 30
            or type(settings["max_region_ratio"]) not in (int, float)
            or not 0 <= settings["max_region_ratio"] <= 1):
        raise ValueError("Invalid diacritic_retry: boolean enabled, DPI 72-600, regions 0-30, ratio 0-1 required")
    return settings


def retry_diacritic_blocks(owner, page_num, blocks, candidates, suspicious_lines):
    """Flag suspect lines even with retries disabled; return retry statistics.

    Keep native copy text and original coordinates as evidence. OCR corrections
    must come from recognizer output and preserve base letters and numeric text.
    """
    settings = diacritic_retry_settings(owner.config)
    suspect = []
    candidate_ids = {id(block) for block in candidates}
    for block in blocks:
        reasons = diacritic_suspicions(block.text)
        if not reasons:
            continue
        if DIACRITIC_REVIEW_CODE not in block.review_reason_codes:
            block.review_reason_codes.append(DIACRITIC_REVIEW_CODE)
        block.quality_score = min(block.quality_score, 0.74) if block.quality_score is not None else None
        block.reviewed = False
        block.fallback_reason = block.fallback_reason or "; ".join(reasons)
        if id(block) not in candidate_ids:
            candidates.append(block)
            candidate_ids.add(id(block))
            suspicious_lines.append(f"{block.text} (reasons: {'; '.join(reasons)})")
        if len(block.bbox) == 4:
            suspect.append(block)
    budget = min(settings["max_regions_per_page"], math.ceil(len(blocks) * settings["max_region_ratio"]))
    record = {"enabled": settings["enabled"], "suspect_lines": len(suspect), "attempted": 0, "improved": 0}
    if not settings["enabled"]:
        return record
    for block in sorted(suspect, key=lambda b: b.quality_score if b.quality_score is not None else 0)[:budget]:
        crop, _ = owner.renderer.render_region_crop(
            page_num=page_num, bbox=block.bbox,
            dpi=max(settings["upscale_dpi"], owner.config.get("render_dpi", 180)),
            margin=min(3.0, max(0.0, block.bbox[3] - block.bbox[1]) * 0.15))
        if crop is None or not crop.size:
            continue
        record["attempted"] += 1
        result = owner.fallback_engine.reocr_crop(
            crop, block.text, block.confidence,
            predict_image=lambda image: predict_image_counted(owner, image), diacritic_only=True)
        if result.get("improved") and (result.get("needs_review")
                or diacritic_suspicions(result["text"])
                or not is_diacritic_only_change(block.text, result["text"])):
            result = {**result, "improved": False, "needs_review": True,
                      "review_reason": result.get("review_reason") or "Diacritic retry changed other line content"}
        if result.get("improved") and block.source == "native":
            # A printed typo can be copied faithfully. A model's preferred
            # spelling is not proof of a broken PDF font map: preserve the
            # native transcription and expose the competing image reading.
            record.setdefault("native_disagreements", []).append({
                "bbox": list(block.bbox), "native_text": block.text,
                "ocr_text": result["text"], "ocr_confidence": result["confidence"]})
            result = {**result, "improved": False, "needs_review": True,
                      "review_reason": "Native text and OCR disagree on Vietnamese diacritics"}
        if apply_reocr_result(block, result):
            record["improved"] += 1
        if not diacritic_suspicions(block.text) and block.reviewed:
            block.review_reason_codes = [code for code in block.review_reason_codes if code != DIACRITIC_REVIEW_CODE]
    return record
