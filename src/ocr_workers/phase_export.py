"""Export: one document from the phase B pages, run with CUDA hidden.
Moved verbatim from ocr_workers.phases (P11b); stage closure "export".
"""
from __future__ import annotations

from pathlib import Path

from ocr_artifacts.atomic_io import atomic_write_json
from ocr_workers.stage_io import read, receipt_path, stage_dir, write_receipt


def run_export(request):
    from ocr_contracts.document import ExtractedDocument
    from ocr_contracts.page import ExtractedPage
    from ocr_contracts.quality import DocumentQualityReport
    from ocr_document.export import DocumentExporter
    from ocr_document.manifest_exporter import ManifestExporter
    a, b = read(receipt_path(request, "text")), read(receipt_path(request, "structure"))
    structure_root = stage_dir(request, "structure")
    pages = [ExtractedPage.model_validate(read(structure_root / name)) for name in sorted(b["files"])]
    # A reused stage ran in an earlier process: its time is not this run's (P11b).
    stages = request.get("stages") or {}
    fresh = {phase: not stages.get(phase, {}).get("reused") for phase in ("text", "structure")}
    def mean(values):
        values = [v for v in values if v is not None]
        return sum(values)/len(values) if values else None
    counts = {"native": 0, "mixed": 0, "ocr": 0}
    for p in pages:
        kind = p.page_type.value
        counts["ocr" if request["config"].get("ocr_source_policy") == "gpu_ocr_only_v1" else
               "native" if kind in ("NATIVE_TEXT", "PRODUCT_SHOWCASE_COLLAGE") else "mixed" if kind == "MIXED" else "ocr"] += 1
    quality = DocumentQualityReport(document_id=Path(request["pdf"]).stem, total_pages=a["total_pages"],
        mean_native_score=mean([p.quality.native_text_score for p in pages]) or 0,
        mean_ocr_confidence=mean([p.quality.ocr_confidence for p in pages]),
        mean_quality_score=mean([p.quality.quality_score for p in pages]),
        ocr_confidence_scored_pages=sum(p.quality.ocr_confidence is not None for p in pages),
        quality_scored_pages=sum(p.quality.quality_score is not None for p in pages),
        pages_processed_native=counts["native"], pages_processed_mixed=counts["mixed"], pages_processed_ocr=counts["ocr"],
        total_fallback_regions=sum(p.quality.fallback_count for p in pages),
        total_time_seconds=(a["seconds"] if fresh["text"] else 0.0)+(b["seconds"] if fresh["structure"] else 0.0),
        startup_seconds=a["init_seconds"] if fresh["text"] else 0.0,
        page_reports=[p.quality for p in pages])
    document = ExtractedDocument(document_id=quality.document_id, file_path=request["pdf"],
        file_hash=request["identity"]["pdf"][:16], total_pages=a["total_pages"], selected_pages=a["selected_pages"],
        profile=request["config"]["profile"], pages=pages, quality=quality)
    document.manifest = ManifestExporter.generate_manifest(document, request["config"],
        config_path=Path(request["config_path"]), cache_key=request["generation"])
    document.manifest["gpu_runtime"] = {"method": "document-two-phase-v1", "generation": request["generation"],
        "model_locks": request["model_hashes"], "dependency_locks": request["lock_hashes"],
        "phase_a_placement": a["placement"], "phase_b_placement": b["placement"],
        "quality_acceptance": "NOT_EVALUATED"}
    if stages:
        document.manifest["gpu_runtime"]["stages"] = {
            phase: {key: stages[phase][key] for key in ("key", "reused", "receipt_sha256", "produced_by_generation",
                                                         "historical_seconds") if key in stages[phase]}
            for phase in ("text", "structure", "export")}
    if request.get("finalize_document", True):
        # V6.2 legacy finalize path (cli/gpu_runner.py) counts keywords in this
        # phase. V6.3 never takes it: keywords are counted by the document owner.
        from src.ocr.application.export_document import ExportDocumentUseCase as exporter
        options = {"keywords_file": request.get("keywords_file")}
    else:
        exporter, options = DocumentExporter, {}
    output = exporter.execute(document, Path(request["output"]), assets_mode=request.get("assets", "png"),
                              output_mode=request.get("output_mode", "compact"), **options)
    validation = read(output / "validation.json")
    if validation["status"] == "FAIL":
        raise RuntimeError(f"Export validation failed: {validation['errors'][:5]}")
    path = stage_dir(request, "export") / "export.json"
    atomic_write_json(path, {"output": str(output), "validation": validation["status"]})
    write_receipt(request, "export", [path])
