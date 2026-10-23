"""Page engine assembly, shared by the V6.3 text phase and the legacy page use
case (moved verbatim from ProcessPageUseCase.__init__, P09b).

This is the composition root of the page engines: it is the only place that
chooses concrete classes (VietOCR or RapidOCR, the ONNX detector, the DLA
engine, the Docling client). Steps receive the engines it builds.
"""
from types import SimpleNamespace
from typing import Any, Dict, Optional

import cv2

from ocr_layout.dla_engine import DLAEngine
from ocr_layout.page_content_analyzer import PageContentAnalyzer
from ocr_pdf_io.native_text_extractor import NativeTextExtractor
from ocr_pdf_io.pdf_inspector import PDFInspector
from ocr_pdf_io.pdf_renderer import PDFRenderer
from ocr_pdf_io.scan_image import validate_settings as validate_scan_image_settings
from ocr_recognition.fallback_engine import FallbackEngine
from ocr_recognition.ocr_quality import OCRQualityEvaluator
from ocr_recognition.rapidocr_engine import RapidOCREngine
from ocr_recognition.vietnamese_seq2seq_engine import VietnameseSeq2SeqEngine
from ocr_recognition.diacritic_retry import diacritic_retry_settings
from ocr_document.reading_order import READING_ORDER_METHODS
from ocr_runtime.config import ConfigError
from ocr_structure.docling_client import DoclingStructureExtractor
from ocr_structure.document_layout_engine import DocumentLayoutEngine


def validate_page_config(config: Dict[str, Any]) -> bool:
    """Reject page settings that would otherwise be silently misread; returns native_first."""
    try:
        diacritic_retry_settings(config)
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc
    native_first = config.get("native_first", True)
    if not isinstance(native_first, bool):
        # A YAML string such as "false" would otherwise be truthy.
        raise ConfigError(f"native_first must be true or false, got {native_first!r}")
    if not isinstance(config.get("retain_table_ocr_lines", False), bool):
        raise ConfigError("retain_table_ocr_lines must be true or false")
    if "native_review_threshold" in config:
        # Never read; keeping it would suggest a second native gate.
        raise ConfigError("native_review_threshold is not supported; set native_quality.review_threshold")
    reading_order = config.get("reading_order", {})
    if not isinstance(reading_order, dict) or set(reading_order) - {"method", "min_gap"} \
            or reading_order.get("method", "heuristic") not in READING_ORDER_METHODS:
        raise ConfigError(f"reading_order accepts method ({', '.join(READING_ORDER_METHODS)}) and min_gap")
    if "scan_image" in config:
        try:
            validate_scan_image_settings(config["scan_image"])
        except ValueError as exc:
            raise ConfigError(str(exc)) from exc
    agreement = config.get("ocr_layer_agreement", {})
    if not isinstance(agreement, dict) or set(agreement) - {"sample_lines"} \
            or type(agreement.get("sample_lines", 5)) is not int or not 3 <= agreement.get("sample_lines", 5) <= 5:
        raise ConfigError("ocr_layer_agreement accepts sample_lines 3-5 (proposal C2.1)")
    return native_first


def build_page_engines(doc, config: Dict[str, Any], *, legacy_furniture: bool,
                       structure_extractor: Optional[DoclingStructureExtractor] = None) -> SimpleNamespace:
    engines = SimpleNamespace()
    engines.inspector = PDFInspector(doc)
    engines.renderer = PDFRenderer(doc)
    engines.native_extractor = NativeTextExtractor(doc)
    primary_engine = config.get("primary_engine", "vietocr")
    threads = config.get("num_threads")
    if threads is not None:
        import torch
        torch.set_num_threads(threads)
        cv2.setNumThreads(threads)
    if primary_engine == "rapidocr":
        engines.ocr_engine = RapidOCREngine(num_threads=threads) if threads else RapidOCREngine()
    elif primary_engine == "vietocr":
        detector_args = {}
        if config.get("text_detector"):
            from ocr_recognition.text_detector import ONNXTextDetector
            detector_args["detector"] = ONNXTextDetector(config["text_detector"], config.get("device", "cpu"),
                                                       num_threads=threads or 2)
        engines.ocr_engine = VietnameseSeq2SeqEngine(
            batch_size=config.get("batch_size", 16), device=config.get("device"),
            **detector_args,
            **({"num_threads": threads} if threads is not None else {}))
    else:
        raise ValueError(f"Unsupported primary_engine: {primary_engine}")
    engines.ocr_quality = OCRQualityEvaluator(min_confidence=config.get("min_confidence", 0.80))
    engines.layout_engine = DocumentLayoutEngine()
    engines.owns_structure_extractor = structure_extractor is None
    engines.structure_extractor = structure_extractor or DoclingStructureExtractor(config.get("docling", {}))
    layout_config = config.get("layout_model", {})
    engines.content_analyzer = PageContentAnalyzer(DLAEngine(
        model_path=layout_config.get("model_path"),
        model_config=layout_config,
        device=config.get("device", "cpu"),
        num_threads=layout_config.get("num_threads", config.get("num_threads", 4)),
        legacy_furniture=legacy_furniture,
    ))
    engines.fallback_engine = FallbackEngine(
        upscale_dpi=config.get("fallback_upscale_dpi", 250),
        ocr_engine=engines.ocr_engine,
    )
    return engines
