from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

class PageAccuracyReport(BaseModel):
    page: int
    # MEASURED, or MISSING_OUTPUT: ground truth exists but the system produced
    # no page, scored as maximum error (proposal 9.1).
    status: str = "MEASURED"
    cer: float = 0.0
    wer: float = 0.0
    diacritic_accuracy: float = 1.0
    table_accuracy: Optional[float] = None
    reading_order_accuracy: float = 1.0
    ref_char_count: int = 0
    pred_char_count: int = 0
    ref_word_count: int = 0
    pred_word_count: int = 0

class AccuracyReport(BaseModel):
    document_id: str
    mean_cer: float = 0.0
    mean_wer: float = 0.0
    mean_diacritic_accuracy: float = 1.0
    mean_table_accuracy: Optional[float] = None
    mean_reading_order_accuracy: float = 1.0
    pages_evaluated: int = 0
    # NOT_EVALUATED when no ground truth applies; the mean_* defaults above
    # are then placeholders, not measurements (proposal 9.1).
    evaluation_status: str = "NOT_EVALUATED"
    pages_missing_output: int = 0
    # Ground-truth pages outside the selected pages of this run.
    pages_not_evaluated: List[int] = Field(default_factory=list)
    # Micro averages, total edit errors / total reference length (9.2 primary).
    micro_cer: Optional[float] = None
    micro_wer: Optional[float] = None
    page_reports: Dict[int, PageAccuracyReport] = Field(default_factory=dict)
