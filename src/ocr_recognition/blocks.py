"""OCR lines to text blocks, moved verbatim from ProcessPageUseCase._execute_page
(P09b): hallucination rejection into rejected evidence, quality evaluation,
the numeric retry flag (A4) and layout block typing."""
import logging
import re

from ocr_contracts.evidence_block import EvidenceBlock
from ocr_contracts.region import BoundingBox, ContentType, Region
from ocr_contracts.text_block import TextBlock
from ocr_recognition.hallucination import classify_ocr_hallucination
from ocr_text.unicode_normalizer import UnicodeNormalizer
from ocr_text.vietnamese_diacritics import DIACRITIC_REASON_PREFIX, DIACRITIC_REVIEW_CODE

logger = logging.getLogger(__name__)


def ocr_results_to_blocks(ocr_results, *, regions, page_num, scale_x, scale_y, use_raw_bbox, page_w, page_h,
                          ocr_quality, dla_engine, numeric_retry_threshold, rejected_evidence, blocks,
                          candidates_for_fallback, suspicious_lines):
    for idx, res in enumerate(ocr_results):
        raw_bbox = res.get("raw_bbox") if (use_raw_bbox and "raw_bbox" in res) else res["bbox"]
        scaled_bbox = [
            round(raw_bbox[0] * scale_x, 2),
            round(raw_bbox[1] * scale_y, 2),
            round(raw_bbox[2] * scale_x, 2),
            round(raw_bbox[3] * scale_y, 2)
        ]
        text = UnicodeNormalizer.normalize(res["text"])
        conf = res.get("confidence")

        # Filter hallucination / low confidence (A1)
        is_valid, reject_reason = classify_ocr_hallucination(text, conf)
        if not is_valid:
            mid_x = (scaled_bbox[0] + scaled_bbox[2]) / 2.0
            mid_y = (scaled_bbox[1] + scaled_bbox[3]) / 2.0
            matching_region = next((r for r in regions if r.bbox.contains_point(mid_x, mid_y)), None)
            if matching_region is None and regions:
                matching_region = regions[0]
            if matching_region is None:
                matching_region = Region(
                    region_id=f"p{page_num}_rej_{len(rejected_evidence) + 1}",
                    bbox=BoundingBox(x0=scaled_bbox[0], y0=scaled_bbox[1], x1=scaled_bbox[2], y1=scaled_bbox[3]),
                    content_type=ContentType.IMAGE,
                    source="ocr",
                    orientation_status="UNCERTAIN",
                    failure_reason="Region inferred for rejected OCR candidate",
                )
                regions.append(matching_region)

            rejected_evidence.append(EvidenceBlock(
                block_id=f"B_{page_num:04d}_REJ_{len(rejected_evidence) + 1:04d}",
                page=page_num,
                region_id=matching_region.region_id,
                bbox=scaled_bbox,
                bbox_original=scaled_bbox,
                bbox_normalized=scaled_bbox,
                text=text,
                content_type=ContentType.IMAGE,
                source="ocr",
                confidence=conf,
                orientation=0.0,
                quality_score=conf,
                block_type="noise",
                is_bold=False,
                font_size=None,
                reading_order=0,
                status=reject_reason,
                failure_reason=f"Rejected: {reject_reason} (conf={conf})",
            ))
            continue

        q_score, needs_fb, reasons = ocr_quality.evaluate_ocr_result(text, conf)
        diacritic_reasons = [reason for reason in reasons if reason.startswith(DIACRITIC_REASON_PREFIX)]
        if res.get("needs_review"):
            needs_fb = True
            q_score = min(q_score, .74) if q_score is not None else None
            reasons.append(res.get("review_reason", "OCR backend requested review"))

        # A4: Numeric Verification Retry for profile balanced/accuracy
        num_threshold = numeric_retry_threshold
        contains_digit = bool(re.search(r"\d", text))
        if contains_digit and conf is not None and conf < num_threshold:
            needs_fb = True
            reasons.append(f"Numeric token with confidence {conf:.2f} < {num_threshold:.2f} (A4 check)")

        block = TextBlock(
            text=text,
            text_raw=res.get("text_raw", res["text"]),
            correction_source=(res.get("correction_source") or "unicode_normalizer")
                if text != res.get("text_raw", res["text"]) else None,
            source="primary_ocr",
            page=page_num,
            bbox=scaled_bbox,
            confidence=conf,
            quality_score=q_score,
            confidence_source="recognizer",
            reviewed=False,
            line_index=idx,
            region_id=res.get("region_id"),
            fallback_reason=(res.get("review_reason") if res.get("needs_review")
                             else "; ".join(diacritic_reasons) or None),
            review_reason_codes=[DIACRITIC_REVIEW_CODE] if diacritic_reasons else [],
        )
        if scaled_bbox and len(scaled_bbox) >= 4:
            dla = dla_engine
            if dla and hasattr(dla, "_classify_text_block"):
                try:
                    c_res = dla._classify_text_block(
                        text=text,
                        bbox=BoundingBox(x0=scaled_bbox[0], y0=scaled_bbox[1], x1=scaled_bbox[2], y1=scaled_bbox[3]),
                        page_h=page_h,
                        page_w=page_w,
                        page_num=page_num,
                        base_font_size=11.0,
                        header_band_y=page_h * 0.10,
                        footer_band_y=page_h * 0.90,
                    )
                    if isinstance(c_res, (tuple, list)) and len(c_res) >= 2:
                        block.block_type = c_res[1]
                except Exception as e:
                    logger.warning("Page %d layout classification failed for OCR block: %s", page_num, e)
        blocks.append(block)

        if needs_fb:
            candidates_for_fallback.append(block)
            suspicious_lines.append(f"{text} (reasons: {', '.join(reasons)})")


def mark_review_regions(candidates_for_fallback, regions):
    """Flag the regions of lines whose numeric text could not be confirmed."""
    for candidate in candidates_for_fallback:
        if candidate.fallback_reason not in ("OCR candidates disagree on numeric text", "numeric_cleanup_rejected"):
            continue
        if len(candidate.bbox) < 4:
            continue
        mid_x = (candidate.bbox[0] + candidate.bbox[2]) / 2.0
        mid_y = (candidate.bbox[1] + candidate.bbox[3]) / 2.0
        for region in regions:
            if region.bbox.contains_point(mid_x, mid_y):
                region.needs_fallback = True
                region.failure_reason = candidate.fallback_reason
                break
