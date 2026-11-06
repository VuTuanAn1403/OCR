"""The exported row tree is partial, geometric, and bound to extraction cells."""
import copy
import json

import pytest

from ocr_contracts.document import ExtractedDocument
from ocr_contracts.page import ExtractedPage
from ocr_contracts.page_type import PageType
from ocr_contracts.quality import DocumentQualityReport, PageQualityReport
from ocr_contracts.table import TableCell, TableStructure
from ocr_document.contract_schema import validate_contract_set
from ocr_document.document_contracts import write_document_contracts
from ocr_document.table_hierarchy import infer_row_hierarchy


def test_export_preserves_rows_and_writes_source_bound_tree(tmp_path):
    labels = [("A. TÀI SẢN", 50), ("I. Tài sản ngắn hạn", 54), ("1. Tiền và tương đương tiền", 60),
              ("- Tiền gửi ngân hàng", 67), ("2. Đầu tư ngắn hạn", 60), ("II. Tài sản dài hạn", 54),
              ("1. Tài sản cố định", 60), ("Cộng", 50), ("1. Chỉ tiêu độc lập", 60)]
    cells = []
    for row, (label, x) in enumerate(labels):
        y = 60 + row * 22
        cells.extend([TableCell(row_idx=row, col_idx=0, bbox=[x, y, 260, y + 14], text=label),
                      TableCell(row_idx=row, col_idx=1, bbox=[310, y, 410, y + 14], text="1.234,50")])
    table = TableStructure(table_id="a", page=1, bbox=[48, 57, 414, 258], num_rows=len(labels), num_cols=2, cells=cells)
    page = ExtractedPage(page_num=1, width=600, height=800, page_type=PageType.MIXED, tables=[table],
                         quality=PageQualityReport(page=1, page_type="MIXED"))
    doc = ExtractedDocument(document_id="report", file_path="report.pdf", file_hash="abcdef0123456789",
                            total_pages=1, pages=[page], manifest={"document_layout": {"method": "region_tree_graph_v1"}},
                            quality=DocumentQualityReport(document_id="report", total_pages=1))
    write_document_contracts(doc, tmp_path, "none")
    extraction, document, structure = [json.loads((tmp_path / f"{kind}.json").read_text(encoding="utf-8"))
                                       for kind in ("extraction", "document", "structure")]
    assert validate_contract_set(extraction, document, structure) == []
    out, = document["tables"]
    assert out["cells"] == extraction["pages"][0]["items"][0]["cells"]
    nodes = out["row_hierarchy"]["nodes"]
    assert [(n["row"], n["parent_row"], n["depth"]) for n in nodes] == [
        (0, None, 0), (1, 0, 1), (2, 1, 2), (3, 2, 3), (4, 1, 2), (5, 0, 1), (6, 5, 2)]
    assert nodes[2]["signal"] == "NUMBERING_AND_INDENTATION" and nodes[2]["indent_pt"] == 6.0
    assert nodes[3]["signal"] == "INDENTED_BULLET"

    changed = copy.deepcopy(document)
    changed["tables"][0]["row_hierarchy"]["nodes"][2]["parent_row"] = 0
    assert any("row hierarchy differs from extraction.json evidence" in error
               for error in validate_contract_set(extraction, changed, structure))


def _cell(row, col, text, x0, x1, *, bbox_source="cell", row_span=1, y=None):
    y = row * 20 if y is None else y
    return {"row": row, "col": col, "text_corrected": text, "bbox": [x0, y, x1, y + 13],
            "bbox_source": bbox_source, "row_span": row_span, "col_span": 1}


def test_split_markers_require_the_exact_number_prefix():
    entries = []
    for row, code, label in [(0, "7.", "Các khoản phải thu"), (1, "7.2", "Phải thu cổ tức"),
                             (2, "7.2.1", "Cổ tức đến hạn"), (3, "8.3.1", "Tiền khác")]:
        entries.extend([_cell(row, 0, code, 35, 61), _cell(row, 1, label, 74, 190)])
    nodes = infer_row_hierarchy(entries)["nodes"]
    assert [(n["row"], n["parent_row"], n["depth"], n["marker_col"], n["label_col"]) for n in nodes] == [
        (0, None, 0, 0, 1), (1, 0, 1, 0, 1), (2, 1, 2, 0, 1)]
    assert nodes[1]["signal"] == "NUMBERING"


@pytest.mark.parametrize("barrier", ["fallback", "missing_row", "overlapping", "rowspan", "unmarked", "signed_amount"])
def test_row_hierarchy_abstains_without_placed_subordinate_evidence(barrier):
    row = 2 if barrier == "missing_row" else 1
    cells = [_cell(0, 0, "I. Tài sản ngắn hạn", 50, 220), _cell(0, 1, "100", 270, 310)]
    text = {"unmarked": "Tiền và tương đương tiền", "signed_amount": "- USD 120"}.get(barrier, "1. Tiền")
    cells.extend([_cell(row, 0, text, 66, 200, bbox_source="table_fallback" if barrier == "fallback" else "cell",
                        row_span=2 if barrier == "rowspan" else 1, y=2 if barrier == "overlapping" else None),
                  _cell(row, 1, "100", 270, 310)])
    assert infer_row_hierarchy(cells) is None
