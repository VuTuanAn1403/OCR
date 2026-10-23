from __future__ import annotations
import sys
import time
import math
import re
import hashlib
import logging
from typing import Dict, Any, Optional, List, Tuple
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError, wait as wait_for_futures
import numpy as np
import pymupdf
import cv2

logger = logging.getLogger(__name__)

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from ocr_artifacts.digest import sha256_json_ascii
from ocr_recognition import hallucination as _hallucination, orientation as _orientation
from ocr_layout import steps as _layout_steps
from ocr_structure import enrichment as _enrichment
from ocr_recognition.inference import predict_image_counted
from ocr_recognition.ocr_layer_agreement import page_layer_agreement
from ocr_pdf_io.scan_image import full_page_image_provenance
from ocr_workers.page_engines import build_page_engines, validate_page_config
from ocr_recognition.blocks import mark_review_regions, ocr_results_to_blocks
from ocr_structure.enrichment import drop_blocks_inside_tables
from ocr_document.page_assembly import assign_region_statuses, build_evidence_blocks, build_page_quality
from src.ocr.domain.models.page import ExtractedPage
from src.ocr.domain.models.text_block import TextBlock
from src.ocr.domain.models.quality import PageQualityReport
from src.ocr.domain.models.region import ContentType, Region, BoundingBox
from src.ocr.domain.models.evidence_block import EvidenceBlock
from src.ocr.domain.routing.page_type import PageType
from src.ocr.infrastructure.pdf.pdf_inspector import PDFInspector
from src.ocr.infrastructure.pdf.pdf_renderer import PDFRenderer
from src.ocr.infrastructure.pdf.region_cropper import RegionCropper
from src.ocr.infrastructure.pdf.native_text_extractor import NativeTextExtractor
from src.ocr.infrastructure.ocr.vietnamese_seq2seq_engine import VietnameseSeq2SeqEngine
from src.ocr.infrastructure.ocr.rapidocr_engine import RapidOCREngine
from src.ocr.infrastructure.ocr.fallback_engine import FallbackEngine
from src.ocr.infrastructure.quality.ocr_quality import OCRQualityEvaluator
from src.ocr.infrastructure.layout.document_layout_engine import DocumentLayoutEngine
from src.ocr.infrastructure.layout.page_content_analyzer import PageContentAnalyzer
from src.ocr.infrastructure.postprocessing.reading_order import READING_ORDER_METHODS, ReadingOrderSorter
from src.ocr.infrastructure.postprocessing.xy_cut import METHOD as XY_CUT_METHOD
from src.ocr.infrastructure.pdf.scan_image import (
    acquire_page_image, full_page_image_info, validate_settings as validate_scan_image_settings)
from src.ocr.infrastructure.quality.ocr_layer_agreement import (
    METHOD as OCR_LAYER_METHOD, measure_agreement as measure_ocr_layer_agreement)
from src.ocr.infrastructure.postprocessing.unicode_normalizer import UnicodeNormalizer
from src.ocr.infrastructure.postprocessing.text_cleaner import TextCleaner
from src.ocr.infrastructure.quality.vietnamese_quality import VietnameseQualityEvaluator
from ocr_recognition.diacritic_retry import retry_diacritic_blocks
from ocr_text.vietnamese_diacritics import DIACRITIC_REVIEW_CODE
from src.ocr.infrastructure.cache.artifact_cache import ArtifactCache
from src.ocr.application.route_page import RoutePageUseCase
from src.ocr.application.reocr_region import ReocrRegionUseCase
from src.ocr.infrastructure.export.markdown_exporter import MarkdownExporter
from src.ocr.infrastructure.layout.docling_structure import (
    DoclingStructureExtractor, DoclingStructureError, block_is_covered,
)
from src.ocr.infrastructure.export.manifest_exporter import PIPELINE_VERSION
from src.ocr.domain.models.schema import PAGE_SCHEMA_VERSION
from src.ocr.runtime.config import ConfigError, config_hash
from src.ocr.runtime.fingerprint import source_fingerprint
from src.ocr.runtime.models import model_fingerprint
from src.ocr.runtime.structured_logging import log_context, progress
from src.ocr.infrastructure.layout.dla_engine import DLAEngine

def _known(values) -> List[float]:
    """Drop unavailable (None) scores."""
    return [v for v in values if v is not None]


def _mean(values) -> Optional[float]:
    known = _known(values)
    return sum(known) / len(known) if known else None


def _score_or(value: Optional[float], default: float) -> float:
    return default if value is None else value


class ProcessPageUseCase:
    """
    Orchestrates extraction for a single PDF page:
    Route -> Native Extract or OCR -> Quality Gate -> Regional Fallback -> Layout/Tables -> Reading Order -> Cache.
    """
    _current_page_ocr_calls: int = 0
    _page_errors: int = 0
    _crop_cache: Dict[str, Any] = {}
    _rejected_evidence: List[Any] = []

    def __init__(
        self,
        doc: pymupdf.Document,
        config: Dict[str, Any],
        doc_hash: str,
        cache: Optional[ArtifactCache] = None,
        structure_extractor: Optional[DoclingStructureExtractor] = None,
    ):
        self.doc = doc
        self.config = config
        from src.ocr.runtime.config import document_layout_settings, furniture_settings
        self.document_layout = document_layout_settings(config)
        self.legacy_furniture = furniture_settings(self.document_layout)["method"] == "legacy_v6_1"
        self.doc_hash = doc_hash
        self.cache = cache

        # One composition root for page engines (ocr_workers.page_engines, P09b).
        engines = build_page_engines(doc, config, legacy_furniture=self.legacy_furniture,
                                     structure_extractor=structure_extractor)
        self.inspector = engines.inspector
        self.renderer = engines.renderer
        self.native_extractor = engines.native_extractor
        self.ocr_engine = engines.ocr_engine
        self.ocr_quality = engines.ocr_quality
        self.layout_engine = engines.layout_engine
        self._owns_structure_extractor = engines.owns_structure_extractor
        self.structure_extractor = engines.structure_extractor
        self.content_analyzer = engines.content_analyzer
        self.fallback_engine = engines.fallback_engine
        self.reocr_use_case = ReocrRegionUseCase(self.renderer, self.fallback_engine)
        self.native_first = validate_page_config(config)
        self._current_page_ocr_calls = 0
        self._page_errors = 0
        self._crop_cache: Dict[str, Any] = {}
        self._rejected_evidence: List[Any] = []
        self.cache_key = self._build_cache_key()

    def _build_cache_key(self) -> str:
        """Profile name plus a digest of everything that changes page output
        (ENV-04): resolved config, schema, code and Docling fingerprints."""
        parts = {
            "config": config_hash(self.config),
            "schema": PAGE_SCHEMA_VERSION,
            "pipeline": PIPELINE_VERSION,
            "code": source_fingerprint(),
            "models": model_fingerprint(self.config),
            "docling": self.structure_extractor.cache_fingerprint() if self.structure_extractor.enabled else None,
        }
        digest = sha256_json_ascii(parts)[:16]
        return f"{self.config.get('profile', 'balanced')}-{digest}"

    def close(self) -> None:
        executor = getattr(self, "_ocr_executor", None)
        if executor is not None:
            executor.shutdown(wait=True)
            self._ocr_executor = None
        if getattr(self, "_owns_structure_extractor", True):
            self.structure_extractor.close()

    def _apply_layout_model(self, doc_page, page_num, blocks, regions, meta, image=None):
        """Moved to ocr_layout.steps.apply_layout_model (P06)."""
        # The renderer is only needed when no image is passed (as before the move).
        return _layout_steps.apply_layout_model(self.content_analyzer.dla_engine, getattr(self, "renderer", None), self.config,
                                                doc_page, page_num, blocks, regions, meta, image)

    def _enrich_structures(self, doc_page, page_num, page_type, blocks, tables, regions, meta):
        """Moved to ocr_structure.enrichment.enrich_structures (P07)."""
        return _enrichment.enrich_structures(self.structure_extractor, doc_page, page_num, page_type,
                                             blocks, tables, regions, meta)

    @staticmethod
    def _full_page_image(doc_page) -> Optional[Dict[str, Any]]:
        return full_page_image_provenance(doc_page)  # ocr_pdf_io.scan_image (P09b)

    def _ocr_layer_agreement(self, doc_page, blocks, meta) -> Dict[str, Any]:
        return page_layer_agreement(  # ocr_recognition.ocr_layer_agreement (P09b)
            doc_page, blocks, meta, self.config.get("ocr_layer_agreement", {}).get("sample_lines", 5))

    def _is_native_eligible(self, page_type: PageType, native_score: float, meta: Dict[str, Any]) -> bool:
        if meta.get("native_extraction_failed", False):
            return False
        if page_type in (PageType.NATIVE_TEXT, PageType.MIXED):
            # Same key RoutingPolicy uses (one threshold source, ENV-13).
            return native_score >= self.config.get("native_quality", {}).get("review_threshold", 0.70)
        return (page_type == PageType.PRODUCT_SHOWCASE_COLLAGE and meta.get("char_count", 0) >= 30
                and not meta.get("unicode_corruption_detected", False))

    def _record_ocr_failure(self, message: str) -> None:
        self._page_errors = getattr(self, "_page_errors", 0) + 1
        if not hasattr(self, "_ocr_failures"):
            self._ocr_failures = []
        self._ocr_failures.append(message)

    def _predict_image_counted(
        self, img_bgr: np.ndarray, timeout_seconds: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        # Moved to ocr_recognition.inference (P09b).
        return predict_image_counted(self, img_bgr, timeout_seconds)

    def execute(
        self,
        page_num: int,
        total_pages: int,
        router: RoutePageUseCase,
        resume: bool = False
    ) -> ExtractedPage:
        with log_context(page=page_num):  # ENV-11: every page log names its page
            return self._execute_page(page_num, total_pages, router, resume)

    def _execute_page(self, page_num: int, total_pages: int, router: RoutePageUseCase,
                      resume: bool) -> ExtractedPage:
        t0 = time.perf_counter()
        self._current_page_ocr_calls = 0
        self._page_errors = 0
        self._ocr_failures: List[str] = []
        cache_profile = self.cache_key
        render_dpi = self.config.get("render_dpi", 180)
        page_timeout_seconds = float(self.config.get("page_timeout_seconds", 120))
        self._active_page_deadline = page_timeout_seconds

        # 1. Check cache if resume is active
        if resume and self.cache:
            cached = self.cache.get_cached_page(self.doc_hash, page_num, cache_profile, render_dpi)
            if cached is not None:
                cached.quality.from_cache = True
                progress(f"[{page_num}/{total_pages}] page={page_num} [CACHED] restored from cache", stage="cache")
                return cached

        # 2. Inspect page metadata
        meta = self.inspector.inspect_page(page_num)
        page_type, native_score = router.execute(meta)

        page_w = meta["width"]
        page_h = meta["height"]

        # 2b. V3.1.2 Content Composition — decompose page into regions
        doc_page = self.doc[page_num - 1]
        if self.config.get("ocr_source_policy") == "gpu_ocr_only_v1":
            # Full-page OCR scales rendered pixels into page.rect (display
            # points). Bring native geometry and layout predictions into that
            # same frame; leave the source PDF and its /Rotate unchanged.
            from src.ocr.infrastructure.pdf.coordinate_transform import page_display_chain
            meta["coordinate_space"] = {"name": "pdf_display_points",
                "native_to_output": page_display_chain(doc_page).to_dict()}
            regions = self.content_analyzer.analyze(meta, doc_page, display_coordinates=True)
        else:
            regions = self.content_analyzer.analyze(meta, doc_page)
        inspect_duration = time.perf_counter() - t0
        native_extract_duration = 0.0
        render_duration = 0.0
        ocr_duration = 0.0
        image_region_ocr_duration = 0.0
        orientation_retry_duration = 0.0
        fallback_duration = 0.0
        table_duration = 0.0
        reading_order_duration = 0.0
        recognized_lines = 0
        recognizer_confidences: List[float] = []
        from collections import Counter
        region_type_counts = dict(Counter(r.content_type.value for r in regions))

        progress(f"[{page_num}/{total_pages}] page={page_num} type={page_type.value} dpi={render_dpi} regions={len(regions)} {region_type_counts}",
                 stage="route", page_type=page_type.value, regions=region_type_counts)

        blocks: List[TextBlock] = []
        self._current_page_diagrams: List[Any] = []
        self._rejected_evidence: List[EvidenceBlock] = []
        page_errors: List[str] = []
        fallback_count = 0
        suspicious_lines: List[str] = []
        candidates_for_fallback: List[TextBlock] = []
        actual_dpi = None
        page_timeout_seconds = float(self.config.get("page_timeout_seconds", 120))

        is_native_eligible = self._is_native_eligible(page_type, native_score, meta)
        # Ablation A1 (proposal 9.4): `native_first: false` OCRs every page and
        # also disables the defensive native recovery and vector tables below.
        native_first = getattr(self, "native_first", True)
        if not native_first:
            is_native_eligible = False
            meta["routing_override"] = "native_first_disabled"

        if is_native_eligible:
            t_nat_start = time.perf_counter()
            # Preserve copied text and any line-level diacritic review flags.
            blocks = self.native_extractor.extract_blocks(page_num)
            for b in blocks:
                b.quality_score = min(b.quality_score, round(native_score, 4)) if b.quality_score is not None else None
                b.confidence = round(native_score, 4)
                b.confidence_source = "native_text_score"
                if b.bbox and len(b.bbox) >= 4:
                    dla = getattr(self.content_analyzer, "dla_engine", None)
                    if dla and hasattr(dla, "_classify_text_block"):
                        try:
                            res = dla._classify_text_block(
                                text=b.text,
                                bbox=BoundingBox(x0=b.bbox[0], y0=b.bbox[1], x1=b.bbox[2], y1=b.bbox[3]),
                                page_h=page_h,
                                page_w=page_w,
                                page_num=page_num,
                                base_font_size=11.0,
                                header_band_y=page_h * 0.10,
                                footer_band_y=page_h * 0.90,
                            )
                            if isinstance(res, (tuple, list)) and len(res) >= 2:
                                b.block_type = res[1]
                        except Exception as e:
                            logger.warning("Page %d layout classification failed for native block: %s", page_num, e)

            if not blocks and page_type == PageType.MIXED:
                # Defensive fallback: If native extractor returned 0 blocks on mixed page,
                # fall through to OCR to avoid content loss.
                is_native_eligible = False
            native_extract_duration = time.perf_counter() - t_nat_start

        if is_native_eligible:
            image_ocr_blocks: List[TextBlock] = []
            if (time.perf_counter() - t0) > page_timeout_seconds:
                logger.warning("Page %d exceeded timeout (%ss) before image region OCR", page_num, page_timeout_seconds)
                page_errors.append(f"Page timeout ({page_timeout_seconds}s) exceeded before image OCR")
            else:
                # Determine which regions require regional OCR (V4.0 Pillar 2: Vector & Diagram preservation):
                page_area = max(1.0, page_w * page_h)
                if page_type == PageType.PRODUCT_SHOWCASE_COLLAGE:
                    target_regions = [
                        r for r in regions
                        if r.content_type in (ContentType.IMAGE_TABLE, ContentType.DIAGRAM)
                        or (r.content_type in (ContentType.IMAGE, ContentType.FIGURE)
                            and r.bbox.area / page_area >= 0.02)
                    ]
                elif page_type == PageType.MIXED or meta.get("layout_type") in ("TWO_UP", "MULTI_REGION"):
                    target_regions = [
                        r for r in regions
                        if r.content_type in (ContentType.IMAGE, ContentType.IMAGE_TABLE, ContentType.VECTOR, ContentType.DIAGRAM)
                    ]
                else:
                    target_regions = [
                        r for r in regions
                        if r.content_type in (ContentType.IMAGE_TABLE, ContentType.DIAGRAM)
                        or (r.content_type in (ContentType.IMAGE, ContentType.FIGURE)
                            and r.bbox.area / page_area >= 0.20)
                    ]

                t_img_ocr = time.perf_counter()
                image_ocr_blocks = self._extract_image_regions(
                    doc_page,
                    page_num,
                    target_regions,
                    blocks,
                    render_dpi,
                    evaluate_all_orientations=meta.get("layout_type") in ("TWO_UP", "MULTI_REGION"),
                )
                image_region_ocr_duration = time.perf_counter() - t_img_ocr
                if image_ocr_blocks:
                    blocks.extend(image_ocr_blocks)
                    recognized_lines += len(image_ocr_blocks)
                    recognizer_confidences.extend(_known(b.confidence for b in image_ocr_blocks))

            if page_type == PageType.MIXED:
                progress(f"[{page_num}/{total_pages}] mixed composition: native={len(blocks) - len(image_ocr_blocks)} image_ocr={len(image_ocr_blocks)} lines", stage="native")
            elif image_ocr_blocks:
                progress(f"[{page_num}/{total_pages}] native+image_table: native={len(blocks) - len(image_ocr_blocks)} image_ocr={len(image_ocr_blocks)} lines", stage="native")
            else:
                progress(f"[{page_num}/{total_pages}] native={len(blocks)} lines (native text gate passed: {native_score:.2f})", stage="native")

        else:
            # Route to full-page OCR (scanned pages, corrupted native text, low-quality OCR layers)
            actual_dpi = render_dpi
            t_render_start = time.perf_counter()
            # Source DPI of the page image (C2.2): metadata for DPI-group reports.
            meta["full_page_image"] = self._full_page_image(doc_page)
            if self.config.get("scan_image"):  # opt-in embedded image / DPI policy (R-08)
                img_bgr, meta["scan_image"] = acquire_page_image(
                    self.doc, page_num, self.renderer, render_dpi, self.config["scan_image"])
                actual_dpi = meta["scan_image"]["processing_dpi"]
            else:
                img_bgr = self.renderer.render_page(page_num, dpi=render_dpi)
            refined_regions = regions
            if self.config.get("two_up_detection_enabled", True) or self.config.get("multi_region_detection_enabled", True):
                refined_regions = self.content_analyzer.refine_with_rendered_image(
                    meta, regions, img_bgr
                )
            if refined_regions:
                regions = refined_regions
                region_type_counts = dict(Counter(r.content_type.value for r in regions))
                meta["region_count"] = len(regions)
            render_duration = time.perf_counter() - t_render_start
            t_ocr_start = time.perf_counter()
            ocr_results, orientation_fallback = self._predict_page_ocr(
                img_bgr, regions, page_w, page_h, meta)
            if orientation_fallback:
                meta["orientation_fallback"] = orientation_fallback
                progress(f"[{page_num}/{total_pages}] orientation_fallback={orientation_fallback}", stage="ocr")
            ocr_duration = time.perf_counter() - t_ocr_start
            recognized_lines = len(ocr_results)
            recognizer_confidences = _known(result.get("confidence") for result in ocr_results)
            progress(f"[{page_num}/{total_pages}] primary={len(ocr_results)} lines time={ocr_duration:.2f}s", stage="ocr",
                     lines=len(ocr_results), seconds=round(ocr_duration, 3))

            # Check if this is a 1-Up landscape scan (full-page scan rotated 90 deg) or 180 deg scan
            is_1up_rotated_90 = (
                meta.get("layout_type") not in ("TWO_UP", "MULTI_REGION")
                and orientation_fallback in ("rotate_90_cw", "rotate_90_ccw")
            )
            is_1up_rotated_180 = (
                meta.get("layout_type") not in ("TWO_UP", "MULTI_REGION")
                and orientation_fallback == "rotate_180"
            )

            if is_1up_rotated_90:
                # Upright coordinate space: Swap page dimensions to effective landscape
                page_w, page_h = page_h, page_w
                meta["effective_width"] = page_w
                meta["effective_height"] = page_h
                meta["is_1up_landscape"] = True
                meta["page_orientation"] = "LANDSCAPE"
                # In 90 deg rotation, rotated image width is img_bgr.shape[0] and height is img_bgr.shape[1]
                rot_w = img_bgr.shape[0]
                rot_h = img_bgr.shape[1]
                scale_x = page_w / max(1.0, rot_w)
                scale_y = page_h / max(1.0, rot_h)
            elif is_1up_rotated_180:
                meta["is_180_rotated"] = True
                rot_w = img_bgr.shape[1]
                rot_h = img_bgr.shape[0]
                scale_x = page_w / max(1.0, rot_w)
                scale_y = page_h / max(1.0, rot_h)
            else:
                scale_x = page_w / max(1.0, img_bgr.shape[1])
                scale_y = page_h / max(1.0, img_bgr.shape[0])

            # Moved to ocr_recognition.blocks (P09b); appends to blocks, candidates,
            # suspicious lines, rejected evidence and regions exactly as before.
            ocr_results_to_blocks(
                ocr_results, regions=regions, page_num=page_num, scale_x=scale_x, scale_y=scale_y,
                use_raw_bbox=is_1up_rotated_90 or is_1up_rotated_180, page_w=page_w, page_h=page_h,
                ocr_quality=self.ocr_quality, dla_engine=getattr(self.content_analyzer, "dla_engine", None),
                numeric_retry_threshold=float(self.config.get("numeric_retry_threshold", 0.85)),
                rejected_evidence=self._rejected_evidence, blocks=blocks,
                candidates_for_fallback=candidates_for_fallback, suspicious_lines=suspicious_lines)

            if page_type == PageType.SCANNED_WITH_OCR_LAYER:
                # Before re-OCR changes any line: layer vs primary OCR (C2.1).
                meta["ocr_layer_agreement"] = self._ocr_layer_agreement(doc_page, blocks, meta)

            # 4. Adaptive Regional Fallback (if enabled)
            fallback_enabled = self.config.get("fallback_enabled", True) or self.config.get("fallback_only_on_review", False)
            if fallback_enabled and candidates_for_fallback:
                max_ratio = self.config.get("max_fallback_region_ratio", 0.15)
                max_count = self.config.get("max_fallback_regions_per_page", 20)
                total_lines = len(blocks)

                budget = min(max_count, max(1, math.ceil(total_lines * max_ratio))) if total_lines else 0
                if budget > 0:
                    t_fallback_start = time.perf_counter()
                    upscale_dpi = self.config.get("fallback_upscale_dpi", 250)
                    priority_candidates = sorted(
                        (block for block in candidates_for_fallback
                         if not (self.config.get("diacritic_retry", {}).get("enabled", False)
                                 and DIACRITIC_REVIEW_CODE in block.review_reason_codes)),
                        key=lambda block: (_score_or(block.quality_score, 0.0), _score_or(block.confidence, 0.0)),
                    )[:budget]
                    _, improved = self.reocr_use_case.execute(
                        page_num=page_num,
                        blocks_to_retry=priority_candidates,
                        upscale_dpi=upscale_dpi
                    )
                    fallback_count = improved
                    fallback_duration = time.perf_counter() - t_fallback_start

            mark_review_regions(candidates_for_fallback, regions)  # ocr_recognition.blocks (P09b)

        # Defensive Native Text Recovery: If OCR produced 0 blocks but the underlying PDF page
        # contains clean digital native text, recover native text to prevent accidental empty pages
        # and IMAGE_PRESERVED_NO_TEXT degeneration.
        if (native_first and not blocks and meta.get("char_count", 0) >= 20
                and not meta.get("unicode_corruption_detected", False)
                and not meta.get("has_hidden_ocr_layer") and not meta.get("hidden_text_only")):
            logger.info("Page %d: OCR returned 0 blocks but native text exists (%d chars). Applying defensive native recovery.", page_num, meta.get("char_count", 0))
            blocks = self.native_extractor.extract_blocks(page_num)
            for b in blocks:
                b.quality_score = min(b.quality_score, round(native_score, 4)) if b.quality_score is not None else None
                b.confidence = round(native_score, 4)
                b.confidence_source = "native_text_score"
                if b.bbox and len(b.bbox) >= 4:
                    dla = getattr(self.content_analyzer, "dla_engine", None)
                    if dla and hasattr(dla, "_classify_text_block"):
                        try:
                            res = dla._classify_text_block(
                                text=b.text,
                                bbox=BoundingBox(x0=b.bbox[0], y0=b.bbox[1], x1=b.bbox[2], y1=b.bbox[3]),
                                page_h=page_h,
                                page_w=page_w,
                                page_num=page_num,
                                base_font_size=11.0,
                                header_band_y=page_h * 0.10,
                                footer_band_y=page_h * 0.90,
                            )
                            if isinstance(res, (tuple, list)) and len(res) >= 2:
                                b.block_type = res[1]
                        except Exception as e:
                            logger.warning("Page %d layout classification failed for fallback native block: %s", page_num, e)

        t_retry_start = time.perf_counter()
        retry_record = retry_diacritic_blocks(self, page_num, blocks, candidates_for_fallback, suspicious_lines)
        fallback_duration += time.perf_counter() - t_retry_start
        fallback_count += retry_record["improved"]
        if self.config.get("diacritic_retry") or retry_record["suspect_lines"]:
            meta["diacritic_retry"] = retry_record

        # 5. Extract tables (doc_page already obtained during content analysis)
        self._apply_layout_model(doc_page, page_num, blocks, regions, meta,
                                 None if is_native_eligible else img_bgr)
        from src.ocr.infrastructure.structure.source_identity import lock_text_evidence
        from src.ocr.infrastructure.postprocessing.document_furniture import protect_table_continuation_lines
        # Protect continuation signals before any structure worker can absorb
        # text, and freeze evidence before sorting/removal changes list order.
        from types import SimpleNamespace
        if self.document_layout["method"] != "legacy":
            protect_table_continuation_lines([SimpleNamespace(page_num=page_num, blocks=blocks)])
            lock_text_evidence(blocks, self.doc_hash, page_num, meta)
        # Opt-in evidence for C3.5(a) experiments. Table extraction removes
        # covered blocks later; A and B must still receive the same OCR lines.
        if self.config.get("retain_table_ocr_lines", False):
            meta["table_ocr_evidence"] = {
                "method": "post-fallback-pre-table-v1",
                "lines": [b.to_dict() for b in blocks
                          if b.source in ("primary_ocr", "fallback_ocr", "image_ocr")],
            }
        layout_model_duration = meta.get("layout_model", {}).get("seconds", 0.0)
        t_table_start = time.perf_counter()
        allow_vector_tables = (
            native_first  # vector tables read native words; off in ablation A1
            and page_type in (PageType.NATIVE_TEXT, PageType.MIXED)
            and native_score >= self.config.get("vector_table_min_native_score", 0.90)
            and not meta.get("native_extraction_failed", False)
            and not (
                self.config.get("skip_vector_tables_on_restricted_pdf", True)
                and meta.get("copy_restricted", False)
            )
        )
        table_rejections: List[Dict[str, Any]] = []
        tables = self.layout_engine.extract_tables(
            doc_page,
            blocks,
            page_num,
            allow_vector_tables=allow_vector_tables,
            regions=regions,
            rejections=table_rejections,
        )
        if table_rejections:
            # Kept as text, not dropped: the review trail of C3.5(g).
            meta["table_rejections"] = table_rejections

        t_docling_start = time.perf_counter()
        blocks, tables, formulas = self._enrich_structures(
            doc_page, page_num, page_type, blocks, tables, regions, meta)
        docling_duration = time.perf_counter() - t_docling_start
        if meta["docling_structure"]["status"] == "FAILED_FALLBACK":
            page_errors.append(meta["docling_structure"]["error"])
        elif meta["docling_structure"].get("errors"):
            page_errors.extend(str(error) for error in meta["docling_structure"]["errors"])
        page_errors.extend(self._ocr_failures)

        # Filter out text blocks that fall inside legitimate tables to prevent duplication
        blocks = drop_blocks_inside_tables(blocks, tables, self.layout_engine)  # ocr_structure (P09b)
        table_duration = time.perf_counter() - t_table_start - docling_duration

        # 6. Sort Reading Order
        t_ro_start = time.perf_counter()
        reading_order = self.config.get("reading_order", {})
        order_sorter = ReadingOrderSorter(page_width=page_w, page_height=page_h,
                                          method=reading_order.get("method", "heuristic"),
                                          min_gap=reading_order.get("min_gap", 3.0))
        order_sorter.classify_furniture = self.legacy_furniture
        sorted_blocks = order_sorter.sort_blocks(blocks)
        if reading_order:  # explicit choice (C3.4 experiment) is recorded; the default stays unchanged
            meta["reading_order"] = {"method": order_sorter.method, "min_gap": order_sorter.min_gap,
                                     **({"version": XY_CUT_METHOD} if order_sorter.method == "xycut" else {})}
        reading_order_duration = time.perf_counter() - t_ro_start

        block_regions = self._link_blocks_to_regions(sorted_blocks, regions, page_num)
        assign_region_statuses(regions, block_regions, tables, meta.get("orientation_fallback"))  # ocr_document (P09b)

        total_time = round(time.perf_counter() - t0, 2)
        durations = {"inspect": inspect_duration, "native_extract": native_extract_duration,
                     "image_region_ocr": image_region_ocr_duration, "render_and_refine": render_duration,
                     "primary_ocr": ocr_duration, "fallback": fallback_duration, "table": table_duration,
                     "docling_structure": docling_duration, "layout_model": layout_model_duration,
                     "reading_order": reading_order_duration}
        quality_report, calibrated_q = build_page_quality(  # ocr_document.page_assembly (P09b)
            page_num=page_num, page_type=page_type, native_score=native_score, total_time=total_time,
            recognizer_confidences=recognizer_confidences, sorted_blocks=sorted_blocks, tables=tables,
            diagrams=self._current_page_diagrams, regions=regions, rejected_evidence=self._rejected_evidence,
            candidates_for_fallback=candidates_for_fallback, suspicious_lines=suspicious_lines,
            ocr_calls=self._current_page_ocr_calls, page_errors=page_errors, recognized_lines=recognized_lines,
            fallback_count=fallback_count, durations=durations, meta=meta,
            allow_vector_tables=allow_vector_tables, region_type_counts=region_type_counts)

        # 7. V3.1.2 EvidenceBlock intermediate representation (spec §3)
        evidence_blocks = build_evidence_blocks(sorted_blocks, regions, page_num, self._rejected_evidence)

        extracted_page = ExtractedPage(
            page_num=page_num,
            width=page_w,
            height=page_h,
            page_type=page_type,
            rendered_dpi=actual_dpi,
            blocks=sorted_blocks,
            tables=tables,
            formulas=formulas,
            diagrams=self._current_page_diagrams,
            regions=regions,
            evidence_blocks=evidence_blocks,
            quality=quality_report,
            metadata=meta
        )

        # Export page markdown
        extracted_page.markdown_content = MarkdownExporter.export_page_markdown(extracted_page)

        # Save to cache
        if self.cache:
            if (meta.get("layout_model", {}).get("status") != "FAILED_FALLBACK"
                    and meta["docling_structure"]["status"] not in ("FAILED_FALLBACK", "partial_success")
                    and not meta["docling_structure"].get("errors")):
                self.cache.save_cached_page(self.doc_hash, extracted_page, cache_profile, render_dpi)

        quality_text = f"{calibrated_q:.2f}" if calibrated_q is not None else "n/a"
        progress(f"[{page_num}/{total_pages}] quality={quality_text} fallback={fallback_count}/{len(sorted_blocks)}", stage="quality")
        progress(f"[{page_num}/{total_pages}] completed time={total_time:.2f}s", stage="complete", seconds=round(total_time, 3))

        return extracted_page

    # Moved to ocr_layout.steps (P06).
    _link_blocks_to_regions = staticmethod(_layout_steps.link_blocks_to_regions)

    # Moved to ocr_recognition.hallucination (P06); kept for callers of the class.
    VN_LEXICON_WORDS = _hallucination.VN_LEXICON_WORDS
    VN_VOWELS = _hallucination.VN_VOWELS
    EN_COMMON_WORDS = _hallucination.EN_COMMON_WORDS

    @classmethod
    def classify_ocr_hallucination(cls, text: str, conf: Optional[float]) -> Tuple[bool, Optional[str]]:
        return _hallucination.classify_ocr_hallucination(text, conf)

    @classmethod
    def _calculate_vn_lexicon_ratio(cls, results: List[Dict[str, Any]]) -> float:
        return _hallucination.calculate_vn_lexicon_ratio(results)

    def _predict_page_ocr(self, img_bgr, regions, page_w, page_h, meta):
        """Bound regional OCR work; noisy segmentation falls back to one page."""
        enabled = self.config.get("orientation_fallback_enabled", True)
        if (self.config.get("ocr_source_policy") != "gpu_ocr_only_v1"
                and self.config.get("two_up_detection_enabled", True)
                and meta.get("layout_type") in ("TWO_UP", "MULTI_REGION")
                and 2 <= len(regions) <= 10):
            return self._predict_region_ocr(img_bgr, regions, page_w, page_h, enabled=enabled)
        return self._predict_with_orientation_fallback(img_bgr, enabled=enabled)

    def _predict_with_orientation_fallback(
        self,
        img_bgr,
        enabled: bool = True,
        allow_hybrid: bool = True,
        evaluate_all_orientations: bool = False,
    ):
        """Retry a failed landscape or 180-degree scan after rotating it for the detector.

        Evaluates orientations when first pass fails, produces vertical glyph noise,
        has low Vietnamese lexicon ratio (< 12%), or when evaluate_all_orientations is requested.
        """
        results = self._predict_image_counted(img_bgr)
        is_noise = self._is_glyph_noise(results)
        vn_ratio = self._calculate_vn_lexicon_ratio(results)

        # A high-confidence full page can be readable even when the recognizer omits
        # Vietnamese diacritics. Avoid three unnecessary rotated OCR passes in that case.
        if (
            results and not is_noise and not evaluate_all_orientations
            and (vn_ratio >= 0.12 or self._is_readable_ocr_layout(results))
        ):
            return results, None

        if not enabled:
            return results, None

        height, width = img_bgr.shape[:2]
        candidates = []
        if results and not is_noise:
            candidates.append((self._orientation_candidate_score(results, label=None), results, None, vn_ratio))

        # Rotate order: 90_CW is standard for landscape tables in Vietnamese portrait PDFs (top is on left),
        # followed by 90_CCW and 180.
        for code, label in (
            (cv2.ROTATE_90_CLOCKWISE, "rotate_90_cw"),
            (cv2.ROTATE_90_COUNTERCLOCKWISE, "rotate_90_ccw"),
            (cv2.ROTATE_180, "rotate_180"),
        ):

            rotated = cv2.rotate(img_bgr, code)
            rotated_results = self._predict_image_counted(rotated)
            if not rotated_results or self._is_glyph_noise(rotated_results):
                continue

            found_any = True
            rot_vn_ratio = self._calculate_vn_lexicon_ratio(rotated_results)

            mapped = []
            for item in rotated_results:
                bbox = item.get("bbox", [])
                if len(bbox) < 4:
                    continue
                rx0, ry0, rx1, ry1 = bbox
                if code == cv2.ROTATE_90_CLOCKWISE:
                    mapped_bbox = [ry0, height - rx1, ry1, height - rx0]
                elif code == cv2.ROTATE_90_COUNTERCLOCKWISE:
                    mapped_bbox = [width - ry1, rx0, width - ry0, rx1]
                else:  # ROTATE_180
                    mapped_bbox = [width - rx1, height - ry1, width - rx0, height - ry0]
                mapped_item = dict(item)
                mapped_item["bbox"] = [round(float(v), 2) for v in mapped_bbox]
                mapped_item["raw_bbox"] = [round(float(v), 2) for v in bbox]
                mapped.append(mapped_item)
            if mapped:
                candidates.append((self._orientation_candidate_score(mapped, label=label), mapped, label, rot_vn_ratio))

        if candidates:
            # If 0 deg was already valid text (not noise), require a significant score margin
            # or higher Vietnamese lexicon density before overriding with a rotation
            orig_candidate = next((c for c in candidates if c[2] is None), None)
            best_score, best_results, best_label, best_vn_ratio = max(candidates, key=lambda item: item[0])
            if orig_candidate and best_label is not None:
                orig_score, orig_results, _, orig_vn_ratio = orig_candidate
                # A small language-score gain can come from hallucinated words
                # on an upside-down crop. Keep the original angle and expose
                # ambiguity instead of silently rotating it.
                strong_language_recovery = orig_vn_ratio <= 0.02 and best_vn_ratio >= 0.25
                if best_score < orig_score + 8.0 and not strong_language_recovery:
                    return orig_results, "orientation_uncertain"
                if best_label == "rotate_180" and orig_vn_ratio >= 0.12 and best_vn_ratio <= orig_vn_ratio * 1.5:
                    return orig_results, None
            return best_results, best_label

        # If all rotations returned noise or empty, return original results if any
        if results:
            return results, None

        # Hybrid 2-Up check for landscape pages with mixed orientation sub-regions
        if allow_hybrid and width >= height * 1.25:
            hybrid_results, hybrid_label = self._predict_hybrid_2up(img_bgr, enabled=enabled)
            if hybrid_results:
                return hybrid_results, hybrid_label

        return [], None

    # Moved to ocr_recognition.orientation (P06).
    _is_readable_ocr_layout = staticmethod(_orientation.is_readable_ocr_layout)
    _is_glyph_noise = staticmethod(_orientation.is_glyph_noise)
    _orientation_candidate_score = staticmethod(_orientation.orientation_candidate_score)

    def _predict_region_ocr(
        self,
        img_bgr,
        regions: List[Region],
        page_width: float,
        page_height: float,
        enabled: bool = True,
    ):
        """OCR each detected Two-Up/multi-region crop and restore page pixels."""
        image_h, image_w = img_bgr.shape[:2]
        combined = []
        orientations = []
        image_regions = [
            r for r in regions
            if r.content_type in (ContentType.IMAGE, ContentType.IMAGE_TABLE)
        ]
        route_regions = image_regions if len(image_regions) >= 2 else regions
        for region in sorted(route_regions, key=lambda r: (r.bbox.x0, r.bbox.y0)):
            bb = region.bbox
            px0 = max(0, min(image_w - 1, int(round(bb.x0 / max(page_width, 1.0) * image_w))))
            py0 = max(0, min(image_h - 1, int(round(bb.y0 / max(page_height, 1.0) * image_h))))
            px1 = max(px0 + 1, min(image_w, int(round(bb.x1 / max(page_width, 1.0) * image_w))))
            py1 = max(py0 + 1, min(image_h, int(round(bb.y1 / max(page_height, 1.0) * image_h))))
            crop = img_bgr[py0:py1, px0:px1]
            if crop.size == 0:
                continue

            local_results, label = self._predict_with_orientation_fallback(
                crop,
                enabled=enabled,
                allow_hybrid=False,
                evaluate_all_orientations=False,
            )
            if label:
                orientations.append(f"{region.region_id}:{label}")
                if "90_cw" in label:
                    region.rotation = 90.0
                    region.orientation_status = "CONFIDENT"
                    region.orientation_confidence = 0.80
                elif "90_ccw" in label:
                    region.rotation = 270.0
                    region.orientation_status = "CONFIDENT"
                    region.orientation_confidence = 0.80
                elif "180" in label:
                    region.rotation = 180.0
                    region.orientation_status = "CONFIDENT"
                    region.orientation_confidence = 0.80
                else:
                    region.orientation_status = "UNCERTAIN"
                    region.needs_fallback = True
                    region.failure_reason = "OCR orientations disagree; manual review required"

            for item in local_results:
                bbox = item.get("bbox", [])
                if len(bbox) < 4:
                    continue
                mapped = dict(item)
                mapped["bbox"] = [
                    round(float(bbox[0]) + px0, 2),
                    round(float(bbox[1]) + py0, 2),
                    round(float(bbox[2]) + px0, 2),
                    round(float(bbox[3]) + py0, 2),
                ]
                mapped["region_id"] = region.region_id
                combined.append(mapped)

        return combined, ";".join(orientations) if orientations else None

    def _predict_hybrid_2up(
        self,
        img_bgr,
        enabled: bool = True
    ):
        """
        V3.1.2 Phase F: Hybrid 2-Up orientation processing.
        Splits a landscape page into left and right halves, independently evaluates
        and rotates each half, then maps bounding boxes back to page space.
        """
        if not enabled:
            return [], None

        height, width = img_bgr.shape[:2]
        if width < height * 1.25:
            return [], None

        mid_x = width // 2
        left_img = img_bgr[:, :mid_x]
        right_img = img_bgr[:, mid_x:]

        left_results, left_orient = self._predict_with_orientation_fallback(
            left_img, enabled=True, allow_hybrid=False
        )
        right_results, right_orient = self._predict_with_orientation_fallback(
            right_img, enabled=True, allow_hybrid=False
        )

        if left_results or right_results:
            combined = []
            if left_results:
                combined.extend(left_results)
            if right_results:
                for item in right_results:
                    mapped_item = dict(item)
                    bx = list(item.get("bbox", [0.0, 0.0, 0.0, 0.0]))
                    mapped_item["bbox"] = [
                        round(bx[0] + mid_x, 2),
                        round(bx[1], 2),
                        round(bx[2] + mid_x, 2),
                        round(bx[3], 2),
                    ]
                    combined.append(mapped_item)

            orient_tag = f"hybrid_2up(L:{left_orient or '0'},R:{right_orient or '0'})"
            return combined, orient_tag

        return [], None

    def _extract_image_regions(
        self,
        doc_page: pymupdf.Page,
        page_num: int,
        target_regions: List[Region],
        native_blocks: List[TextBlock],
        render_dpi: int,
        evaluate_all_orientations: bool = False,
    ) -> List[TextBlock]:
        """
        V3.1.2 Phase B: Inspects and extracts text from candidate image regions.
        - Inspects large images even when a sparse native header/footer exists.
        - Skips images substantially covered by clean native text.
        - Runs OCR on cropped regions, maps coordinates back to page.
        - Suppresses OCR blocks that duplicate clean native text blocks (spec §17).
        """
        if not target_regions:
            return []

        image_blocks: List[TextBlock] = []
        page_rect = doc_page.rect
        page_area = max(1.0, float(page_rect.width * page_rect.height))
        native_bboxes = [b.bbox for b in native_blocks if b.bbox and len(b.bbox) >= 4]

        for region in target_regions:
            bb = region.bbox
            # FastIconFilter (spec §4.1): Skip decorative icons, bullets, and micro-images
            if bb.width < 60.0 or bb.height < 40.0 or bb.area < 3000.0:
                continue

            # Check if region is covered by native text blocks
            covered_area = 0.0
            for nb in native_bboxes:
                ix0 = max(bb.x0, nb[0])
                iy0 = max(bb.y0, nb[1])
                ix1 = min(bb.x1, nb[2])
                iy1 = min(bb.y1, nb[3])
                if ix1 > ix0 and iy1 > iy0:
                    covered_area += (ix1 - ix0) * (iy1 - iy0)
            if bb.area > 0 and (covered_area / bb.area) > 0.40:
                continue

            # Crop region and run OCR
            crop_bgr, actual_crop_rect = RegionCropper.crop_page_region(
                doc_page, bb, dpi=render_dpi, margin=3.0
            )
            if crop_bgr.size == 0 or crop_bgr.shape[0] < 16 or crop_bgr.shape[1] < 16:
                continue

            # P1: Fast variance pre-filter to skip blank/flat/gradient images in < 1ms
            crop_gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY) if len(crop_bgr.shape) == 3 else crop_bgr
            if crop_bgr.sum() > 0 and float(np.std(crop_gray)) < 15.0:
                continue

            crop_h, crop_w = crop_bgr.shape[:2]
            try:
                # P4: SHA-256 crop caching across identical graphical headers/logos
                _crop_cache = getattr(self, "_crop_cache", None)
                if _crop_cache is None:
                    _crop_cache = self._crop_cache = {}

                crop_hash = hashlib.sha256(crop_bgr.tobytes()).hexdigest()
                if crop_hash in _crop_cache:
                    ocr_results, orientation_label = _crop_cache[crop_hash]
                else:
                    ocr_results, orientation_label = self._predict_with_orientation_fallback(
                        crop_bgr,
                        enabled=self.config.get("orientation_fallback_enabled", True),
                        evaluate_all_orientations=evaluate_all_orientations,
                    )
                    _crop_cache[crop_hash] = (ocr_results, orientation_label)

                mean_confidence = (
                    sum(_score_or(item.get("confidence"), 0.0) for item in ocr_results) / len(ocr_results)
                    if ocr_results else 0.0
                )
                retry_risk = (
                    not ocr_results or self._is_glyph_noise(ocr_results)
                    or mean_confidence < self.config.get("min_confidence", 0.85)
                )
                num_threshold = float(self.config.get("numeric_retry_threshold", 0.85))
                has_low_conf_number = any(
                    bool(re.search(r"\d", item.get("text", ""))) and _score_or(item.get("confidence"), 0.0) < num_threshold
                    for item in ocr_results
                ) if ocr_results else False
                should_retry_region = (
                    (self.config.get("regional_retry_enabled", False) and retry_risk and bb.area / page_area >= 0.10)
                    or has_low_conf_number
                ) and self.config.get("fallback_upscale_dpi", render_dpi) > render_dpi
                if should_retry_region:
                    retry_crop, retry_rect = RegionCropper.crop_page_region(
                        doc_page, bb,
                        dpi=self.config["fallback_upscale_dpi"], margin=3.0,
                    )
                    if retry_crop.size:
                        retry_results, retry_orientation = self._predict_with_orientation_fallback(
                            retry_crop,
                            enabled=self.config.get("orientation_fallback_enabled", True),
                            evaluate_all_orientations=evaluate_all_orientations,
                        )
                        original_numbers = re.findall(
                            r"\d+(?:[.,/]\d+)*", " ".join(item.get("text", "") for item in ocr_results)
                        )
                        retry_numbers = re.findall(
                            r"\d+(?:[.,/]\d+)*", " ".join(item.get("text", "") for item in retry_results)
                        )
                        if ocr_results and retry_results and original_numbers != retry_numbers and (original_numbers or retry_numbers):
                            region.needs_fallback = True
                            region.failure_reason = "High-DPI OCR disagrees on numeric text; manual review required"
                        elif retry_results and (
                            not ocr_results
                            or self._orientation_candidate_score(retry_results) >
                            self._orientation_candidate_score(ocr_results) + 5.0
                        ):
                            ocr_results = retry_results
                            orientation_label = retry_orientation
                            crop_bgr, actual_crop_rect = retry_crop, retry_rect
                            crop_h, crop_w = retry_crop.shape[:2]
                if orientation_label:
                    if "90_cw" in orientation_label:
                        region.rotation = 90.0
                    elif "90_ccw" in orientation_label:
                        region.rotation = 270.0
                    elif "180" in orientation_label:
                        region.rotation = 180.0
                    if orientation_label == "orientation_uncertain":
                        region.orientation_status = "UNCERTAIN"
                        region.orientation_confidence = 0.0
                        region.needs_fallback = True
                        region.failure_reason = "OCR orientations disagree; manual review required"
                    else:
                        region.orientation_status = "CONFIDENT"
                        region.orientation_confidence = 0.80
                    progress(f"[{page_num}] region {region.region_id} rotation={region.rotation}° ({orientation_label}, {len(ocr_results)} lines)", stage="image_region_ocr")
                elif evaluate_all_orientations:
                    region.orientation_status = "CONFIDENT"
                    region.orientation_confidence = 0.70
            except Exception as e:
                # Recorded as a page error, not only printed: the region text is lost.
                logger.exception("Page %d: region OCR failed for %s", page_num, region.region_id)
                self._record_ocr_failure(f"Region OCR failed for {region.region_id}: {e}")
                continue
            if not ocr_results:
                continue

            # V4.0 Diagram Structure & Mermaid Detection (Pillar 4)
            from src.ocr.infrastructure.layout.diagram_builder import DiagramBuilder
            if region.content_type == ContentType.DIAGRAM or DiagramBuilder.is_diagram_content(ocr_results):
                diagram = DiagramBuilder.build_org_chart(
                    ocr_results,
                    page_num=page_num,
                    diagram_idx=len(self._current_page_diagrams) + 1
                )
                if diagram:
                    self._current_page_diagrams.append(diagram)
                    try:
                        progress(f"[{page_num}] Reconstructed diagram: {diagram.title} ({len(diagram.nodes)} nodes, {len(diagram.edges)} edges)", stage="diagram")
                    except Exception:
                        pass

            for idx, res in enumerate(ocr_results):
                raw_bbox = res.get("bbox", [])
                if len(raw_bbox) < 4:
                    continue

                text = UnicodeNormalizer.normalize(res.get("text", ""))
                conf = res.get("confidence")

                # Check hallucination / low confidence filter (A1)
                is_valid, reject_reason = self.classify_ocr_hallucination(text, conf)
                if not is_valid:
                    mapped_bbox = RegionCropper.map_crop_bbox_to_page(
                        raw_bbox, actual_crop_rect, crop_w, crop_h
                    )
                    _rejected_list = getattr(self, "_rejected_evidence", None)
                    if _rejected_list is None:
                        _rejected_list = self._rejected_evidence = []
                    _rejected_list.append(EvidenceBlock(
                        block_id=f"B_{page_num:04d}_REJ_{len(_rejected_list) + 1:04d}",
                        page=page_num,
                        region_id=region.region_id,
                        bbox=mapped_bbox,
                        bbox_original=mapped_bbox,
                        bbox_normalized=mapped_bbox,
                        text=text,
                        content_type=ContentType.IMAGE,
                        source="ocr",
                        confidence=conf,
                        orientation=region.rotation,
                        quality_score=conf,
                        block_type="noise",
                        is_bold=False,
                        font_size=None,
                        reading_order=0,
                        status=reject_reason,
                        failure_reason=f"Rejected: {reject_reason} (conf={conf})"
                    ))
                    continue

                mapped_bbox = RegionCropper.map_crop_bbox_to_page(
                    raw_bbox, actual_crop_rect, crop_w, crop_h
                )

                # Check if mapped OCR block overlaps with any native text block
                is_duplicate = False
                for nb in native_bboxes:
                    if RegionCropper.compute_intersection_over_min(mapped_bbox, nb) > 0.40:
                        is_duplicate = True
                        break

                if is_duplicate:
                    continue  # Native clean text takes priority

                q_score, _, _ = self.ocr_quality.evaluate_ocr_result(text, conf)
                if res.get("needs_review"):
                    q_score = min(q_score, .74) if q_score is not None else None
                    region.needs_fallback = True
                    region.failure_reason = res.get("review_reason", "OCR backend requested review")

                block = TextBlock(
                    text=text,
                    text_raw=res.get("text_raw", res.get("text", "")),
                    correction_source=(res.get("correction_source") or "unicode_normalizer")
                        if text != res.get("text_raw", res.get("text", "")) else None,
                    source="image_ocr",
                    page=page_num,
                    bbox=mapped_bbox,
                    confidence=conf,
                    quality_score=q_score,
                    confidence_source="recognizer",
                    reviewed=False,
                    line_index=len(native_blocks) + len(image_blocks) + idx,
                    region_id=region.region_id,
                    fallback_reason=res.get("review_reason") if res.get("needs_review") else None,
                )
                image_blocks.append(block)

        return image_blocks
