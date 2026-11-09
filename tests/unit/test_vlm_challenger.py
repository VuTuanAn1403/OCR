"""VLM fallback challenger (V8-090): diagnostic-only selection, canonical records, review, catalog gate."""
import json
from pathlib import Path

import pytest

from benchmark.challengers.canonical import validate_predictions
from benchmark.challengers.vlm import adapter, backends, selection


def _page(number, confidence=0.9, lines=10, low=0, corrupted=False):
    suspicious = ["x (reasons: line_orientation_unverified)"] * lines + ["y (reasons: Low engine confidence: 0.5 < 0.80)"] * low
    return {"page_num": number, "quality": {"recognized_lines": lines, "ocr_confidence": confidence, "review_required_count": lines,
                                            "suspicious_lines": suspicious, "unicode_corruption_detected": corrupted}}


def test_only_pages_with_a_diagnostic_are_selected():
    pages = [_page(1), _page(2, confidence=0.6), _page(3, low=2), _page(4, corrupted=True), _page(5), _page(6, lines=0, confidence=0.1)]
    extraction = {5: {"items": [{"kind": "t", "source": "heuristic"}]}, 1: {"items": [{"kind": "t", "source": "docling_tableformer"}]}}
    assert selection.select_pages(pages, extraction) == [
        {"page": 2, "reasons": ["LOW_PAGE_CONFIDENCE"]}, {"page": 3, "reasons": ["LOW_CONFIDENCE_LINES"]},
        {"page": 4, "reasons": ["UNICODE_CORRUPTION"]}, {"page": 5, "reasons": ["HEURISTIC_TABLE"]}]


class _Backend:
    engine, model_version = "fake-vlm", "fake@0"

    def __init__(self, fail_on=()):
        self.fail_on, self.seen = set(fail_on), []

    def transcribe(self, image_png, prompt):
        self.seen.append(image_png)
        if image_png in self.fail_on:
            raise RuntimeError("out of memory")
        return "  Doanh thu | 1.234  \n"


def test_records_keep_the_raw_string_require_review_and_keep_failures_in_the_denominator():
    selected = [{"page": 2, "reasons": ["LOW_PAGE_CONFIDENCE"]}, {"page": 5, "reasons": ["HEURISTIC_TABLE"]}]
    images = {2: b"png-2", 5: b"png-5"}
    backend = _Backend(fail_on={b"png-5"})
    records = adapter.run("DOC", selected, lambda page: (images[page], (595.0, 842.0)), lambda page: f"product {page}",
                          backend, "RUN-1")
    assert backend.seen == [b"png-2", b"png-5"]  # selected pages only
    ok, failed = records
    assert ok["text_raw"] == "  Doanh thu | 1.234  \n"  # unchanged, not stripped or corrected
    assert ok["review_required"] is True and ok["selection_reasons"] == ["LOW_PAGE_CONFIDENCE"]
    assert ok["confidence"] is None and ok["confidence_reason"]
    assert ok["product_text_sha256"] == adapter.sha256(b"product 2")
    assert failed["status"] == "MISSING_OUTPUT" and failed["text_raw"] is None and "out of memory" in failed["error"]
    report = validate_predictions(records, "page_text", {("DOC", 2, "page"), ("DOC", 5, "page")})
    assert report["status"] == "COMPLETE" and report["problems"] == [] and report["missing_output_records"] == 1


def test_backend_refuses_unpinned_candidates_and_never_downloads(tmp_path):
    with pytest.raises(backends.BackendUnavailable, match="revision not pinned"):
        backends.open_backend("vintern-1b-v3.5", tmp_path)
    with pytest.raises(backends.BackendUnavailable, match="not a VLM candidate"):
        backends.open_backend("doclayout-yolo", tmp_path)


def test_pinned_candidate_needs_matching_local_weights(tmp_path):
    weights = tmp_path / "weights"
    weights.mkdir()
    (weights / "model.safetensors").write_bytes(b"weights")
    entry = {"id": "local-vlm", "experiment_layer": "VLM", "code_licence": "MIT", "weights_licence": "MIT",
             "licence_label": "VERIFIED", "revision": "abc123", "weights_sha256": "0" * 64}
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps({"candidates": [entry]}), encoding="utf-8")
    with pytest.raises(backends.BackendUnavailable, match="differs from the catalog"):
        backends.open_backend("local-vlm", weights, catalog_path)
    entry["weights_sha256"] = backends.weights_sha256(weights)
    catalog_path.write_text(json.dumps({"candidates": [entry]}), encoding="utf-8")
    with pytest.raises(backends.BackendUnavailable, match="no inference code"):
        backends.open_backend("local-vlm", weights, catalog_path)
    with pytest.raises(backends.BackendUnavailable, match="never downloaded"):
        backends.open_backend("local-vlm", Path(tmp_path / "missing"), catalog_path)
