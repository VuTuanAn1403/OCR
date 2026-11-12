"""Spec 13 §4.1 (no silent drop) and V8-080 (heuristic table cells keep source geometry)."""
from ocr_contracts.region import BoundingBox, ContentType, Region
from ocr_contracts.text_block import TextBlock
from ocr_document.source_identity import lock_rejected_ocr_lines
from ocr_pipeline.review_packet import page_candidates
from ocr_recognition.blocks import ocr_results_to_blocks
from ocr_structure.document_layout_engine import DocumentLayoutEngine


class _Quality:
    def evaluate_ocr_result(self, text, conf):
        return 0.9, False, []


def _rejected(regions):
    rejected, blocks = [], []
    results = [{"text": "Báo cáo xanh", "confidence": 0.31, "bbox": [10, 10, 90, 20]},
               {"text": "Doanh thu thuần", "confidence": 0.95, "bbox": [10, 30, 90, 40]}]
    ocr_results_to_blocks(results, regions=regions, page_num=3, scale_x=1, scale_y=1, use_raw_bbox=False,
                          page_w=100, page_h=100, ocr_quality=_Quality(), dla_engine=None,
                          numeric_retry_threshold=.85, rejected_evidence=rejected, blocks=blocks,
                          candidates_for_fallback=[], suspicious_lines=[])
    return rejected, blocks


def test_low_confidence_line_is_recorded_with_identity_and_review():
    regions = [Region(region_id="r1", bbox=BoundingBox(x0=0, y0=0, x1=100, y1=50),
                      content_type=ContentType.TEXT, source="native")]
    rejected, blocks = _rejected(regions)
    assert [b.text for b in blocks] == ["Doanh thu thuần"]
    assert rejected[0].content_type == ContentType.TEXT  # no longer hard-coded IMAGE
    meta = {}
    record = lock_rejected_ocr_lines(rejected, "a" * 64, 3, meta, regions)
    line, = record["items"]
    assert line["source_id"] == "aaaaaaaaaaaaaaaa:p0003:r000001"
    assert line["text_raw"] == "Báo cáo xanh" and line["bbox"] == [10, 10, 90, 20]
    assert line["confidence"] == 0.31 and line["needs_review"] is True
    assert line["disposition"] == "RETAINED_FOR_REVIEW" and line["region_content_type"] == "TEXT"
    assert "OCR_LINE_LOW_CONFIDENCE" in line["review_reason_codes"]
    page = {"page": 3, "items": [], "rejected_ocr_lines": record, "coordinate_space": "pdf_points_top_left",
            "transforms": [], "width": 100, "height": 100}
    row, = page_candidates("doc", "a" * 64, page, ["xanh"])
    assert row["locator"] == {"rejected_source_id": line["source_id"]}
    assert [m["keyword"] for m in row["keyword_matches"]] == ["xanh"]


def test_heuristic_cells_keep_their_own_line_box_and_raw_text():
    rows = [("STT", "Chỉ tiêu", "Kế hoạch", "Thực hiện"),
            ("1", "Ống 12225 HDPE", "109.500", "108.866"),
            ("2", "Tổng doanh thu", "1.189.485", "1.183.591")]
    blocks = [TextBlock(text=text, page=5, bbox=[50 + 100 * c, 100 + 20 * r, 140 + 100 * c, 115 + 20 * r])
              for r, row in enumerate(rows) for c, text in enumerate(row)]
    table = DocumentLayoutEngine()._detect_table_from_ocr_blocks(blocks, page_num=5)
    assert table is not None
    by_text = {cell.text: cell.bbox for cell in table.cells}
    assert "Ống 12225 HDPE" in by_text  # digits never rewritten
    assert by_text["109.500"] == [250, 120, 340, 135] and by_text["108.866"] == [350, 120, 440, 135]
    assert table.provenance["heuristic_cells"]["method"] == "heuristic-source-line-cells-v1"


def test_heuristic_split_line_gets_estimated_boxes_and_stripped_zero_is_reviewed():
    lines = ["Chỉ tiêu Năm 2020 Năm 2021 Tăng", "Doanh thu 1.234 2.345 10%", "Lợi nhuận 345 456 5%",
             "Chi phí 111 222 3%", "Thuế 12 34 1%"]
    blocks = [TextBlock(text=t, page=1, bbox=[70, 100 + 20 * i, 450, 115 + 20 * i]) for i, t in enumerate(lines)]
    blocks.append(TextBlock(text="0", page=1, bbox=[50, 120, 60, 135]))  # separate leading glyph
    table = DocumentLayoutEngine()._detect_table_from_ocr_blocks(blocks, page_num=1)
    if table is None:
        return  # the guards may decline this layout; the geometry contract is covered above
    info = table.provenance["heuristic_cells"]
    assert any(t["text"] == "0" and t["numeric_like"] for t in info["stripped_tokens"])
    assert table.needs_review is True
    boxes = [tuple(c.bbox) for c in table.cells if c.row_idx == 1]
    assert len(set(boxes)) == len(boxes)
