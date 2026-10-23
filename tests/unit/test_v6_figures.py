"""Figure captions and figure text in document.json (proposal V6 C3.6,
review item R-09)."""
from process_test_helpers import historical_profiles
import copy
import json

import pymupdf

from src.ocr.application.convert_document import ConvertDocumentUseCase
from src.ocr.infrastructure.export.contract_schema import validate_contract_pair
from src.ocr.infrastructure.structure.figures import link_figures

DOC = "abcd1234abcd1234"


def _chunk(n, text, box, page=1, kind="paragraph", spans=None):
    cid = f"{DOC}:p{page:04d}:{'i' if kind == 'image' else 'b'}{n:04d}"
    return {"chunk_id": cid, "type": kind, "text_corrected": text,
            "spans": spans or [{"page": page, "bbox": box, "block_ids": [cid]}]}


def _figure_page():
    image = _chunk(1, "", [100, 100, 400, 300], kind="image")
    chunks = [image,
              _chunk(2, "Doanh thu 2025", [150, 150, 300, 165]),             # inside the figure
              _chunk(3, "Hình 1. Cơ cấu doanh thu", [120, 310, 380, 322]),   # 10 pt below
              _chunk(4, "Hình 2. Không phải chú thích", [120, 400, 380, 412]),  # too far
              _chunk(5, "Bảng 1. Số liệu", [120, 90, 380, 98]),              # table caption word
              _chunk(6, "Nội dung thường", [120, 302, 380, 308])]           # no caption word
    images = [{"image_id": image["chunk_id"], "chunk_id": image["chunk_id"]}]
    return chunks, images


def test_figure_text_and_keyword_caption_are_linked():
    chunks, images = _figure_page()
    summary = link_figures(chunks, images)
    by_text = {c["text_corrected"]: c for c in chunks}
    assert by_text["Doanh thu 2025"]["role"] == "figure_text"
    assert images[0]["figure_text_chunk_ids"] == [by_text["Doanh thu 2025"]["chunk_id"]]
    assert images[0]["caption"] == {"chunk_id": by_text["Hình 1. Cơ cấu doanh thu"]["chunk_id"],
                                    "position": "below", "gap_pt": 10.0}
    for text in ("Hình 2. Không phải chú thích", "Bảng 1. Số liệu", "Nội dung thường"):
        assert "role" not in by_text[text]
    assert summary["captions_linked"] == 1 and summary["evaluation"] == "NOT_EVALUATED"


def test_unsure_cases_stay_unlinked():
    image = _chunk(1, "", [100, 100, 400, 300], kind="image")
    multi_page = _chunk(2, "Hình 3. Qua trang", None, spans=[
        {"page": 1, "bbox": [120, 305, 380, 315], "block_ids": [f"{DOC}:p0001:b0002"]},
        {"page": 2, "bbox": [120, 40, 380, 50], "block_ids": [f"{DOC}:p0002:b0001"]}])
    side = _chunk(3, "Hình 4. Lệch sang bên", [420, 305, 560, 315])  # no horizontal overlap
    images = [{"image_id": image["chunk_id"], "chunk_id": image["chunk_id"]}]
    link_figures([image, multi_page, side], images)
    assert images[0]["caption"] is None and images[0]["figure_text_chunk_ids"] == []


def _figure_pdf(path):
    with pymupdf.open() as art:
        canvas = art.new_page(width=300, height=200)
        canvas.draw_rect(canvas.rect, color=(0, 0, 0), fill=(0.85, 0.9, 1.0))
        canvas.insert_text((40, 100), "DOANH THU 2025", fontsize=22)
        pixmap = canvas.get_pixmap(dpi=150)
    with pymupdf.open() as doc:
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 80), "Báo cáo hoạt động kinh doanh trong năm", fontsize=12)
        page.insert_image(pymupdf.Rect(100, 120, 500, 387), pixmap=pixmap)
        page.insert_text((110, 405), "Hình 1. Cơ cấu doanh thu theo sản phẩm", fontsize=11)
        page.insert_text((72, 460), "Doanh thu tăng trưởng ổn định so với năm trước.", fontsize=12)
        doc.save(path)
    return path


def test_pipeline_links_the_caption_and_validates(tmp_path):
    pdf = _figure_pdf(tmp_path / "FIG_doc.pdf")
    ConvertDocumentUseCase(config_path=historical_profiles()).execute(str(pdf), "fast", output_dir=str(tmp_path / "out"),
                                     cache_dir=str(tmp_path / "cache"), assets_mode="none")
    out = tmp_path / "out/FIG_doc"
    document = json.loads((out / "document.json").read_text(encoding="utf-8"))
    assert json.loads((out / "validation.json").read_text(encoding="utf-8"))["status"] != "FAIL"
    assert document["figure_links"]["status"] == "COMPLETED"
    (image,) = document["images"]
    caption = next(c for c in document["chunks"] if c["chunk_id"] == image["caption"]["chunk_id"])
    assert caption["text_corrected"].startswith("Hình 1.") and caption["role"] == "caption"

    extraction = json.loads((out / "extraction.json").read_text(encoding="utf-8"))
    assert validate_contract_pair(extraction, document) == []
    broken = copy.deepcopy(document)
    next(c for c in broken["chunks"] if c["chunk_id"] == caption["chunk_id"])["figure_id"] = None
    assert any("caption link" in e or "out of step" in e for e in validate_contract_pair(extraction, broken))
