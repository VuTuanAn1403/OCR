"""Recognized display formulas with explicit, unverified model provenance."""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class Formula(BaseModel):
    formula_id: str
    page: int
    latex: str
    bbox: List[float] = Field(default_factory=list)
    engine: str = "docling_codeformula"
    confidence: Optional[float] = None
    status: str = "NEEDS_REVIEW"
    provenance: Dict[str, Any] = Field(default_factory=dict)

    def to_markdown(self) -> str:
        return "$$\n" + self.latex.strip() + "\n$$"
