"""Model-free document fixtures shared by CPU pipeline/analysis tests."""
from ocr_contracts.document import ExtractedDocument
from ocr_contracts.evidence_block import EvidenceBlock
from ocr_contracts.page import ExtractedPage
from ocr_contracts.page_type import PageType
from ocr_contracts.quality import DocumentQualityReport, PageQualityReport
from ocr_contracts.region import BoundingBox, ContentType, Region
from ocr_contracts.text_block import TextBlock


def make_doc(pages):
    for n, blocks in enumerate(pages, 1):
        for b in blocks:
            b.region_id = f"r{n}"
    extracted = [ExtractedPage(page_num=n, width=600, height=842, blocks=blocks,
        evidence_blocks=[EvidenceBlock(page=n, block_id=f"p{n}b{i}", text=b.text, bbox=b.bbox,
                                      source="native", orientation=0, region_id=f"r{n}") for i, b in enumerate(blocks)],
        regions=[Region(region_id=f"r{n}", bbox=BoundingBox(x0=0, y0=0, x1=600, y1=842),
                        content_type=ContentType.TEXT, status="EXTRACTED", orientation_status="CONFIDENT")],
        page_type=PageType.NATIVE_TEXT, quality=PageQualityReport(page=n, page_type="NATIVE_TEXT"))
        for n, blocks in enumerate(pages, 1)]
    return ExtractedDocument(document_id="furniture-v3", file_path="unused.pdf", file_hash="0123456789abcdef",
        total_pages=len(pages), selected_pages=list(range(1, len(pages)+1)), pages=extracted,
        manifest={"document_id": "furniture-v3", "file_hash": "0123456789abcdef",
                  "selected_pages": list(range(1, len(pages)+1))},
        quality=DocumentQualityReport(document_id="furniture-v3", total_pages=len(pages)))


def block(text, n, y=25, **kwargs):
    return TextBlock(text=text, page=n, bbox=[40, y, 500, y+14], **kwargs)
