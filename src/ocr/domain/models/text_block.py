from typing import List, Optional, Literal
from pydantic import BaseModel, Field

class TextBlock(BaseModel):
    text: str
    text_raw: Optional[str] = None
    correction_source: Optional[str] = None
    source: Literal["native", "primary_ocr", "fallback_ocr", "image_ocr", "vector", "docling"] = "primary_ocr"
    page: int
    bbox: List[float] = Field(default_factory=list)  # [x0, y0, x1, y1]
    # None = the producing model gives no calibrated confidence (see confidence_source).
    confidence: Optional[float] = 1.0
    quality_score: Optional[float] = 1.0
    confidence_source: Optional[str] = None  # e.g. recognizer, native_text_score, unavailable
    reviewed: bool = False
    block_type: str = "paragraph"  # paragraph, title, section_header, header, footer, page_number, list_item, table_cell, caption, formula
    line_index: int = 0
    column_index: int = 0
    font_size: Optional[float] = None
    is_bold: Optional[bool] = None
    engine: str = "vietnamese_seq2seq"
    fallback: bool = False
    fallback_reason: Optional[str] = None
    region_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "text_raw": self.text_raw if self.text_raw is not None else self.text,
            "text_corrected": self.text,
            "correction_source": self.correction_source,
            "block_type": self.block_type,
            "source": self.source,
            "engine": self.engine,
            "page": self.page,
            "bbox": self.bbox,
            "confidence": None if self.confidence is None else round(self.confidence, 4),
            "quality_score": None if self.quality_score is None else round(self.quality_score, 4),
            "confidence_source": self.confidence_source,
            "reviewed": self.reviewed,
            "fallback": self.fallback,
            "fallback_reason": self.fallback_reason,
            "region_id": self.region_id,
            "font_size": self.font_size,
            "is_bold": self.is_bold,
            "line_index": self.line_index,
            "column_index": self.column_index,
        }
