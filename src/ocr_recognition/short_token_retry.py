"""Bounded high-DPI image proposals for short codes; no numeric rewriting."""
import hashlib
import math
import time

from ocr_recognition.inference import predict_image_counted
from ocr_text.numeric_guard import (SHORT_TOKEN_REVIEW_CODE, preserves_numeric_evidence,
                                    short_token_suspicions)


def short_token_retry_settings(config):
    defaults = {"enabled": False, "upscale_dpi": 400, "max_regions_per_page": 3}
    options = config.get("short_token_retry", {})
    if not isinstance(options, dict) or set(options) - defaults.keys():
        raise ValueError("short_token_retry accepts enabled, upscale_dpi, max_regions_per_page")
    settings = {**defaults, **options}
    if (type(settings["enabled"]) is not bool
            or type(settings["upscale_dpi"]) is not int or not 300 <= settings["upscale_dpi"] <= 400
            or type(settings["max_regions_per_page"]) is not int or not 0 <= settings["max_regions_per_page"] <= 10):
        raise ValueError("Invalid short_token_retry: boolean enabled, DPI 300-400, regions 0-10 required")
    return settings


def retry_short_token_blocks(owner, page_num, blocks, candidates, suspicious_lines):
    """Retain raw/final text and the numeric guard, even when an OCR proposal differs."""
    settings = short_token_retry_settings(owner.config)
    record = {"enabled": settings["enabled"], "suspect_lines": 0, "attempted": 0,
              "applied": 0, "lines": []}
    candidate_ids = {id(block) for block in candidates}
    for index, block in enumerate(blocks):
        hints = short_token_suspicions(block.text)
        if not hints:
            continue
        record["suspect_lines"] += 1
        if SHORT_TOKEN_REVIEW_CODE not in block.review_reason_codes:
            block.review_reason_codes.append(SHORT_TOKEN_REVIEW_CODE)
        block.reviewed = False
        block.quality_score = min(block.quality_score, .74) if block.quality_score is not None else None
        block.fallback_reason = block.fallback_reason or SHORT_TOKEN_REVIEW_CODE
        if id(block) not in candidate_ids:
            candidates.append(block)
            candidate_ids.add(id(block))
            suspicious_lines.append(f"{block.text} (reason: {SHORT_TOKEN_REVIEW_CODE})")
        line = {"block_index": index, "bbox": list(block.bbox), "text_raw": block.text_raw,
                "text_before": block.text, "hints": hints, "applied": False,
                "status": "REVIEW_ONLY"}
        record["lines"].append(line)
        block.recognition_provenance["short_token_retry"] = line
        if not settings["enabled"] or record["attempted"] >= settings["max_regions_per_page"]:
            continue
        if (len(block.bbox) != 4 or not all(math.isfinite(v) for v in block.bbox)
                or block.bbox[2] <= block.bbox[0] or block.bbox[3] <= block.bbox[1]):
            line["status"] = "INVALID_BBOX_REVIEW"
            continue
        dpi = max(settings["upscale_dpi"], owner.config.get("render_dpi", 180))
        crop, actual = owner.renderer.render_region_crop(page_num, block.bbox, dpi=dpi, margin=2)
        if crop is None or not crop.size:
            line["status"] = "EMPTY_CROP_REVIEW"
            continue
        record["attempted"] += 1
        started = time.perf_counter()
        predictions = predict_image_counted(owner, crop)
        candidate = " ".join(row["text"] for row in predictions).strip()
        line.update({"status": "IMAGE_PROPOSAL_REQUIRES_REVIEW", "dpi": dpi,
                     "crop_bbox": list(actual), "crop_shape": list(crop.shape),
                     "crop_bgr_sha256": hashlib.sha256(crop.tobytes(order="C")).hexdigest(),
                     "seconds": time.perf_counter()-started, "candidate_text": candidate,
                     "candidate_lines": predictions,
                     "numeric_evidence_preserved": preserves_numeric_evidence(block.text, candidate)})
    return record
