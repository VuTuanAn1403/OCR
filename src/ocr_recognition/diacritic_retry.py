"""Bounded image-backed retries shared by native-first and GPU-only pages."""
import math
import hashlib
import time

from ocr_recognition.fallback_engine import apply_reocr_result
from ocr_contracts.geometry import is_oriented_line_candidate
from ocr_recognition.inference import predict_image_counted
from ocr_text.vietnamese_diacritics import DIACRITIC_REVIEW_CODE, diacritic_suspicions, is_diacritic_only_change


def diacritic_retry_settings(config):
    options = config.get("diacritic_retry", {})
    defaults = {"enabled": False, "upscale_dpi": 300, "max_regions_per_page": 5, "max_region_ratio": 0.15, "extra_phrases": ()}
    if not isinstance(options, dict) or set(options) - defaults.keys():
        raise ValueError("diacritic_retry accepts enabled, upscale_dpi, max_regions_per_page, max_region_ratio, extra_phrases")
    settings = {**defaults, **options}
    if settings.get("extra_phrases") is None:
        settings["extra_phrases"] = ()
    if (type(settings["enabled"]) is not bool
            or type(settings["upscale_dpi"]) is not int or not 72 <= settings["upscale_dpi"] <= 600
            or type(settings["max_regions_per_page"]) is not int or not 0 <= settings["max_regions_per_page"] <= 30
            or type(settings["max_region_ratio"]) not in (int, float)
            or not 0 <= settings["max_region_ratio"] <= 1
            or not isinstance(settings["extra_phrases"], (list, tuple))
            or any(not isinstance(p, str) for p in settings["extra_phrases"])):
        raise ValueError("Invalid diacritic_retry: boolean enabled, DPI 72-600, regions 0-30, ratio 0-1, extra_phrases tuple/list required")
    settings["extra_phrases"] = tuple(settings["extra_phrases"])
    return settings


def retry_diacritic_blocks(owner, page_num, blocks, candidates, suspicious_lines):
    """Flag suspect lines even with retries disabled; return retry statistics.

    Keep native copy text and original coordinates as evidence. OCR corrections
    must come from recognizer output and preserve base letters and numeric text.
    """
    settings = diacritic_retry_settings(owner.config)
    extra_phrases = settings.get("extra_phrases") or ()
    if not extra_phrases:
        raw = (
            getattr(owner, "keyword_phrases", None)
            or getattr(owner, "keywords", None)
            or owner.config.get("keyword_phrases")
            or owner.config.get("extra_phrases")
            or ()
        )
        if isinstance(raw, (list, tuple)):
            extra_phrases = tuple(p for p in raw if isinstance(p, str))

    suspect = []
    candidate_ids = {id(block) for block in candidates}
    for block in blocks:
        reasons = diacritic_suspicions(block.text, extra_phrases=extra_phrases)
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
    record = {"enabled": settings["enabled"], "suspect_lines": len(suspect), "attempted": 0,
              "improved": 0, "lines": [], "extra_phrases_count": len(extra_phrases)}
    if not settings["enabled"]:
        return record
    for block in sorted(suspect, key=lambda b: b.quality_score if b.quality_score is not None else 0)[:budget]:
        dpi = max(settings["upscale_dpi"], owner.config.get("render_dpi", 180))
        crop, actual = owner.renderer.render_region_crop(
            page_num=page_num, bbox=block.bbox,
            dpi=dpi,
            margin=min(3.0, max(0.0, block.bbox[3] - block.bbox[1]) * 0.15))
        if crop is None or not crop.size:
            continue
        record["attempted"] += 1
        started = time.perf_counter()
        before = block.text
        result = owner.fallback_engine.reocr_crop(
            crop, block.text, block.confidence,
            predict_image=lambda image: predict_image_counted(owner, image), diacritic_only=True)
        if result.get("improved") and (result.get("needs_review")
                or diacritic_suspicions(result["text"], extra_phrases=extra_phrases)
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
        independent_codes = [code for code in block.review_reason_codes if code != DIACRITIC_REVIEW_CODE]
        if result.get("improved") and (independent_codes or is_oriented_line_candidate(block.recognition_provenance)
                                        or block.recognition_provenance.get("repetition")):
            result = {**result, "needs_review": True,
                      "review_reason": "Diacritic retry does not resolve independent orientation or source review"}
        applied = apply_reocr_result(block, result)
        if applied:
            record["improved"] += 1
        line = {"bbox": list(block.bbox), "text_raw": block.text_raw, "text_before": before,
                "text_after": block.text, "dpi": dpi, "crop_bbox": list(actual),
                "crop_shape": list(crop.shape),
                "crop_bgr_sha256": hashlib.sha256(crop.tobytes(order="C")).hexdigest(),
                "seconds": time.perf_counter()-started, "applied": bool(applied),
                "needs_review": bool(result.get("needs_review")),
                "review_reason": result.get("review_reason"),
                "image_candidates": result.get("image_candidates", [])}
        record["lines"].append(line)
        block.recognition_provenance["diacritic_retry"] = line
        if not diacritic_suspicions(block.text, extra_phrases=extra_phrases) and applied:
            block.review_reason_codes = [code for code in block.review_reason_codes if code != DIACRITIC_REVIEW_CODE]
    return record
