"""Scan image acquisition: source DPI, embedded image, DPI clamp (proposal V6
C2.2(2)(3), review item R-08). Both options are off by default."""
import copy
import json

import numpy as np
import pymupdf
import pytest
import yaml

from src.ocr.application.convert_document import ConvertDocumentUseCase
from src.ocr.infrastructure.pdf.pdf_renderer import PDFRenderer
from src.ocr.infrastructure.pdf.scan_image import (
    acquire_page_image, full_page_image_info, processing_dpi, validate_settings)
from src.ocr.runtime.config import ConfigError, load_profiles

LINES = ["Doanh thu thuan nam 2025", "Loi nhuan sau thue tang manh", "Tong tai san cuoi nam"]


def _scan(path, dpi=100, rotate=0, drawing=False):
    with pymupdf.open() as source:
        page = source.new_page(width=595, height=842)
        for i, text in enumerate(LINES):
            page.insert_text((72, 100 + 40 * i), text, fontsize=16)
        pixmap = page.get_pixmap(dpi=dpi)
    with pymupdf.open() as scan:
        page = scan.new_page(width=595, height=842)
        page.insert_image(page.rect, pixmap=pixmap)
        if drawing:
            page.draw_line((50, 300), (500, 300))
        if rotate:
            page.set_rotation(rotate)
        scan.save(path)
    return path


def test_source_dpi_is_measured_from_the_placed_image(tmp_path):
    with pymupdf.open(_scan(tmp_path / "s.pdf", dpi=100)) as doc:
        info = full_page_image_info(doc[0])
        assert info["upright"] and info["covers_page"] and info["images_on_page"] == 1
        assert info["source_dpi"] == pytest.approx(100, abs=1)
    with pymupdf.open() as doc:
        assert full_page_image_info(doc.new_page()) is None


@pytest.mark.parametrize("source, k, expected", [(96, 2.0, 192), (59, 2.0, 150), (200, 2.0, 300)])
def test_processing_dpi_is_clamped(source, k, expected):
    assert processing_dpi(source, k) == expected


def test_embedded_image_spans_the_page_like_the_render(tmp_path):
    with pymupdf.open(_scan(tmp_path / "s.pdf", dpi=100)) as doc:
        renderer = PDFRenderer(doc)
        image, record = acquire_page_image(doc, 1, renderer, 180, {"source": "embedded"})
        rendered = renderer.render_page(1, dpi=180)
    assert record["source"] == "embedded" and record["processing_dpi"] == 180
    assert image.shape == rendered.shape
    assert np.abs(image.astype(int) - rendered.astype(int)).mean() < 8  # same content, other resampling
    assert record["coordinate_chain"]["target"] == "render_pixels"


@pytest.mark.parametrize("kwargs, reason", [({"drawing": True}, "vector drawings"), ({"rotate": 90}, "rotation")])
def test_embedded_falls_back_to_render_with_a_reason(tmp_path, kwargs, reason):
    with pymupdf.open(_scan(tmp_path / "s.pdf", **kwargs)) as doc:
        _, record = acquire_page_image(doc, 1, PDFRenderer(doc), 180, {"source": "embedded"})
    assert record["source"] == "render" and reason in record["embedded_fallback_reason"]


def test_source_clamp_needs_k_and_falls_back_without_an_image(tmp_path):
    with pymupdf.open(_scan(tmp_path / "s.pdf", dpi=100)) as doc:
        _, record = acquire_page_image(doc, 1, PDFRenderer(doc), 180, {"dpi_policy": "source_clamp", "k": 2.0})
        assert record["processing_dpi"] == 200 and record["source"] == "render"
    with pymupdf.open() as doc:
        doc.new_page().insert_text((72, 72), "native")
        _, record = acquire_page_image(doc, 1, PDFRenderer(doc), 180, {"dpi_policy": "source_clamp", "k": 2.0})
    assert record["processing_dpi"] == 180 and "no full-page image" in record["dpi_fallback_reason"]


@pytest.mark.parametrize("settings", [{"dpi_policy": "source_clamp"}, {"source": "tiff"}, {"min_dpi": 400},
                                      {"dpi_policy": "source_clamp", "k": True}, {"scale": 2}])
def test_malformed_settings_are_rejected(settings):
    with pytest.raises(ValueError):
        validate_settings(settings)


def _config_with(tmp_path, **extra):
    _, profiles = load_profiles()
    fast = copy.deepcopy(profiles["fast"])
    fast.update(extra)
    path = tmp_path / "profiles.yaml"
    path.write_text(yaml.safe_dump({"profiles": {"fast": fast}}, allow_unicode=True), encoding="utf-8")
    return path


def _run(tmp_path, name, pdf, **extra):
    converter = ConvertDocumentUseCase(str(_config_with(tmp_path / name, **extra)) if extra else None)
    converter.execute(str(pdf), "fast", output_dir=str(tmp_path / name / "out"),
                      cache_dir=str(tmp_path / name / "cache"), assets_mode="none")
    return json.loads((tmp_path / name / "out/SCAN_page/pages/page-0001.json").read_text(encoding="utf-8"))


def test_embedded_ocr_returns_the_same_text_in_the_same_pdf_coordinates(tmp_path):
    (tmp_path / "default").mkdir()
    (tmp_path / "embedded").mkdir()
    pdf = _scan(tmp_path / "SCAN_page.pdf", dpi=150)
    default = _run(tmp_path, "default", pdf)
    embedded = _run(tmp_path, "embedded", pdf, scan_image={"source": "embedded"})
    assert "scan_image" not in default["metadata"]  # off by default
    assert default["metadata"]["full_page_image"]["source_dpi"] == pytest.approx(150, abs=1)
    assert embedded["metadata"]["scan_image"]["source"] == "embedded"
    def lines(page):  # resampling may move a space ("nam2025"); compare text without spaces
        return [("".join(b["text"].split()), b["bbox"]) for b in sorted(page["blocks"], key=lambda b: b["bbox"][1])]
    assert [text for text, _ in lines(default)] == [text for text, _ in lines(embedded)] == \
        ["".join(line.split()) for line in LINES]
    for (_, a), (_, b) in zip(lines(default), lines(embedded)):
        assert np.allclose(a, b, atol=3.0)


def test_profile_validation_reports_scan_image_errors(tmp_path):
    (tmp_path / "bad").mkdir()
    pdf = _scan(tmp_path / "SCAN_page.pdf")
    with pytest.raises(ConfigError, match="scan_image"):
        _run(tmp_path, "bad", pdf, scan_image={"dpi_policy": "source_clamp"})


@pytest.mark.parametrize("render_mode, expected", [(0, "render"), (3, "embedded")])
def test_embedded_shortcut_preserves_visible_text_overlays(tmp_path, render_mode, expected):
    with pymupdf.open(_scan(tmp_path / "overlay.pdf")) as doc:
        doc[0].insert_text((60, 400), "Visible correction: revenue 2025", render_mode=render_mode)
        _, record = acquire_page_image(doc, 1, PDFRenderer(doc), 150, {"source": "embedded"})
    assert record["source"] == expected
    if render_mode == 0:
        assert "visible text" in record["embedded_fallback_reason"]


@pytest.mark.parametrize("k", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_dpi_scale_is_rejected_at_the_acquisition_boundary(k):
    with pytest.raises(ValueError, match="experimentally chosen"):
        acquire_page_image(None, 1, None, 150, {"dpi_policy": "source_clamp", "k": k})


def test_decode_failure_renders_the_page_and_preserves_the_reason(tmp_path, monkeypatch):
    from src.ocr.infrastructure.pdf import scan_image
    def failed_decode(*_):
        raise ValueError("unsupported embedded codec")
    monkeypatch.setattr(scan_image, "_decode", failed_decode)
    with pymupdf.open(_scan(tmp_path / "codec.pdf")) as doc:
        image, record = acquire_page_image(doc, 1, PDFRenderer(doc), 150, {"source": "embedded"})
    assert image.size and record["source"] == "render"
    assert "unsupported embedded codec" in record["embedded_fallback_reason"]
