"""Phase A (text): full-page GPU OCR of every selected page, Docling deferred.
Moved verbatim from ocr_workers.phases (P11b); its code identity is the stage
closure of this module (ocr_runtime.fingerprint.stage_fingerprint("text")).
"""
from __future__ import annotations

import copy
import time

from ocr_artifacts.atomic_io import atomic_write_json
from ocr_workers.stage_io import stage_dir, write_receipt


def run_text(request):
    from ocr_pdf_io.document_view import processing_pdf
    import numpy as np
    from ocr_recognition.route_page import RoutePageUseCase
    from ocr_recognition.routing_policy import RoutingPolicy
    from ocr_runtime.torch_placement import TorchPlacementAudit
    root = stage_dir(request, "text")
    config = copy.deepcopy(request["config"])
    config["docling"]["enabled"] = False  # a deferred stage, recorded as such
    router = RoutePageUseCase(RoutingPolicy(**{
        "reliable_threshold": config["native_quality"]["reliable_threshold"],
        "review_threshold": config["native_quality"]["review_threshold"]}))
    started = time.perf_counter()
    with processing_pdf(request["pdf"], config.get("pdf_render_policy", "original_v1"),
                        expected_sha256=request["identity"]["pdf"]) as (doc, render_view):
        pages = request.get("pages") or list(range(1, len(doc)+1))
        if any(type(p) is not int or p < 1 or p > len(doc) for p in pages):
            raise ValueError("Page selection is outside the PDF")
        if config.get("ocr_source_policy") == "gpu_ocr_only_v1":
            # V6.3 phase A orchestrator (P09b).
            from ocr_workers.text_page import TextPageExtractor as page_extractor
        else:
            # V6.2 legacy profiles (native-first, two-up, region fallback) keep
            # the frozen legacy page use case.
            from src.ocr.application.process_page import ProcessPageUseCase as page_extractor
        processor = page_extractor(doc, config, request["identity"]["pdf"][:16])
        placement = TorchPlacementAudit(request["device"])
        placement.attach(processor.ocr_engine._recognizer.model, "vietocr")
        init_seconds = time.perf_counter() - started
        files = []
        try:
            for page_num in sorted(set(pages)):
                strict_ocr = config.get("ocr_source_policy") == "gpu_ocr_only_v1"
                detector = processor.ocr_engine._detector
                before_detection = getattr(detector, "inference_calls", 0)
                before_recognition = sum(placement.counts.values())
                page = processor.execute(page_num=page_num, total_pages=len(doc), router=router, resume=False)
                # Real full-page detector probe on native pages as well. It is
                # independent evidence, never a model-layout ROI gate.
                if not strict_ocr:
                    detector.detect(processor.renderer.render_page(page_num, dpi=config["render_dpi"]))
                else:
                    detection_calls = detector.inference_calls-before_detection
                    recognition_calls = sum(placement.counts.values())-before_recognition
                    if detection_calls < 1 or detector.last_detections and recognition_calls < 1:
                        raise RuntimeError("Missing actual GPU OCR inference for document page")
                    if any(b.source == "native" for b in page.blocks):
                        raise RuntimeError("Native text leaked into GPU-only page output")
                    page.metadata["gpu_ocr"] = {"scope":"all_pages", "source_policy":"gpu_ocr_only_v1",
                        "detector_device":request["device"], "recognizer_device":request["device"],
                        "detector_calls":detection_calls,"recognizer_forward_calls":recognition_calls,
                        "detector_scope":"full_page","detector_input_shape":detector.last_input_shape,
                        "render_dpi":config["render_dpi"],"workload":"document",
                        "status":"OCR_PROCESSED" if detector.last_detections else "BLANK_NO_DETECTIONS"}
                if page.quality.errors:
                    raise RuntimeError(f"Phase A page {page_num} has extraction errors; inspect the phase log")
                page.metadata["runtime_phase"] = {"method": "document-two-phase-v1", "phase": "A",
                                                   "generation": request["generation"], "docling_deferred": True}
                if render_view["policy"] != "original_v1":
                    page.metadata["pdf_render_view"] = render_view
                path = root / "text" / f"page-{page_num:04d}.json"
                atomic_write_json(path, page.model_dump(mode="json"))
                files.append(path)
            observed = placement.report()
            recognition_workload = "document"
            if observed["status"] != "VERIFIED_INFERENCE":
                if config.get("ocr_source_policy") == "gpu_ocr_only_v1":
                    # Truly blank inputs need no fictitious recognition call.
                    observed["workload"] = "document_no_recognition_regions"
                    recognition_workload = "document_no_recognition_regions"
                else:
                # A native-only input must still prove this backend can run.
                    from PIL import Image, ImageDraw
                    image = Image.new("RGB", (256, 40), "white")
                    ImageDraw.Draw(image).text((5, 5), "GPU OCR 123", fill="black")
                    processor.ocr_engine._recognizer.predict_batch([image], return_prob=True)
                    observed = placement.report(require_inference=True)
                    recognition_workload = "synthetic_backend_probe_native_only_document"
            observed["workload"] = recognition_workload
            layout = processor.content_analyzer.dla_engine._torch_layout.placement
            if not layout:
                raise RuntimeError("Layout model inference was never exercised")
            write_receipt(request, "text", files, total_pages=len(doc), selected_pages=sorted(set(pages)),
                    init_seconds=init_seconds, seconds=time.perf_counter()-started,
                    placement={"detector": detector.placement, "recognizer": observed, "layout": layout},
                    pdf_render_view=render_view)
        finally:
            processor.close()
