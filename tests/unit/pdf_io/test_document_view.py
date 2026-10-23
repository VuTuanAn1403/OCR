"""PDF processing views retain source bytes, pages, rotation and rendering."""
import hashlib

import pymupdf
import pytest

from ocr_pdf_io.document_view import processing_pdf


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_normalized_view_preserves_geometry_text_and_pixels(tmp_path, rotation):
    path = tmp_path / "source.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page(width=300, height=400)
        page.insert_text((30, 60), "OCR source 123.45%")
        page.set_rotation(rotation)
        doc.new_page(width=450, height=200)
        doc.save(path)
    before = path.read_bytes()
    source_hash = hashlib.sha256(before).hexdigest()
    with processing_pdf(path, "original_v1") as (original, _):
        text = original[0].get_text()
        pixels = original[0].get_pixmap(dpi=72).samples
    with processing_pdf(path, "normalized_memory_v1", expected_sha256=source_hash) as (view, evidence):
        assert len(view) == 2 and view[0].rotation == rotation
        assert view[0].get_text() == text
        assert view[0].get_pixmap(dpi=72).samples == pixels
        assert evidence["source_pdf_sha256"] == source_hash
        assert evidence["source_file_modified"] is False
        assert evidence["view_pdf_sha256"] != source_hash
    with processing_pdf(path, "normalized_memory_v1") as (_, repeated):
        assert repeated == evidence
    assert view.is_closed and path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]


def test_wrong_source_and_unknown_policy_are_refused(tmp_path):
    path = tmp_path / "source.pdf"
    with pymupdf.open() as doc:
        doc.new_page()
        doc.save(path)
    with pytest.raises(ValueError, match="source changed"):
        with processing_pdf(path, "normalized_memory_v1", expected_sha256="wrong"):
            pytest.fail("must not open a changed source")
    with pytest.raises(ValueError, match="Unknown"):
        with processing_pdf(path, "unknown"):
            pytest.fail("must not silently ignore a policy typo")
