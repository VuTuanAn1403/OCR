"""Phase A layout steps moved verbatim from ProcessPageUseCase (P06).

`apply_layout_model` annotates OCR/native blocks with D1 model regions and
never removes content; `link_blocks_to_regions` gives every block a region.
"""
import logging
import time
from typing import List

import pymupdf

from ocr_contracts.region import BoundingBox, ContentType, Region
from ocr_contracts.text_block import TextBlock

logger = logging.getLogger(__name__)


def _score_or(value, default):
    return default if value is None else value


def apply_layout_model(engine, renderer, config, doc_page, page_num, blocks, regions, meta, image=None):
    """Run optional D1 in-process, retaining geometric regions on failure.

    Model candidates annotate text and supplement structure candidates;
    they do not remove OCR content or gate Docling before pilot validation.
    """
    if engine.model_path is None:
        meta["layout_model"] = {"status": "HEURISTIC_ONLY"}
        return
    meta["layout_model"] = {"adapter": engine.adapter_kind, "model_path": str(engine.model_path),
                            "device": engine.device, "status": "FAILED_FALLBACK"}
    display_coordinates = config.get("ocr_source_policy") == "gpu_ocr_only_v1"
    if (meta.get("is_1up_landscape") or meta.get("is_180_rotated")
            or (getattr(doc_page, "rotation", 0) and not display_coordinates)):
        # Legacy OCR can retain boxes in an upright page space. Until all
        # transforms are invertible, do not merge original-PDF model boxes.
        meta["layout_model"].update(status="SKIPPED_COORDINATE_TRANSFORM_REQUIRED",
                                    reason="Legacy rotated OCR/PDF coordinates need an explicit transform")
        if getattr(engine, "strict", False) is True:
            raise RuntimeError("Strict GPU layout requires a verified coordinate transform for this rotated page")
        return
    if engine._session is None:
        meta["layout_model"]["error"] = engine.last_error or "ONNX session unavailable"
        if getattr(engine, "strict", False) is True:
            raise RuntimeError(meta["layout_model"]["error"])
        return
    started = time.perf_counter()
    try:
        if image is None:
            image = renderer.render_page(page_num, dpi=config.get("layout_model", {}).get("render_dpi", 144))
        if isinstance(doc_page, pymupdf.Page):
            from ocr_pdf_io.coordinate_transform import render_coordinate_chain
            meta["layout_model"]["render_transform"] = render_coordinate_chain(doc_page, image.shape).to_dict()
        predicted = engine._run_onnx_dla(image, doc_page, page_num)
        if display_coordinates:
            from ocr_pdf_io.coordinate_transform import page_display_chain
            chain = page_display_chain(doc_page)
            for region in predicted:
                box = chain.bbox(region.bbox.to_list())
                region.bbox = BoundingBox(x0=box[0], y0=box[1], x1=box[2], y1=box[3])
            meta["layout_model"]["native_to_output"] = chain.to_dict()
        text_labels = {"title", "section_header", "text", "header", "footer", "page_number", "caption", "list", "document_index"}
        for block in blocks:
            if len(block.bbox) != 4 or block.block_type == "formula":
                continue
            bb = BoundingBox(x0=block.bbox[0], y0=block.bbox[1], x1=block.bbox[2], y1=block.bbox[3])
            matches = [r for r in predicted if r.label in text_labels and r.bbox.overlap_ratio(bb) >= .7
                       and r.bbox.contains_point((bb.x0 + bb.x1) / 2, (bb.y0 + bb.y1) / 2)]
            if matches:
                region = max(matches, key=lambda r: (_score_or(r.dla_score, 0.0), -r.bbox.area))
                block.block_type = region.label
        regions.extend(predicted)
        meta["layout_model"].update(status="MODEL_OUTPUT", regions=len(predicted),
                                    providers=engine._session.get_providers(),
                                    coordinates=("PDF_DISPLAY_POINTS_TOP_LEFT_CROP_RELATIVE" if display_coordinates
                                                 else "PDF_POINTS_TOP_LEFT_CROP_RELATIVE"),
                                    validated_on_pilot=False)
    except Exception as exc:
        if getattr(engine, "strict", False) is True:
            raise
        meta["layout_model"]["error"] = str(exc)
        logger.warning("Page %d: layout model failed; retaining geometric regions: %s", page_num, exc)
    finally:
        meta["layout_model"]["seconds"] = round(time.perf_counter() - started, 4)


def link_blocks_to_regions(
    blocks: List[TextBlock], regions: List[Region], page_num: int
) -> set[str]:
    linked: set[str] = set()
    for idx, block in enumerate(blocks):
        region = next((r for r in regions if r.region_id == block.region_id), None)
        if region is None and len(block.bbox) >= 4:
            mid_x = (block.bbox[0] + block.bbox[2]) / 2.0
            mid_y = (block.bbox[1] + block.bbox[3]) / 2.0
            candidates = [r for r in regions if r.bbox.contains_point(mid_x, mid_y)]
            preferred = (
                (ContentType.TEXT, ContentType.OUTLINED_TEXT)
                if block.source == "native"
                else (ContentType.IMAGE, ContentType.IMAGE_TABLE, ContentType.TEXT)
            )
            candidates.sort(key=lambda r: (
                0 if r.content_type in preferred else 1,
                r.bbox.area,
            ))
            region = candidates[0] if candidates else None
        if region is None:
            bbox = block.bbox if len(block.bbox) >= 4 else [0.0, 0.0, 0.0, 0.0]
            region = Region(
                region_id=f"p{page_num}_inferred_{idx + 1}",
                bbox=BoundingBox(x0=bbox[0], y0=bbox[1], x1=bbox[2], y1=bbox[3]),
                content_type=ContentType.TEXT,
                source="native" if block.source == "native" else "ocr",
                orientation_status="UNCERTAIN",
                failure_reason="Region inferred from text block bbox",
            )
            regions.append(region)
        block.region_id = region.region_id
        linked.add(region.region_id)
    return linked
