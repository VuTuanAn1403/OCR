"""Automatic export must join a cut row and preserve every physical source cell."""
from copy import deepcopy
import json

import pymupdf
import pytest

from ocr_contracts.document import ExtractedDocument
from ocr_contracts.page import ExtractedPage
from ocr_contracts.page_type import PageType
from ocr_contracts.quality import DocumentQualityReport, PageQualityReport
from ocr_contracts.table import TableCell, TableStructure
from ocr_document.auto_table_stitch import build_auto_stitches
from ocr_document.contract_schema import validate_contract_pair
from ocr_document.export import DocumentExporter


def example(tmp_path, *, split=True):
    pdf = tmp_path / "source.pdf"
    with pymupdf.open() as doc:
        doc.new_page(width=600, height=800)
        doc.new_page(width=600, height=800)
        doc.save(pdf)
    headers = ["Chỉ tiêu", "Năm 2025", "Năm 2024"]
    data = [[headers, ["Khoản mục trước", "10", "11"], ["Khoản đầu tư vào", "", ""]],
            [headers, ["công ty liên kết", "(020)", "30"], ["Khoản mục sau", "40", "50"]]]
    if not split:
        data[0][-1] = ["Khoản mục độc lập", "12", "13"]
        data[1][1][0] = "Khoản mục mới"
    pages = []
    for n, rows in enumerate(data, 1):
        top = 650 if n == 1 else 10
        cells = [TableCell(row_idx=r, col_idx=c, text=text, confidence=.99,
                           bbox=[40+170*c, top+40*r, 40+170*(c+1), top+40*(r+1)])
                 for r, values in enumerate(rows) for c, text in enumerate(values)]
        table = TableStructure(table_id=f"source-table-{n}", page=n, bbox=[40, top, 550, top+120],
                               num_rows=3, num_cols=3, cells=cells, engine="docling_tableformer", confidence=.99)
        pages.append(ExtractedPage(page_num=n, width=600, height=800, page_type=PageType.MIXED,
                                   tables=[table], quality=PageQualityReport(page=n, page_type="mixed")))
    return ExtractedDocument(document_id="source", file_path=str(pdf), file_hash="a"*16, total_pages=2,
                             selected_pages=[1, 2], pages=pages, quality=DocumentQualityReport(document_id="source", total_pages=2),
                             manifest={"device": "cuda", "document_id": "source", "file_hash": "a"*16,
                                       "selected_pages": [1, 2], "configuration": {
                                 "document_layout": {"method": "region_tree_graph_v1"},
                                 "table_stitch": {"method": "auto_v1"}}})


@pytest.mark.parametrize("split", [True, False])
def test_export_automatically_projects_one_table_and_counts_each_source_once(tmp_path, split):
    doc = example(tmp_path, split=split)
    original_cells = [[c.model_dump() for c in page.tables[0].cells] for page in doc.pages]
    out = DocumentExporter.execute(doc, tmp_path / "out", assets_mode="none", output_mode="compact")
    extraction = json.loads((out / "extraction.json").read_text(encoding="utf-8"))
    document = json.loads((out / "document.json").read_text(encoding="utf-8"))
    group, = document["table_stitch"]["logical_tables"]
    assert group["projection"]["boundaries"][0]["kind"] == ("SPLIT_ROW" if split else "BETWEEN_ROWS")
    assert group["projection"]["observed_source_cells"] == 18
    assert group["needs_review"] and document["table_stitch"]["acceptance"] == "NOT_EVALUATED"
    assert len(document["tables"]) == len(extraction["pages"]) == 2
    assert original_cells == [[c.model_dump() for c in page.tables[0].cells] for page in doc.pages]
    for name in ("document.md", "result.md"):
        text = (out / name).read_text(encoding="utf-8")
        assert text.count("Năm 2025") == 1 and text.count("(020)") == 1
        assert text.count("Khoản mục trước") == text.count("Khoản mục sau") == 1
        if split:
            assert "Khoản đầu tư vào<br>công ty liên kết" in text
    assert (out / group["html_path"]).is_file()
    plain = (out / "result.txt").read_text(encoding="utf-8")
    assert plain.count("Năm 2025") == 1 and plain.count("(020)") == 1
    assert "[HTML đầy đủ]" not in plain and "HTML đầy đủ" in plain
    assert validate_contract_pair(extraction, document) == []
    corrupt = deepcopy(document)
    corrupt["table_stitch"]["logical_tables"][0]["projection"]["cells"][0]["sources"][0]["cell"]["text_raw"] = "fake"
    assert any("stitch differs" in error for error in validate_contract_pair(extraction, corrupt))


def test_adjacent_tables_with_a_closed_total_or_new_caption_stay_separate(tmp_path):
    doc = example(tmp_path, split=False)
    out = DocumentExporter.execute(doc, tmp_path / "out", assets_mode="none")
    extraction = json.loads((out / "extraction.json").read_text(encoding="utf-8"))
    document = json.loads((out / "document.json").read_text(encoding="utf-8"))
    document["tables"][1]["caption"] = {"chunk_id": "new-caption"}
    report = build_auto_stitches(extraction, document)
    assert not report["logical_tables"] and report["decisions"][0]["reason"] == "following_table_has_new_caption"
    document["tables"][1].pop("caption")
    document["tables"][0]["cells"][-3]["text_raw"] = "Tổng cộng"
    extraction["pages"][0]["items"][0]["cells"][-3]["text_raw"] = "Tổng cộng"
    report = build_auto_stitches(extraction, document)
    assert not report["logical_tables"] and report["decisions"][0]["reason"] == "previous_table_ends_with_total"


@pytest.mark.parametrize("amount", ["0", "2025"])
@pytest.mark.parametrize("label", ["Khác", "Tài sản khác"])
def test_equal_financial_data_rows_are_never_removed_as_headers(tmp_path, amount, label):
    doc = example(tmp_path, split=False)
    for page in doc.pages:
        for cell in page.tables[0].cells:
            if cell.row_idx == 1:
                cell.text = label if cell.col_idx == 0 else amount
    out = DocumentExporter.execute(doc, tmp_path / "out", assets_mode="none")
    document = json.loads((out / "document.json").read_text(encoding="utf-8"))
    group, = document["table_stitch"]["logical_tables"]
    assert group["projection"]["boundaries"][0]["repeated_header_rows"] == 1
    for name in ("result.md", "document.md"):
        assert (out / name).read_text(encoding="utf-8").count(label) == 2


def test_model_header_roles_distinguish_bare_year_header_from_equal_amounts(tmp_path):
    doc = example(tmp_path, split=False)
    for page in doc.pages:
        for cell in page.tables[0].cells:
            cell.column_header = cell.row_idx == 0
            if cell.row_idx == 0 and cell.col_idx:
                cell.text = "2025" if cell.col_idx == 1 else "2024"
            elif cell.row_idx == 1:
                cell.text = "Tài sản khác" if cell.col_idx == 0 else "2025"
    out = DocumentExporter.execute(doc, tmp_path / "out", assets_mode="none")
    document = json.loads((out / "document.json").read_text(encoding="utf-8"))
    group, = document["table_stitch"]["logical_tables"]
    assert group["projection"]["boundaries"][0]["repeated_header_rows"] == 1
    assert (out / "result.txt").read_text(encoding="utf-8").count("Tài sản khác") == 2
    assert document["tables"][0]["cells"][0]["column_header"] is True


def test_cut_financial_row_keeps_code_column_and_complementary_period_values(tmp_path):
    doc = example(tmp_path, split=True)
    for page in doc.pages:
        table = page.tables[0]
        for cell in table.cells:
            if cell.col_idx == 0:
                cell.col_idx = 1
                cell.bbox[0] += 100
                cell.bbox[2] += 100
            elif cell.col_idx == 1:
                cell.col_idx = 0
                cell.bbox[0] -= 170
                cell.bbox[2] -= 170
        for row in range(3):
            left = next(c for c in table.cells if c.row_idx == row and c.col_idx == 0)
            label = next(c for c in table.cells if c.row_idx == row and c.col_idx == 1)
            amount = next(c for c in table.cells if c.row_idx == row and c.col_idx == 2)
            left.bbox = [40, left.bbox[1], 110, left.bbox[3]]
            label.bbox = [110, label.bbox[1], 380, label.bbox[3]]
            amount.bbox = [380, amount.bbox[1], 550, amount.bbox[3]]
            left.text = "Mã số" if row == 0 else "12" if page.page_num == 1 and row == 2 else "" if page.page_num == 2 and row == 1 else "10"
    out = DocumentExporter.execute(doc, tmp_path / "out", assets_mode="none")
    document = json.loads((out / "document.json").read_text(encoding="utf-8"))
    group, = document["table_stitch"]["logical_tables"]
    assert group["projection"]["boundaries"][0]["kind"] == "SPLIT_ROW"
    text = (out / "result.txt").read_text(encoding="utf-8")
    assert "Khoản đầu tư vào\ncông ty liên kết" in text
    assert "12" in text and "30" in text


def test_observed_two_row_header_keeps_years_and_every_data_occurrence(tmp_path):
    doc = example(tmp_path, split=True)
    for page in doc.pages:
        table = page.tables[0]
        top = table.bbox[1]
        for cell in table.cells:
            cell.column_header = cell.row_idx == 0
            if cell.row_idx >= 1:
                cell.row_idx += 1
                cell.bbox[1] += 20
                cell.bbox[3] += 20
        table.cells.extend(TableCell(row_idx=1, col_idx=c, text=text, column_header=True,
                                     bbox=[40+170*c, top+40, 40+170*(c+1), top+60])
                           for c, text in enumerate(["", "2025", "2024"]))
        table.num_rows += 1
        table.bbox[3] += 20
    out = DocumentExporter.execute(doc, tmp_path / "out", assets_mode="none")
    document = json.loads((out / "document.json").read_text(encoding="utf-8"))
    group, = document["table_stitch"]["logical_tables"]
    assert group["projection"]["boundaries"][0]["repeated_header_rows"] == 2
    assert group["projection"]["observed_source_cells"] == 24
    text = (out / "result.txt").read_text(encoding="utf-8")
    assert text.count("Năm 2025") == 1 and text.count("(020)") == 1


def spanned_header_example(tmp_path):
    doc = example(tmp_path, split=True)
    for page in doc.pages:
        table = page.tables[0]
        top = table.bbox[1]
        table.cells = [c for c in table.cells if c.row_idx != 0]
        for cell in table.cells:
            cell.row_idx += 1
            cell.bbox[1] += 40
            cell.bbox[3] += 40
            cell.column_header = False
        table.cells.extend([
            TableCell(row_idx=0, col_idx=0, row_span=2, text="Chỉ tiêu", column_header=True,
                      bbox=[40, top, 210, top+80]),
            TableCell(row_idx=0, col_idx=1, col_span=2, text="Giá trị", column_header=True,
                      bbox=[210, top, 550, top+40]),
            TableCell(row_idx=1, col_idx=1, text="2025", column_header=True,
                      bbox=[210, top+40, 380, top+80]),
            TableCell(row_idx=1, col_idx=2, text="2024", column_header=True,
                      bbox=[380, top+40, 550, top+80]),
        ])
        table.num_rows += 1
        table.bbox[3] += 40
    return doc


def test_automatic_cut_row_waits_for_the_complete_spanned_header(tmp_path):
    doc = spanned_header_example(tmp_path)
    frozen = [[c.model_dump() for c in p.tables[0].cells] for p in doc.pages]
    out = DocumentExporter.execute(doc, tmp_path / "out", assets_mode="none")
    extraction = json.loads((out / "extraction.json").read_text(encoding="utf-8"))
    document = json.loads((out / "document.json").read_text(encoding="utf-8"))
    group, = document["table_stitch"]["logical_tables"]
    projection = group["projection"]
    assert projection["boundaries"] == [{"kind": "SPLIT_ROW", "repeated_header_rows": 2,
                                         "join_columns": [0, 1, 2]}]
    assert projection["observed_source_cells"] == 20
    assert [[c.model_dump() for c in p.tables[0].cells] for p in doc.pages] == frozen
    assert validate_contract_pair(extraction, document) == []
    for name in ("result.md", "document.md"):
        text = (out / name).read_text(encoding="utf-8")
        assert text.count("2025") == 1 and text.count("2024") == 1
        assert "Khoản đầu tư vào<br>công ty liên kết" in text
        assert text.count("(020)") == 1
    html = (out / group["html_path"]).read_text(encoding="utf-8")
    assert 'rowspan="2"' in html and 'colspan="2"' in html
    assert (out / "result.txt").read_text(encoding="utf-8").count("(020)") == 1


@pytest.mark.parametrize("fault", ["data_role", "unknown_role", "different_period", "missing_cell", "overlap"])
def test_spanned_header_must_not_hide_data_or_missing_period_evidence(tmp_path, fault):
    doc = spanned_header_example(tmp_path)
    table = doc.pages[1].tables[0]
    label = next(c for c in table.cells if c.row_idx == 0 and c.col_idx == 0)
    year = next(c for c in table.cells if c.row_idx == 1 and c.col_idx == 2)
    if fault == "data_role":
        label.column_header = False
    elif fault == "unknown_role":
        label.column_header = None
    elif fault == "different_period":
        year.text = "2023"
    elif fault == "missing_cell":
        table.cells.remove(year)
    else:
        table.cells.append(TableCell(row_idx=1, col_idx=0, text="Khác", column_header=True,
                                     bbox=[40, table.bbox[1]+40, 210, table.bbox[1]+80]))
    out = DocumentExporter.execute(doc, tmp_path / "out", assets_mode="none")
    document = json.loads((out / "document.json").read_text(encoding="utf-8"))
    assert document["table_stitch"]["logical_tables"] == []
    assert document["table_stitch"]["decisions"][0]["reason"] == "exact_repeated_header_required"
    plain = (out / "result.txt").read_text(encoding="utf-8")
    assert "(020)" in plain and "công ty liên kết" in plain


def test_different_observed_table_orientations_require_review(tmp_path):
    from ocr_document.contract_schema import validate_contract_set
    doc = example(tmp_path, split=True)
    doc.pages[0].tables[0].provenance["table_orientation"] = "rot_0"
    doc.pages[1].tables[0].provenance["table_orientation"] = "rot_180"
    out = DocumentExporter.execute(doc, tmp_path / "out", assets_mode="none")
    document = json.loads((out / "document.json").read_text(encoding="utf-8"))
    assert not document["table_stitch"]["logical_tables"]
    assert document["table_stitch"]["decisions"][0]["reason"] == "table_orientation_differs_or_unavailable"
    extraction = json.loads((out / "extraction.json").read_text(encoding="utf-8"))
    structure = json.loads((out / "structure.json").read_text(encoding="utf-8"))
    document["tables"][1]["table_orientation"] = "rot_0"
    assert any("orientation differs" in error for error in validate_contract_set(extraction, document, structure))


def test_plain_companion_validation_rejects_tampering_but_accepts_legacy_absence(tmp_path):
    from ocr_document.validation import validate_document
    doc = example(tmp_path, split=True)
    out = DocumentExporter.execute(doc, tmp_path / "out", assets_mode="none")
    path = out / "result.txt"
    original = path.read_text(encoding="utf-8")
    path.write_text(original + "\n999", encoding="utf-8")
    report = validate_document(out, skip_groups=True)
    assert any("result.txt differs" in error for error in report["errors"])
    path.unlink()
    assert validate_document(out, skip_groups=True)["status"] != "FAIL"
