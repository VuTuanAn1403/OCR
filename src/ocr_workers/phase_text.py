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
    from ocr_runtime.pipeline_policy import validate_phase_request
    validate_phase_request(request)
    from ocr_pdf_io.document_view import processing_pdf
    from ocr_workers.text_page import TextPageExtractor
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
        pages = list(range(1, len(doc)+1))
        processor = TextPageExtractor(doc, config, request["identity"]["pdf"][:16])
        placement = TorchPlacementAudit(request["device"])
        placement.attach(processor.ocr_engine._recognizer.model, "vietocr")
        init_seconds = time.perf_counter() - started
        files = []
        try:
            for page_num in sorted(set(pages)):
                detector = processor.ocr_engine._detector
                before_detection = getattr(detector, "inference_calls", 0)
                before_recognition = sum(placement.counts.values())
                page = processor.execute(page_num=page_num, total_pages=len(doc), router=router, resume=False)
                detection_calls = detector.inference_calls-before_detection
                recognition_calls = sum(placement.counts.values())-before_recognition
                primary = processor.primary_ocr_detector
                if primary is None:
                    raise RuntimeError("Missing primary full-page detector telemetry")
                if detection_calls < 1 or primary["detection_count"] and recognition_calls < 1:
                    raise RuntimeError("Missing actual GPU OCR inference for document page")
                if any(b.source == "native" for b in page.blocks):
                    raise RuntimeError("Native text leaked into GPU-only page output")
                page.metadata["gpu_ocr"] = {"scope":"all_pages", "source_policy":"gpu_ocr_only_v1",
                    "detector_device":request["device"], "recognizer_device":request["device"],
                    "detector_calls":detection_calls,"recognizer_forward_calls":recognition_calls,
                    "detector_scope":"full_page","detector_input_shape":primary["input_shape"],
                    "render_dpi":config["render_dpi"],"workload":"document",
                    "status":"OCR_PROCESSED" if primary["detection_count"] else "BLANK_NO_DETECTIONS"}
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
                # Blank inputs need no fictitious recognizer inference.
                recognition_workload = "document_no_recognition_regions"
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
