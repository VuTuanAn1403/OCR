"""Page assembly steps moved verbatim from ProcessPageUseCase._execute_page
(P09b): region statuses, the page quality report and evidence blocks."""
from typing import List, Optional

from ocr_contracts.evidence_block import EvidenceBlock
from ocr_contracts.quality import PageQualityReport
from ocr_contracts.region import BoundingBox, ContentType


def _known(values):
    """Drop unavailable (None) scores."""
    return [v for v in values if v is not None]


def _mean(values) -> Optional[float]:
    known = _known(values)
    return sum(known) / len(known) if known else None


def assign_region_statuses(regions, block_regions, tables, orientation_fallback):
    orientation_angle = {
        "rotate_90_cw": 90.0,
        "rotate_90_ccw": 270.0,
        "rotate_180": 180.0,
    }.get(orientation_fallback, 0.0)
    for region in regions:
        if region.region_id in block_regions:
            region.status = "NEEDS_REVIEW" if region.needs_fallback else "EXTRACTED"
            if region.orientation_status == "UNKNOWN":
                region.rotation = orientation_angle
                region.orientation_status = "CONFIDENT" if orientation_angle else "UNCERTAIN"
                region.orientation_confidence = 0.8 if orientation_angle else 0.5
        elif any(
            table.bbox and len(table.bbox) >= 4
            and region.bbox.overlap_ratio(BoundingBox(
                x0=table.bbox[0], y0=table.bbox[1],
                x1=table.bbox[2], y1=table.bbox[3],
            )) > 0.5
            for table in tables
        ):
            region.status = "NEEDS_REVIEW" if region.needs_fallback else "EXTRACTED"
            if region.orientation_status == "UNKNOWN":
                region.rotation = orientation_angle
                region.orientation_status = "CONFIDENT" if orientation_angle else "UNCERTAIN"
                region.orientation_confidence = 0.8 if orientation_angle else 0.5
        elif region.content_type in (ContentType.IMAGE, ContentType.IMAGE_TABLE, ContentType.FIGURE):
            region.status = "PRESERVED"
            if region.orientation_status == "UNKNOWN":
                region.orientation_status = "UNCERTAIN"
            region.failure_reason = region.failure_reason or "Image preserved without recognized text"
        else:
            region.failure_reason = region.failure_reason or "No matching extracted block or table"


def build_page_quality(*, page_num, page_type, native_score, total_time, recognizer_confidences, sorted_blocks,
                       tables, diagrams, regions, rejected_evidence, candidates_for_fallback, suspicious_lines,
                       ocr_calls, page_errors, recognized_lines, fallback_count, durations, meta,
                       allow_vector_tables, region_type_counts):
    mean_conf = (
        sum(recognizer_confidences) / len(recognizer_confidences)
        if recognizer_confidences else None
    )
    # Weighted character average for quality score (Proposal R1). Blocks
    # without a calibrated score (model output) are excluded (C2.3d); a page
    # whose content has no measurable score gets None, not a constant.
    scored_blocks = [b for b in sorted_blocks if b.quality_score is not None]
    total_chars = sum(len(b.text.strip()) for b in scored_blocks)
    calibrated_q: Optional[float]
    if total_chars > 0:
        calibrated_q = sum(b.quality_score * len(b.text.strip()) for b in scored_blocks) / total_chars
    elif scored_blocks:
        calibrated_q = sum(b.quality_score for b in scored_blocks) / len(scored_blocks)
    elif tables:
        calibrated_q = _mean(t.confidence for t in tables)
    elif sorted_blocks:
        calibrated_q = None
    else:
        calibrated_q = 0.0

    native_q = _mean(b.quality_score for b in sorted_blocks if b.source == "native")
    ocr_q = _mean(b.quality_score for b in sorted_blocks
                  if b.source in ("primary_ocr", "image_ocr", "fallback_ocr"))
    known_q = _known(b.quality_score for b in sorted_blocks)
    min_reg_q = min(known_q) if known_q else (None if sorted_blocks else 1.0)
    low_conf_line_count = len(rejected_evidence) + sum(
        1 for b in sorted_blocks if b.confidence is not None and b.confidence < 0.60)

    if sorted_blocks or tables or diagrams:
        content_status, content_reason = "EXTRACTED", None
    elif any(r.content_type in (ContentType.IMAGE, ContentType.IMAGE_TABLE, ContentType.FIGURE) for r in regions):
        content_status = "IMAGE_PRESERVED_NO_TEXT"
        content_reason = "No text recognized; image is preserved for review"
    else:
        content_status = "UNRESOLVED_NO_CONTENT"
        content_reason = "No text, table, diagram, or image region was extracted"

    quality_report = PageQualityReport(
        page=page_num,
        page_type=page_type.value,
        native_text_score=round(native_score, 4),
        ocr_confidence=round(mean_conf, 4) if mean_conf is not None else None,
        ocr_confidence_samples=len(recognizer_confidences),
        quality_scored_blocks=len(scored_blocks),
        quality_scored_characters=total_chars,
        quality_score=round(calibrated_q, 4) if calibrated_q is not None else None,
        native_quality=round(native_q, 4) if native_q is not None else None,
        ocr_quality=round(ocr_q, 4) if ocr_q is not None else None,
        low_confidence_line_count=low_conf_line_count,
        min_region_quality=round(min_reg_q, 4) if min_reg_q is not None else None,
        ocr_calls=ocr_calls,
        errors=len(page_errors),
        total_blocks=len(sorted_blocks),
        recognized_lines=recognized_lines,
        fallback_count=fallback_count,
        review_required_count=(
            sum(not block.reviewed for block in candidates_for_fallback)
            + len(rejected_evidence)
            + sum(1 for r in regions if getattr(r, "needs_fallback", False))
        ),
        suspicious_lines=suspicious_lines[:10],
        time_taken_seconds=total_time,
        stage_seconds={
            "inspect": round(durations["inspect"], 3),
            "native_extract": round(durations["native_extract"], 3),
            "image_region_ocr": round(durations["image_region_ocr"], 3),
            "render_and_refine": round(durations["render_and_refine"], 3),
            "primary_ocr": round(durations["primary_ocr"], 3),
            "fallback": round(durations["fallback"], 3),
            "table": round(durations["table"], 3),
            "docling_structure": round(durations["docling_structure"], 3),
            "layout_model": round(durations["layout_model"], 3),
            "reading_order": round(durations["reading_order"], 3),
            "postprocess": round(max(0.0, total_time - (durations["inspect"] + durations["native_extract"] + durations["image_region_ocr"] + durations["render_and_refine"] + durations["primary_ocr"] + durations["fallback"] + durations["table"] + durations["docling_structure"] + durations["layout_model"] + durations["reading_order"])), 3),
        },
        unicode_corruption_detected=bool(
            meta.get("unicode_corruption_detected", False)
            or meta.get("native_extraction_failed", False)
        ),
        native_extraction_failed=bool(meta.get("native_extraction_failed", False)),
        orientation_fallback=meta.get("orientation_fallback"),
        vector_table_probe_enabled=allow_vector_tables,
        region_count=len(regions),
        region_types=region_type_counts,
        content_status=content_status,
        content_reason=content_reason,
    )
    return quality_report, calibrated_q


def build_evidence_blocks(sorted_blocks, regions, page_num, rejected_evidence):
    evidence_blocks: List[EvidenceBlock] = []
    region_by_id = {r.region_id: r for r in regions}
    for idx, b in enumerate(sorted_blocks):
        src = "native" if b.source == "native" else "ocr"
        ct = ContentType.FORMULA if b.block_type == "formula" else (ContentType.TEXT if src == "native" else ContentType.IMAGE)
        block_region = region_by_id.get(b.region_id)
        rot = block_region.rotation if block_region else 0.0
        no_score = b.quality_score is None
        needs_review = no_score or b.quality_score < 0.75
        evidence_blocks.append(EvidenceBlock(
            block_id=f"B_{page_num:04d}_{idx + 1:04d}",
            page=page_num,
            region_id=b.region_id or f"p{page_num}_inferred",
            bbox=b.bbox if b.bbox else [],
            bbox_original=b.bbox if b.bbox else [],
            bbox_normalized=b.bbox if b.bbox else [],
            text=b.text,
            content_type=ct,
            source=src,
            confidence=b.confidence,
            confidence_source=b.confidence_source,
            orientation=rot,
            quality_score=b.quality_score,
            block_type=b.block_type or "paragraph",
            is_bold=b.is_bold,
            font_size=b.font_size,
            reading_order=idx + 1,
            status="UNRESOLVED" if needs_review else "EXTRACTED",
            failure_reason=("No calibrated confidence for model output" if no_score
                            else (b.fallback_reason or "Low OCR quality score") if needs_review else None),
        ))
    evidence_blocks.extend(rejected_evidence)
    return evidence_blocks
