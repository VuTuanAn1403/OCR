from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from ocr_contracts.region import BoundingBox, Region
from ocr_contracts.text_block import TextBlock
from ocr_contracts.table import TableStructure
from ocr_contracts.diagram import DiagramStructure
from ocr_contracts.page_type import PageType

class LogicalSubPage(BaseModel):
    """
    V4.0 Subpage Isolation:
    Represents an independently partitioned subpage (e.g. left or right half of a Two-Up page).
    """
    parent_page_num: int
    subpage_idx: int                  # 0 for left, 1 for right
    bbox: BoundingBox
    logical_page_num: Optional[int] = None   # Page number printed on footer (e.g. 20, 21)
    page_type: PageType = PageType.NATIVE_TEXT
    regions: List[Region] = Field(default_factory=list)
    blocks: List[TextBlock] = Field(default_factory=list)
    tables: List[TableStructure] = Field(default_factory=list)
    diagrams: List[DiagramStructure] = Field(default_factory=list)
    markdown_content: str = ""
    native_score: float = 1.0
