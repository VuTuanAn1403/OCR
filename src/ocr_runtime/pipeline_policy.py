"""Invariants of the one supported pipeline; no model imports."""
from ocr_runtime.config import ConfigError, document_layout_settings, furniture_settings

PIPELINE = "v6.3"
PROFILE = "unified_gpu_full_ocr"
BACKEND = "gpu_two_phase"
SOURCE_POLICY = "gpu_ocr_only_v1"
BRIDGE_POLICY = "raster-plus-gpu-text-v1"
TEXT_REQUIRED = {
    "ocr_source_policy": SOURCE_POLICY,
    "native_first": False,
    "two_up_detection_enabled": False,
    "multi_region_detection_enabled": False,
    "orientation_fallback_enabled": False,
    "fallback_enabled": False,
}


def validate_profile(config, *, phase=None):
    if not isinstance(config, dict):
        raise ConfigError("Unified profile must be a mapping")
    required = {**TEXT_REQUIRED, "device": "cuda", "ocr_scope": "all_pages",
                "bridge_policy": BRIDGE_POLICY, "primary_engine": "vietocr"}
    wrong = {key: config.get(key) for key, value in required.items()
             if config.get(key) != value or isinstance(value, bool) and type(config.get(key)) is not bool}
    if wrong or config.get("fallback_only_on_review"):
        raise ConfigError(f"Unified pipeline requires CUDA, native_first=false, all_pages and {SOURCE_POLICY}; "
                          f"unsupported settings: {wrong}")
    runtime = config.get("runtime", {})
    if not isinstance(runtime, dict) or runtime.get("scheduler") != "document_two_phase_v1":
        raise ConfigError("Unified pipeline requires document_two_phase_v1")
    layout = document_layout_settings(config)
    if layout["method"] != "region_tree_graph_v1" or furniture_settings(layout)["method"] != "document_context_v3":
        raise ConfigError("Unified pipeline requires region_tree_graph_v1 and document_context_v3")
    docling = config.get("docling", {})
    if not isinstance(docling, dict):
        raise ConfigError("Unified Docling settings must be a mapping")
    required_docling = {"enabled": phase != "text", "ocr": False, "strict_gpu": True,
                       "verify_placement": True, "tables": True, "formulas": True, "page_selection": "all"}
    if any(docling.get(k) != v or isinstance(v, bool) and type(docling.get(k)) is not bool
           for k, v in required_docling.items()):
        raise ConfigError("Unified pipeline requires verified Docling GPU on all pages, tables/formulas enabled "
                          "and Docling OCR disabled; only the text phase defers Docling")
    return config


def validate_phase_request(request):
    """Reject retired routes before importing any model implementation."""
    if request.get("device") != "cuda":
        raise ConfigError("Unified extraction workers require CUDA; CPU is used for coordination and analysis")
    if request.get("finalize_document", False):
        raise ConfigError("Phase keyword finalization was retired; the document owner finalizes keywords")
    if request.get("pages") is not None:
        raise ConfigError("Unified extraction processes every page; partial page requests are not supported")
    validate_profile(request["config"])
