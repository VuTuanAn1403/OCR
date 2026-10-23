"""ocr_pdf_io: rendering size, invertible coordinate chains, crops and the
shared geometry helper. No OCR model is imported (P05b)."""
import json
import math
import os
from pathlib import Path
import subprocess
import sys

import pymupdf
import pytest

from ocr_contracts.geometry import block_is_covered
from ocr_pdf_io.coordinate_transform import CoordinateChain
from ocr_pdf_io.pdf_inspector import PDFInspector
from ocr_pdf_io.pdf_renderer import PDFRenderer
from ocr_pdf_io.region_cropper import RegionCropper

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def document():
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Báo cáo thường niên 2020", fontsize=12)
    yield doc
    doc.close()


@pytest.mark.parametrize("dpi", [72, 150, 180])
def test_render_size_follows_dpi(document, dpi):
    image = PDFRenderer(document).render_page(1, dpi=dpi)
    assert image.shape[1] == math.ceil(595 * dpi / 72) or abs(image.shape[1] - 595 * dpi / 72) <= 1
    assert abs(image.shape[0] - 842 * dpi / 72) <= 1 and image.shape[2] == 3


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_rotated_chain_round_trips(rotation):
    angle = math.radians(rotation)
    rotate = [[math.cos(angle), -math.sin(angle), 0], [math.sin(angle), math.cos(angle), 0], [0, 0, 1]]
    chain = CoordinateChain("pdf_points").then("scale", "pixels", [[2.5, 0, 0], [0, 2.5, 0], [0, 0, 1]]) \
        .then("rotate", "rotated_pixels", rotate)
    box = [10.0, 20.0, 110.0, 70.0]
    back = chain.inverse().bbox(chain.bbox(box))
    assert back == pytest.approx(box, abs=1e-6)


def test_invalid_coordinates_are_rejected():
    with pytest.raises(ValueError):
        CoordinateChain("a").then("singular", "b", [[0, 0, 0], [0, 0, 0], [0, 0, 1]])
    with pytest.raises(ValueError):
        CoordinateChain("a").bbox([5, 5, 1, 1])


def test_inspector_reports_page_geometry(document):
    info = PDFInspector(document).inspect_page(1)
    assert info["width"] == pytest.approx(595) and info["height"] == pytest.approx(842)


def test_iou_and_coverage_geometry():
    assert RegionCropper.compute_iou([0, 0, 10, 10], [0, 0, 10, 10]) == pytest.approx(1)
    assert RegionCropper.compute_iou([0, 0, 10, 10], [20, 20, 30, 30]) == 0
    table = type("T", (), {"bbox": [0, 0, 100, 100]})()
    assert block_is_covered([10, 10, 20, 20], [table]) and not block_is_covered([90, 90, 200, 200], [table])
    assert not block_is_covered([1, 2, 3], [table]) and not block_is_covered([5, 5, 5, 9], [table])


def test_import_loads_no_ocr_model_library():
    code = ("import json, sys\nimport ocr_pdf_io.coordinate_transform, ocr_pdf_io.native_text_extractor, "
            "ocr_pdf_io.pdf_inspector, ocr_pdf_io.pdf_renderer, ocr_pdf_io.region_cropper, ocr_pdf_io.scan_image\n"
            "print(json.dumps(sorted(m for m in ('torch','onnxruntime','vietocr','docling','transformers','openpyxl',"
            "'src.ocr') if m in sys.modules)))")
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT / "src", capture_output=True, text=True,
                            env={**os.environ, "PYTHONPATH": str(ROOT / "src")}, timeout=120)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == []
