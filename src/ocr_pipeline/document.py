"""V6.3 document finalizer, invoked inside a lifetime-bounded CPU worker.

Extraction acceptance (GPU source evidence, OCR receipt) lives here; keyword
finalization lives in keyword_finalization.py (analysis closure).
"""
import json
from pathlib import Path

from ocr_contracts.processing import KEYWORD_ARTIFACTS, IdentityMismatch
from ocr_artifacts.digest import sha256_json_compact as digest
# Re-exported: the keyword step lives in the analysis closure (P11a).
from ocr_pipeline.keyword_finalization import finalize_keywords
from ocr_artifacts.atomic_io import atomic_write_json
from ocr_pipeline.scheduler import sha256


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def ocr_files(output):
    excluded = {*KEYWORD_ARTIFACTS, "COMPLETED.json", "ocr_receipt.json"}
    return {p.relative_to(output).as_posix():sha256(p) for p in sorted(output.rglob('*'))
            if p.is_file() and p.name not in excluded and p.name != "manifest.json" and not p.name.endswith(".tmp")}


def manifest_ocr_hash(output):
    manifest = read(output/"manifest.json")
    manifest.pop("keyword_contract", None)
    return digest(manifest)


def valid_ocr(output, identity):
    try:
        receipt = read(output/"ocr_receipt.json")
        return (receipt["ocr_identity"] == identity and receipt["manifest_ocr_sha256"] == manifest_ocr_hash(output)
                and receipt["files"] == ocr_files(output))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def validate_gpu_source(output):
    manifest = read(output/"manifest.json")
    pages = manifest["selected_pages"]
    if pages != list(range(1, manifest["total_pages"]+1)):
        raise ValueError("PARTIAL_DOCUMENT cannot enter a full-document matrix")
    placement = manifest["gpu_runtime"]["phase_a_placement"]
    if (placement["detector"].get("expected_provider") != "CUDAExecutionProvider"
            or placement["recognizer"].get("device") != "cuda"
            or placement["recognizer"].get("workload", "").startswith("synthetic")):
        raise ValueError("Missing real document GPU placement evidence")
    for n in pages:
        page = read(output/"pages"/f"page-{n:04d}.json")
        audit = page["metadata"].get("gpu_ocr", {})
        if (audit.get("scope") != "all_pages" or audit.get("source_policy") != "gpu_ocr_only_v1"
                or audit.get("detector_device") != "cuda" or audit.get("recognizer_device") != "cuda"
                or audit.get("detector_calls", 0) < 1 or audit.get("workload") != "document"
                or audit.get("status") not in ("OCR_PROCESSED", "BLANK_NO_DETECTIONS")
                or audit.get("status") == "OCR_PROCESSED" and audit.get("recognizer_forward_calls", 0) < 1):
            raise ValueError(f"Page {n} lacks actual full-page GPU OCR evidence")
        if page["metadata"].get("ocr_structure_bridge", {}).get("policy") != "raster-plus-gpu-text-v1":
            raise ValueError(f"Page {n} lacks a source-safe Docling bridge")
        if any(b.get("source") == "native" for b in page["blocks"]):
            raise ValueError(f"Native text in counted output, page {n}")
        if any(b.get("source") == "native" for b in page["metadata"].get("text_evidence", {}).get("items", [])):
            raise ValueError(f"Native evidence in GPU-only page {n}")
        if any(s.get("provenance", {}).get("text_source_policy") != "gpu_ocr_only_v1" for s in [*page.get("tables",[]), *page.get("formulas",[])]):
            raise ValueError(f"Unverified structure text source, page {n}")


def process_document(request, snapshot, *, resume=False, backend=None):
    from ocr_pipeline.scheduler import run_document
    from ocr_pipeline.artifact_validation import validate_document_artifacts
    output = Path(request["output"])/Path(request["pdf"]).stem
    identity = request["ocr_identity"]
    if not resume or not valid_ocr(output,identity):
        # Invalidate the old acceptance before a forced/new extraction. If
        # inference fails, a later retry must not certify the previous output
        # through its still-valid document receipt.
        from ocr_pipeline.completion import clear_completed
        clear_completed(output)
        (output/"ocr_receipt.json").unlink(missing_ok=True)
        (backend or run_document)({**request,"finalize_document":False}, resume=resume)
        validate_gpu_source(output)
        validation = validate_document_artifacts(output, include_keywords=False)
        if validation["status"] == "FAIL":
            raise ValueError(f"OCR artifact validation failed: {validation['errors'][:3]}")
        atomic_write_json(output/"ocr_receipt.json", {"ocr_identity":identity,"manifest_ocr_sha256":manifest_ocr_hash(output),
                                                     "files":ocr_files(output)})
    validate_gpu_source(output)
    result = finalize_keywords(output,snapshot,request["pdf_sha256"])
    if not valid_ocr(output,identity):
        raise IdentityMismatch("OCR changed during keyword finalization")
    return result
