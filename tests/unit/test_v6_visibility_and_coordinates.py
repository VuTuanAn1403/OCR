import numpy as np
import pymupdf
import pytest

from src.ocr.domain.routing.routing_policy import RoutingPolicy
from src.ocr.domain.routing.page_type import PageType
from src.ocr.infrastructure.pdf.pdf_inspector import PDFInspector
from src.ocr.infrastructure.pdf.coordinate_transform import CoordinateChain


def test_invisible_text_on_full_page_image_is_not_clean_native_text():
    with pymupdf.open() as image_doc:
        p = image_doc.new_page(width=200, height=300)
        p.insert_text((20, 50), "Visible source image report")
        png = p.get_pixmap().tobytes("png")
    with pymupdf.open() as doc:
        p = doc.new_page(width=200, height=300)
        p.insert_image(p.rect, stream=png)
        p.insert_text((20, 60), "Wrong stale OCR layer but syntactically clean text", render_mode=3)
        meta = PDFInspector(doc).inspect_page(1)
        assert meta["hidden_char_count"] > 30 and meta["visible_char_count"] == 0
        assert meta["has_hidden_ocr_layer"]
        policy = RoutingPolicy()
        assert policy.determine_page_type(meta, .99) == PageType.SCANNED_WITH_OCR_LAYER
        assert policy.should_ocr(PageType.SCANNED_WITH_OCR_LAYER)


def test_visible_text_with_background_image_remains_distinct_from_hidden_ocr():
    with pymupdf.open() as doc:
        p = doc.new_page(width=200, height=300)
        p.insert_text((20, 60), "Real visible native text over background")
        meta = PDFInspector(doc).inspect_page(1)
        assert not meta["has_hidden_ocr_layer"] and meta["visible_char_count"] > 0
        assert RoutingPolicy().determine_page_type(meta, .99) == PageType.NATIVE_TEXT


def test_coordinate_chain_preserves_points_through_crop_rotate_deskew_resize():
    angle = np.deg2rad(5)
    rotation = [[np.cos(angle), -np.sin(angle), 20], [np.sin(angle), np.cos(angle), -10], [0, 0, 1]]
    chain = (CoordinateChain("pdf_points")
        .then("dpi", "render_pixels", [[2, 0, 0], [0, 2, 0], [0, 0, 1]])
        .then("crop", "crop_pixels", [[1, 0, -50], [0, 1, -70], [0, 0, 1]])
        .then("deskew", "deskew_pixels", rotation)
        .then("resize", "tensor_pixels", [[.5, 0, 3], [0, .6, 5], [0, 0, 1]]))
    points = [[20, 40], [200, 400], [100, 200]]
    mapped = chain.points(points)
    assert np.asarray(chain.inverse().points(mapped)) == pytest.approx(np.asarray(points))
    restored = CoordinateChain.from_dict(chain.to_dict())
    assert restored.matrix == pytest.approx(chain.matrix)
    with pytest.raises(ValueError, match="invertible"):
        chain.then("broken", "bad", [[0, 0, 0], [0, 1, 0], [0, 0, 1]])
