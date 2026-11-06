from typing import Any, List, Optional, Literal
from pydantic import Field, model_serializer
from ocr_contracts.confidence import ConfidenceModel
from ocr_contracts.region import ContentType


class EvidenceBlock(ConfidenceModel):
    """
    V3.1.2 Evidence-Preserving intermediate representation (spec §3).

    Markdown is only generated AFTER EvidenceBlocks are complete.
    Each block carries its provenance (source, confidence, content_type)
    so the merge/reading-order stage can make informed decisions.
    """
    page: int
    block_id: str = ""
    region_id: Optional[str] = None
    bbox: List[float] = Field(default_factory=list)  # [x0, y0, x1, y1]
    bbox_original: List[float] = Field(default_factory=list)
    bbox_normalized: List[float] = Field(default_factory=list)
    text: str = ""
    text_raw: Optional[str] = None
    recognition_provenance: dict[str, Any] = Field(default_factory=dict)
    content_type: ContentType = ContentType.TEXT
    source: Literal["native", "ocr", "vector", "image"] = "native"
    orientation: Optional[float] = None
    rotation: float = 0.0
    column_id: Optional[int] = None
    table_id: Optional[str] = None
    image_id: Optional[str] = None
    reading_order: int = -1
    parent_region: Optional[str] = None
    transform_matrix: List[float] = Field(default_factory=list)
    status: str = "UNRESOLVED"
    failure_reason: Optional[str] = None
    quality_score: Optional[float] = None
    block_type: str = "paragraph"
    is_bold: Optional[bool] = None
    font_size: Optional[float] = None

    @model_serializer(mode="wrap")
    def _serialize_optional_recognition_evidence(self, handler):
        data = super().serialize_confidence(handler)
        if self.text_raw is None:
            data.pop("text_raw", None)
        if not self.recognition_provenance:
            data.pop("recognition_provenance", None)
        return data
