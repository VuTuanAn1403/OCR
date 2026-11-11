"""V8-130: DOCX/XLSX exports keep table structure and survive a read-back round trip."""
import zipfile
from io import BytesIO
from xml.etree import ElementTree

from openpyxl import load_workbook

from ocr_reporting import structured_export as export

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def cell(row, col, text, rs=1, cs=1, raw=None):
    return {"row": row, "col": col, "row_span": rs, "col_span": cs, "text_corrected": text,
            "text_raw": text if raw is None else raw}


def document(cells, rows=4, cols=3):
    return {
        "sections": [{"section_id": "s1", "level": 1, "title": "Báo cáo tài chính"}],
        "chunks": [{"chunk_id": "p1", "section_id": "s1", "type": "paragraph", "text_corrected": "Đoạn mở đầu"},
                   {"chunk_id": "t1", "section_id": "s1", "type": "table"},
                   {"chunk_id": "l1", "section_id": "s1", "type": "list_item", "text_corrected": "cổ đông lớn"},
                   {"chunk_id": "i1", "section_id": "s1", "type": "image", "asset": "images/p1.png"}],
        "tables": [{"table_id": "t1", "chunk_id": "t1", "pages": [3], "num_rows": rows, "num_cols": cols,
                    "engine": "docling_tableformer", "cells": cells}],
    }


SPANNED = [cell(0, 0, "Khoản mục", rs=2), cell(0, 1, "Năm 2020", cs=2), cell(1, 1, "Giá trị"),
           cell(1, 2, "Tỷ trọng"), cell(2, 0, "Doanh thu & lãi <ròng>"), cell(2, 1, "1.234,5"),
           cell(2, 2, "10%"), cell(3, 2, "dòng 1\ndòng 2")]


def test_spanned_table_round_trips_through_docx_and_xlsx():
    doc = document(SPANNED)
    docx, docx_warnings = export.docx_bytes(doc)
    xlsx, xlsx_warnings = export.xlsx_bytes(doc)
    assert docx_warnings == xlsx_warnings == []
    result = export.round_trip(doc, docx, xlsx)
    assert result["status"] == "ROUND_TRIP_OK" and result["tables"] == result["docx_tables"] == 1
    (grid,) = export.docx_table_grids(docx)
    assert grid[(0, 0)] == ("Khoản mục", 2, 1) and grid[(0, 1)] == ("Năm 2020", 1, 2)
    assert grid[(2, 0)] == ("Doanh thu & lãi <ròng>", 1, 1) and grid[(3, 2)] == ("dòng 1\ndòng 2", 1, 1)
    book = load_workbook(BytesIO(xlsx))
    sheet = book["T0001"]
    assert {str(rng) for rng in sheet.merged_cells.ranges} == {"A1:A2", "B1:C1"}
    assert sheet["B3"].value == "1.234,5" and sheet["B3"].number_format == "@"  # never reformatted
    assert [c.value for c in book["Index"][2]][:5] == ["T0001", "t1", "3", 4, 3]
    book.close()


def test_docx_keeps_reading_order_headings_lists_and_images():
    docx, _ = export.docx_bytes(document(SPANNED))
    with zipfile.ZipFile(BytesIO(docx)) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
        assert {"[Content_Types].xml", "word/styles.xml", "_rels/.rels"} <= set(archive.namelist())
    body = root.find(f"{W}body")
    kinds = [child.tag.replace(W, "") for child in body]
    texts = ["".join(t.text or "" for t in child.iter(f"{W}t")) for child in body]
    assert texts[0] == "Báo cáo tài chính"
    assert body[0].find(f"{W}pPr/{W}pStyle").get(f"{W}val") == "Heading1"
    assert texts[1] == "Đoạn mở đầu" and kinds[2] == "tbl"
    assert "• cổ đông lớn" in texts and "[Hình: images/p1.png]" in texts


def test_colliding_cells_keep_their_text_and_are_reported():
    cells = [cell(0, 0, "A", cs=2), cell(0, 1, "B"), cell(0, 0, "A2"), cell(1, 0, "C", rs=3), cell(2, 0, "D")]
    doc = document(cells, rows=2, cols=2)
    layout = export.table_layout(doc["tables"][0])
    # Same anchor (A2): texts joined. Address inside another span (B, D): that span shrinks, so
    # B and D keep their own cells (numeric cells must stay at their addresses).
    assert layout.anchors[(0, 0)] == {"text": "A\nA2", "rs": 1, "cs": 1}
    assert layout.anchors[(0, 1)]["text"] == "B" and layout.anchors[(2, 0)]["text"] == "D"
    assert layout.anchors[(1, 0)] == {"text": "C", "rs": 1, "cs": 1}
    assert layout.rows == 4  # span past the declared size enlarges the grid
    assert len(layout.warnings) == 4
    docx, warnings = export.docx_bytes(doc)
    xlsx, _ = export.xlsx_bytes(doc)
    assert len(warnings) == 4
    assert export.round_trip(doc, docx, xlsx)["status"] == "ROUND_TRIP_OK"
    values = {str(c.value) for row in load_workbook(BytesIO(xlsx))["T0001"].iter_rows() for c in row if c.value}
    assert values == {"A\nA2", "B", "C", "D"}


def test_text_field_control_characters_and_determinism():
    cells = [cell(0, 0, "đã sửa", raw="da sua"), cell(0, 1, "tab" + chr(9) + "ok" + chr(11) + chr(0))]
    doc = document(cells, rows=1, cols=2)
    corrected, _ = export.docx_bytes(doc)
    raw, _ = export.docx_bytes(doc, text_field="text_raw")
    assert export.docx_table_grids(corrected)[0][(0, 0)][0] == "đã sửa"
    assert export.docx_table_grids(raw)[0][(0, 0)][0] == "da sua"
    assert export.docx_table_grids(corrected)[0][(0, 1)][0] == "tab" + chr(9) + "ok"
    assert export.docx_bytes(doc)[0] == corrected  # identical input, identical bytes
