import pytest
from src.ocr.domain.models.document import ExtractedDocument
from src.ocr.domain.models.page import ExtractedPage
from src.ocr.domain.models.text_block import TextBlock
from src.ocr.domain.models.quality import PageQualityReport, DocumentQualityReport
from src.ocr.domain.routing.page_type import PageType
from src.ocr.application.export_document import ExportDocumentUseCase
from src.ocr.infrastructure.export.markdown_exporter import MarkdownExporter


def _make_page(page_num: int, height: float = 1000.0, blocks=None) -> ExtractedPage:
    return ExtractedPage(
        page_num=page_num,
        width=800.0,
        height=height,
        page_type=PageType.NATIVE_TEXT,
        blocks=blocks or [],
        quality=PageQualityReport(
            page=page_num,
            page_type="NATIVE_TEXT",
            time_taken_seconds=0.01,
        )
    )


def test_repeated_blocks_on_single_page_not_running_header():
    """
    Review Item 9: Probe 3 identical blocks on 1 page of a 10-page document
    must NOT be marked as running_header.
    """
    # 10 pages total
    pages = [_make_page(i) for i in range(1, 11)]

    # Page 1 has 3 identical header blocks in top margin
    pages[0].blocks = [
        TextBlock(text="BÁO CÁO THƯỜNG NIÊN", block_type="header", bbox=[50, 20, 200, 40], page=1),
        TextBlock(text="BÁO CÁO THƯỜNG NIÊN", block_type="header", bbox=[50, 45, 200, 65], page=1),
        TextBlock(text="BÁO CÁO THƯỜNG NIÊN", block_type="header", bbox=[50, 70, 200, 90], page=1),
    ]

    doc = ExtractedDocument(
        document_id="doc10",
        file_path="dummy.pdf",
        file_hash="hash10",
        total_pages=10,
        pages=pages,
        quality=DocumentQualityReport(document_id="doc10", total_pages=10),
    )

    ExportDocumentUseCase._detect_running_headers_and_footers(doc)

    # All 3 blocks on page 1 must remain "header", NOT "running_header"
    for b in pages[0].blocks:
        assert b.block_type == "header", f"Block falsely marked as {b.block_type}"


def test_repeated_blocks_across_distinct_pages_marked_running_header():
    """
    If header appears across >= 30% distinct pages in top 15%, it is marked running_header.
    """
    pages = [_make_page(i) for i in range(1, 11)]

    # Header appears on pages 1, 2, 3, 4 (40% >= ceil(10 * 0.3) = 3)
    for p_idx in [0, 1, 2, 3]:
        pages[p_idx].blocks.append(
            TextBlock(text="TẬP ĐOÀN ĐIỆN LỰC VIỆT NAM", block_type="header", bbox=[50, 20, 300, 40], page=p_idx + 1)
        )

    doc = ExtractedDocument(
        document_id="doc10_running",
        file_path="dummy.pdf",
        file_hash="hash10_running",
        total_pages=10,
        pages=pages,
        quality=DocumentQualityReport(document_id="doc10_running", total_pages=10),
    )

    ExportDocumentUseCase._detect_running_headers_and_footers(doc)

    for p_idx in [0, 1, 2, 3]:
        assert pages[p_idx].blocks[0].block_type == "running_header"


def test_running_headers_footers_hidden_in_markdown_by_default():
    """
    Running header/footer is omitted in Markdown by default (A2 & Item 9),
    while normal headers/footers are retained.
    """
    page = _make_page(1)
    page.blocks = [
        TextBlock(text="HEADER CHÍNH", block_type="header", bbox=[50, 10, 200, 30], page=1),
        TextBlock(text="HEADER LẶP LẠI", block_type="running_header", bbox=[50, 35, 200, 55], page=1),
        TextBlock(text="Nội dung chính trang 1.", block_type="paragraph", bbox=[50, 100, 500, 120], page=1),
        TextBlock(text="FOOTER LẶP LẠI", block_type="running_footer", bbox=[50, 950, 200, 970], page=1),
        TextBlock(text="FOOTER ĐẶC THÙ", block_type="footer", bbox=[50, 975, 200, 995], page=1),
    ]

    # Default: include_running_headers_footers=False
    md_default = MarkdownExporter.export_page_markdown(page, include_running_headers_footers=False)
    assert "HEADER CHÍNH" in md_default
    assert "HEADER LẶP LẠI" not in md_default
    assert "FOOTER LẶP LẠI" not in md_default
    assert "FOOTER ĐẶC THÙ" in md_default
    assert "Nội dung chính trang 1." in md_default

    # Explicit: include_running_headers_footers=True
    md_with_running = MarkdownExporter.export_page_markdown(page, include_running_headers_footers=True)
    assert "HEADER LẶP LẠI" in md_with_running
    assert "FOOTER LẶP LẠI" in md_with_running
