"""Two-sheet per-document layout adapted from upstream commit b910247a.

Summary and rich citations follow VuTuanAn1403/OCR_pdf's keyword_exporter;
counts and source locations come from the canonical report, never a recount.
"""
from io import BytesIO
import json
from pathlib import Path

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from ocr_contracts.keyword import KeywordReport
from ocr_artifacts.atomic_io import atomic_write_bytes

try:
    from openpyxl.cell.rich_text import CellRichText, TextBlock
    from openpyxl.cell.text import InlineFont
except ImportError:
    CellRichText = None

SHEETS = ("Tong_hop", "Trich_dan_chi_tiet")
CITATION_HEADERS = ("STT", "Tên từ khóa", "Thuộc trang số", "Trích dẫn")
WORKBOOK_SCHEMA = "keyword-workbook-two-sheets-v1"


def ordered_citations(report):
    order = {}
    for index, keyword in enumerate(report.keywords):
        order.setdefault(keyword.keyword.casefold(), index)
    return sorted(report.citations, key=lambda c: (order.get(c.keyword.casefold(), len(order)),
                  c.page_numbers[0] if c.page_numbers else 2**31, c.match_start))


def citation_text(citation):
    return " ".join(part for part in (citation.citation_before, citation.citation_keyword, citation.citation_after) if part)


def citation_page(citation):
    return citation.page_number if citation.page_number is not None else (", ".join(map(str, citation.page_numbers)) or None)


def _text(sheet, row, col, value):
    cell = sheet.cell(row, col, value)
    cell.data_type = "s"  # Treat formula-like names, keywords and quotes literally.
    return cell


def _header(sheet, values):
    border = Border(bottom=Side(style="thin", color="C7D5E0"))
    for col, value in enumerate(values, 1):
        cell = _text(sheet, 1, col, value)
        cell.font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E79")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border


def _write_citation(cell, citation):
    if len(citation_text(citation)) > 32767:
        raise ValueError("Citation exceeds Excel cell text capacity; refusing silent truncation")
    if CellRichText is None or not citation.citation_keyword:
        cell.value = citation_text(citation)
    else:
        parts = []
        if citation.citation_before:
            parts.append(citation.citation_before + " ")
        parts.append(TextBlock(InlineFont(b=True), citation.citation_keyword))
        if citation.citation_after:
            parts.append(" " + citation.citation_after)
        cell.value = CellRichText(*parts)
    cell.data_type = "s"
    cell.alignment = Alignment(wrap_text=True, vertical="top")


class KeywordExporter:
    @staticmethod
    def export_excel(report: KeywordReport, output_dir: Path, *, metadata=None) -> Path:
        return KeywordExporter.export_file_excel(report, Path(output_dir) / "count_keywords.xlsx", metadata=metadata)

    @staticmethod
    def export_file_excel(report: KeywordReport, output_file: Path, *, metadata=None) -> Path:
        if len(report.keywords) > 16383 or len(report.citations) > 1048575:
            raise ValueError("Keyword workbook exceeds Excel row/column capacity")
        workbook = Workbook()
        try:
            sheet = workbook.active
            sheet.title = SHEETS[0]
            _header(sheet, ["File_name", *(k.keyword for k in report.keywords)])
            _text(sheet, 2, 1, report.document_id)
            for column, keyword in enumerate(report.keywords, 2):
                sheet.cell(2, column, keyword.count).number_format = "#,##0"
                sheet.cell(2, column).alignment = Alignment(horizontal="center")
                sheet.column_dimensions[get_column_letter(column)].width = min(24, max(12, len(keyword.keyword) + 2))
            sheet.column_dimensions["A"].width = min(65, max(28, len(report.document_id) + 4))
            sheet.row_dimensions[1].height = 65
            sheet.freeze_panes = "B2"
            citations = workbook.create_sheet(SHEETS[1])
            _header(citations, CITATION_HEADERS)
            for column, width in enumerate((8, 34, 18, 100), 1):
                citations.column_dimensions[get_column_letter(column)].width = width
            for number, citation in enumerate(ordered_citations(report), 1):
                row = number + 1
                citations.cell(row, 1, number)
                _text(citations, row, 2, citation.keyword)
                page = citation_page(citation)
                cell = citations.cell(row, 3, page)
                if isinstance(page, str):
                    cell.data_type = "s"
                cell.alignment = Alignment(horizontal="center")
                if not citation.page_numbers:
                    cell.comment = Comment("Nguồn chưa đủ để xác định trang vật lý.", "OCR PDF")
                elif len(citation.page_numbers) > 1:
                    cell.comment = Comment("Các trang nguồn của bảng ghép; cần rà vị trí cụ thể.", "OCR PDF")
                _write_citation(citations.cell(row, 4), citation)
                citations.row_dimensions[row].height = 45
            citations.freeze_panes = "A2"
            if metadata is not None:
                workbook.properties.description = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
            workbook.properties.creator = "OCR PDF"
            buffer = BytesIO()
            workbook.save(buffer)
            path = Path(output_file)
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(path, buffer.getvalue())
            return path
        finally:
            workbook.close()
