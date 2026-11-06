"""Workbook read-back checks for the new per-document export contract."""
import openpyxl
import pytest

from ocr_keywords.contract import count_report, dictionary_snapshot
from ocr_reporting.workbooks import export_document, verify_document


def workbook(tmp_path):
    keys = tmp_path / "keys.txt"
    keys.write_text("=SUM(A1:A2)\nhọc máy\nmissing\n", encoding="utf-8")
    snapshot = dictionary_snapshot(keys, "test-export")
    text = tmp_path / "result.md"
    text.write_text("# Trang 1\n=SUM(A1:A2) học máy", encoding="utf-8")
    report = count_report("=malicious-name", None, text, snapshot, [1])
    export_document(report, snapshot, tmp_path)
    return tmp_path / "count_keywords.xlsx", report, snapshot


def test_exactly_two_sheets_zero_counts_and_rich_literal_quotes(tmp_path):
    path, report, snapshot = workbook(tmp_path)
    book = openpyxl.load_workbook(path, rich_text=True)
    try:
        summary, details = book.worksheets
        assert book.sheetnames == ["Tong_hop", "Trich_dan_chi_tiet"]
        assert summary["A2"].data_type == summary["B1"].data_type == "s"
        assert summary["D2"].value == 0
        assert details.max_row == 3 and details["C2"].value == 1
        assert str(details["D2"].value).startswith("# Trang 1 =SUM(A1:A2)")
        assert details["D2"].data_type == "s"
        assert any(getattr(getattr(part, "font", None), "b", False) for part in details["D2"].value)
    finally:
        book.close()
    verify_document(path, report, snapshot)


@pytest.mark.parametrize("change", ["bold", "page", "page_bool", "ordinal_bool", "keyword_formula", "text", "extra", "missing_sheet", "summary"])
def test_readback_rejects_changed_sheet_content_or_bold(tmp_path, change):
    path, report, snapshot = workbook(tmp_path)
    book = openpyxl.load_workbook(path, rich_text=True)
    if change == "bold":
        cell = book.worksheets[1]["D2"]
        cell.value = str(cell.value)
    elif change == "page":
        book.worksheets[1]["C2"] = 99
    elif change == "page_bool":
        book.worksheets[1]["C2"] = True
    elif change == "ordinal_bool":
        book.worksheets[1]["A2"] = True
    elif change == "keyword_formula":
        book.worksheets[1]["B2"].data_type = "f"
    elif change == "text":
        book.worksheets[1]["D2"] = "invented"
    elif change == "extra":
        book.worksheets[1].append([99, "học máy", 1, "invented"])
    elif change == "missing_sheet":
        book.remove(book.worksheets[1])
    else:
        book.active["D2"] = 1
    book.save(path)
    book.close()
    with pytest.raises(ValueError):
        verify_document(path, report, snapshot)


def test_legacy_single_sheet_is_only_accepted_for_reports_without_citation_schema(tmp_path):
    path, report, snapshot = workbook(tmp_path)
    legacy = {key: value for key, value in report.items()
              if key not in ("citation_schema_version", "citation_context", "citations")}
    book = openpyxl.Workbook()
    book.active.title = "Thống kê từ khóa"
    for number, (keyword, count) in enumerate(zip(snapshot["display_columns"], report["display_counts"]), 1):
        book.active.cell(number + 4, 1, number)
        book.active.cell(number + 4, 2, keyword).data_type = "s"
        book.active.cell(number + 4, 3, count)
    book.save(path)
    verify_document(path, legacy, snapshot)
    with pytest.raises(ValueError, match="two declared"):
        verify_document(path, report, snapshot)
    book.active["C5"] = 99
    book.save(path)
    book.close()
    with pytest.raises(ValueError, match="legacy Excel"):
        verify_document(path, legacy, snapshot)
