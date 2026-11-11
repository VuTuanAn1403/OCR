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
        backends.open_backend("paddleocr-vl-1.6", tmp_path)
    with pytest.raises(backends.BackendUnavailable, match="not a VLM candidate"):
        backends.open_backend("doclayout-yolo", tmp_path)
    with pytest.raises(backends.BackendUnavailable, match="hf download 5CD-AI/Vintern-1B-v3_5 --revision b98f263e"):
        backends.open_backend("vintern-1b-v3.5", tmp_path / "missing")


def _pinned(tmp_path, weights_bytes=b"weights", config_bytes=b'{"a": 1}'):
    weights = tmp_path / "weights"
    weights.mkdir(exist_ok=True)
    sha = __import__("hashlib").sha256(weights_bytes).hexdigest()
    pin = {"revision": "abc123", "repository": "org/model", "download_command": "hf download org/model",
           "files": {"model.safetensors": {"size": len(weights_bytes), "git_oid": "x", "sha256": sha},
                     "config.json": {"size": len(config_bytes), "git_oid": backends.git_blob_sha1(config_bytes)},
                     "README.md": {"size": 3, "git_oid": "y"}}}
    pins = tmp_path / "pins"
    pins.mkdir(exist_ok=True)
    (pins / "local-vlm.json").write_text(json.dumps(pin), encoding="utf-8")
    entry = {"id": "local-vlm", "experiment_layer": "VLM", "code_licence": "MIT", "weights_licence": "MIT",
             "licence_label": "VERIFIED", "revision": "abc123", "weights_sha256": sha}
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps({"candidates": [entry]}), encoding="utf-8")
    return weights, pins, catalog_path, entry


def test_local_files_must_match_the_pin_before_any_model_code_runs(tmp_path):
    weights, pins, catalog_path, entry = _pinned(tmp_path)
    calls = []
    factory = lambda directory, pin: calls.append(pin["revision"]) or "backend"  # noqa: E731
    (weights / "model.safetensors").write_bytes(b"weights")
    with pytest.raises(backends.BackendUnavailable, match="missing config.json"):
        backends.open_backend("local-vlm", weights, catalog_path, pins, factory)
    (weights / "config.json").write_bytes(b'{"a": 2}')
    with pytest.raises(backends.BackendUnavailable, match="config.json: hash differs"):
        backends.open_backend("local-vlm", weights, catalog_path, pins, factory)
    (weights / "config.json").write_bytes(b'{"a": 1}')
    assert calls == []  # nothing was built while a file did not match
    assert backends.open_backend("local-vlm", weights, catalog_path, pins, factory) == "backend"  # README is optional
    assert calls == ["abc123"]
    entry["revision"] = "other"
    catalog_path.write_text(json.dumps({"candidates": [entry]}), encoding="utf-8")
    with pytest.raises(backends.BackendUnavailable, match="pin and catalog disagree"):
        backends.open_backend("local-vlm", weights, catalog_path, pins, factory)


def test_tile_grid_follows_the_model_card():
    assert backends.tile_grid(1190, 1684, max_num=6) == (2, 3)  # portrait A4 at 144 DPI
    assert backends.tile_grid(2382, 1684, max_num=6) == (3, 2)  # landscape spread
    assert backends.tile_grid(448, 448, max_num=6) == (1, 1)


def test_pinned_vintern_matches_the_catalog():
    pin = json.loads((backends.PINS / "vintern-1b-v3.5.json").read_text(encoding="utf-8"))
    entry = backends.candidate("vintern-1b-v3.5")
    assert pin["revision"] == entry["revision"] and pin["files"]["model.safetensors"]["sha256"] == entry["weights_sha256"]
    assert pin["custom_code"] == ["configuration_intern_vit.py", "configuration_internvl_chat.py", "conversation.py",
                                  "modeling_intern_vit.py", "modeling_internvl_chat.py"]
