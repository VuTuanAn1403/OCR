from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class QualityMetrics(BaseModel):
    cer: Optional[float] = None
    wer: Optional[float] = None
    mean_confidence: Optional[float] = None
    vietnamese_character_errors: int = 0
    unicode_errors: int = 0
    reading_order_errors: int = 0
    table_structure_errors: int = 0
    primary_lines: int = 0
    fallback_lines: int = 0
    fallback_ratio: float = 0.0

class PageQualityReport(BaseModel):
    page: int
    page_type: str
    native_text_score: float = 0.0
    # None when no recognizer supplied a measured confidence; zero is a real score.
    ocr_confidence: Optional[float] = None
    # None when no block or table on the page carries a measurable score.
    quality_score: Optional[float] = 0.0
    total_blocks: int = 0
    recognized_lines: int = 0
    fallback_count: int = 0
    review_required_count: int = 0
    suspicious_lines: List[str] = Field(default_factory=list)
    time_taken_seconds: float = 0.0
    stage_seconds: Dict[str, float] = Field(default_factory=dict)
    unicode_corruption_detected: bool = False
    native_extraction_failed: bool = False
    orientation_fallback: Optional[str] = None
    vector_table_probe_enabled: bool = False
    # V3.1.2 Content Composition stats
    region_count: int = 0
    region_types: Dict[str, int] = Field(default_factory=dict)  # e.g. {"TEXT": 5, "IMAGE": 2}
    content_status: str = "UNRESOLVED"
    content_reason: Optional[str] = None
    native_quality: Optional[float] = None
    ocr_quality: Optional[float] = None
    low_confidence_line_count: int = 0
    min_region_quality: Optional[float] = None
    ocr_calls: int = 0
    errors: int = 0
    # True when restored from the page cache: time_taken_seconds and
    # stage_seconds then belong to the earlier run that produced it (H24).
    from_cache: bool = False

class DocumentQualityReport(BaseModel):
    document_id: str
    total_pages: int
    mean_native_score: float = 0.0
    mean_ocr_confidence: Optional[float] = None
    mean_quality_score: Optional[float] = 0.0
    pages_processed_native: int = 0
    pages_processed_ocr: int = 0
    pages_processed_mixed: int = 0
    total_fallback_regions: int = 0
    total_time_seconds: float = 0.0
    pages_from_cache: int = 0
    # Model loading measured before the first page (PERF-05).
    startup_seconds: Optional[float] = None
    metrics: QualityMetrics = Field(default_factory=QualityMetrics)
    page_reports: List[PageQualityReport] = Field(default_factory=list)
