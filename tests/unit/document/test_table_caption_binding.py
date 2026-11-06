"""Caption links use existing export chunks and preserve source evidence."""
import copy
import json

import pytest

from ocr_contracts.document import ExtractedDocument
from ocr_contracts.page import ExtractedPage
from ocr_contracts.page_type import PageType
from ocr_contracts.quality import DocumentQualityReport, PageQualityReport
from ocr_contracts.table import TableCell, TableStructure
from ocr_contracts.text_block import TextBlock
from ocr_document.contract_schema import validate_contract_set
from ocr_document.document_contracts import write_document_contracts
from ocr_document.figures import link_table_captions


@pytest.mark.parametrize("has_unit", [False, True])
def test_modern_export_links_the_title_to_its_table(tmp_path, has_unit):
    label = "Bảng: Tình hình tài chính 2020" if has_unit else "Biểu đồ 3: Tăng trưởng doanh thu 2020-2024"
    table_top = 140 if has_unit else 105
    blocks = [TextBlock(text=label, text_raw=label, page=1, bbox=[80, 80, 340, 95],
                        block_type="caption", confidence=.99, quality_score=.99)]
    if has_unit:
        blocks.append(TextBlock(text="Đơn vị: tỷ đồng", page=1, bbox=[360, 105, 440, 120],
                                block_type="text", confidence=.99, quality_score=.99))
    page = ExtractedPage(
        page_num=1, width=600, height=800, page_type=PageType.MIXED,
        blocks=blocks,
        tables=[TableStructure(table_id="t1", page=1, bbox=[70, table_top, 470, 250], num_rows=1, num_cols=1,
                               cells=[TableCell(row_idx=0, col_idx=0, text="1.234", bbox=[70, table_top, 470, 250])])],
        quality=PageQualityReport(page=1, page_type="MIXED"),
    )
    doc = ExtractedDocument(document_id="report", file_path="report.pdf", file_hash="abcdef0123456789",
                            total_pages=1, pages=[page],
                            manifest={"document_layout": {"method": "region_tree_graph_v1"}},
                            quality=DocumentQualityReport(document_id="report", total_pages=1))
    write_document_contracts(doc, tmp_path, "none")
    extraction, document, structure = [json.loads((tmp_path / f"{kind}.json").read_text(encoding="utf-8"))
                                       for kind in ("extraction", "document", "structure")]
    assert validate_contract_set(extraction, document, structure) == []
    table, = document["tables"]
    caption = next(chunk for chunk in document["chunks"] if chunk["text_corrected"] == label)
    expected = {"chunk_id": caption["chunk_id"], "position": "above", "gap_pt": float(table_top - 95),
                "method": "table-caption-adjacency-v1", "label": "table" if has_unit else "chart"}
    if has_unit:
        unit = next(chunk for chunk in document["chunks"] if chunk["text_corrected"] == "Đơn vị: tỷ đồng")
        expected["unit_chunk_id"] = unit["chunk_id"]
    assert table["caption"] == expected
    assert caption["text_raw"] == caption["text_corrected"] == label
    assert caption["spans"][0]["bbox"] == [80, 80, 340, 95]
    assert table["cells"][0]["text_raw"] == "1.234"
    assert (tmp_path / "document.md").read_text(encoding="utf-8").count(label) == 1

    bad = copy.deepcopy(document)
    bad["tables"][0]["caption"]["gap_pt"] = 2.0
    assert any("caption geometry differs from extraction.json" in e
               for e in validate_contract_set(extraction, bad, structure))
    if has_unit:
        bad = copy.deepcopy(document)
        bad["tables"][0]["caption"]["unit_chunk_id"] = caption["chunk_id"]
        assert any("invalid caption unit evidence" in e for e in validate_contract_set(extraction, bad, structure))


def _chunk(ref, kind, bbox, *, page=1, section="a", text=""):
    return {"chunk_id": ref, "type": kind, "section_id": section, "text_corrected": text,
            "spans": [{"bbox": bbox, "page": page, "block_ids": [ref]}]}


@pytest.mark.parametrize("obstruction", ["body", "image", "two_tables", "two_captions", "other_page", "other_section"])
def test_caption_abstains_when_geometry_does_not_identify_one_pair(obstruction):
    title = _chunk("b", "paragraph", [100, 60, 300, 80], text="Biểu đồ 3: Tăng trưởng doanh thu")
    table = _chunk("t", "table", [80, 104, 350, 220],
                   page=2 if obstruction == "other_page" else 1,
                   section="b" if obstruction == "other_section" else "a")
    chunks = [title, table]
    tables = [{"chunk_id": "t"}]
    if obstruction == "body":
        chunks.append(_chunk("p", "paragraph", [100, 86, 300, 99], text="Đơn vị tính theo báo cáo."))
    elif obstruction == "image":
        chunks.append(_chunk("i", "image", [85, 110, 350, 300]))
    elif obstruction == "two_tables":
        chunks.append(_chunk("t2", "table", [80, 10, 350, 48]))
        tables.append({"chunk_id": "t2"})
    elif obstruction == "two_captions":
        chunks.append(_chunk("b2", "paragraph", [100, 226, 300, 240], text="Bảng 4: Tổng doanh thu"))
    link_table_captions(chunks, tables)
    assert all("caption" not in t for t in tables)
