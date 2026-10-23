from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from ocr_contracts.text_block import TextBlock
from ocr_contracts.table import TableStructure
from ocr_contracts.quality import PageQualityReport
from ocr_contracts.region import Region
from ocr_contracts.evidence_block import EvidenceBlock
from ocr_contracts.diagram import DiagramStructure
from ocr_contracts.formula import Formula
from ocr_contracts.page_type import PageType

class ExtractedPage(BaseModel):
    page_num: int
    width: float
    height: float
    page_type: PageType
    rendered_dpi: Optional[int] = None
    blocks: List[TextBlock] = Field(default_factory=list)
    tables: List[TableStructure] = Field(default_factory=list)
    formulas: List[Formula] = Field(default_factory=list)
    diagrams: List[DiagramStructure] = Field(default_factory=list)
    regions: List[Region] = Field(default_factory=list)  # V3.1.2 Content Composition
    evidence_blocks: List[EvidenceBlock] = Field(default_factory=list)  # V3.1.2 Intermediate Repr
    raw_text: str = ""
    markdown_content: str = ""
    quality: PageQualityReport
    metadata: Dict[str, Any] = Field(default_factory=dict)
