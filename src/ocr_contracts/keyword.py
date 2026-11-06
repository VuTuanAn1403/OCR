"""Exact keyword frequency reports, adapted from OCR_pdf_backup."""
from pydantic import BaseModel, Field


class KeywordCitation(BaseModel):
    keyword_id: str = ""
    keyword: str
    page_number: int | None = None
    page_numbers: list[int] = Field(default_factory=list)
    page_status: str = "UNRESOLVED_PAGE"
    match_start: int = 0
    match_end: int = 0
    citation_before: str = ""
    citation_keyword: str = ""
    citation_after: str = ""


class KeywordCount(BaseModel):
    keyword: str
    exact_count: int = 0
    count: int = 0


class KeywordReport(BaseModel):
    document_id: str
    source_file: str
    keywords: list[KeywordCount] = Field(default_factory=list)
    citations: list[KeywordCitation] = Field(default_factory=list)
    total_keywords_searched: int = 0
    total_exact_matches: int = 0
    total_matches: int = 0
