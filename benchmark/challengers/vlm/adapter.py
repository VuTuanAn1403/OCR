"""VLM fallback adapter: canonical page_text predictions beside, never over, the product text.

* Input is the rendered page image of a selected page (``selection.select_pages``).
* The backend's string is stored unchanged as ``text_raw`` of a challenger record
  (``ocr-v8-challenger-prediction-v1``, layer ``page_text``). The product extraction is
  read for provenance hashes only and never written.
* Every record carries ``review_required: true`` and the selection reasons; a VLM
  string is a hypothesis for a reviewer, not a correction (V8-090 gate).
* A backend failure is a ``MISSING_OUTPUT`` record: the page stays in the denominator.
* A VLM gives no calibrated score, so ``confidence`` is null with a reason.
"""
from __future__ import annotations

import hashlib
from typing import Callable, Dict, Iterable, List, Protocol

from benchmark.challengers.canonical import SCHEMA, validate_prediction

PROMPT_V1 = ("Transcribe all text on this Vietnamese annual-report page exactly as printed, "
             "line by line, keeping every diacritic, digit, sign and separator. Do not translate, "
             "summarise or correct. Write tables row by row with cells separated by ' | '.")
PROMPT_VI_V1 = ("Chép lại nguyên văn toàn bộ chữ trong ảnh trang báo cáo này theo từng dòng, giữ đúng dấu tiếng Việt, "
                "chữ số, dấu và ký hiệu. Không dịch, không tóm tắt, không sửa. Bảng ghi từng hàng, các ô cách nhau bằng ' | '.")
PROMPTS = {"en": PROMPT_V1, "vi": PROMPT_VI_V1}


class VlmBackend(Protocol):
    engine: str
    model_version: str

    def transcribe(self, image_png: bytes, prompt: str) -> str:
        """Return the model's raw text for one page image."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def page_record(document_id: str, page: int, size, image_png: bytes, backend: VlmBackend, run_id: str,
                reasons: List[str], product_text: str, prompt: str = PROMPT_V1) -> Dict:
    base = {"schema_version": SCHEMA, "document_id": document_id, "physical_page": page, "region_id": "page",
            "engine": backend.engine, "model_version": backend.model_version, "run_id": run_id,
            "bbox": [0.0, 0.0, float(size[0]), float(size[1])], "coordinate_space": "pdf_points",
            "source_image_sha256": sha256(image_png), "confidence": None,
            "confidence_reason": "the VLM returns no calibrated score",
            "review_required": True, "selection_reasons": list(reasons),
            "prompt_sha256": sha256(prompt.encode("utf-8")),
            "product_text_sha256": sha256(product_text.encode("utf-8"))}
    try:
        text = backend.transcribe(image_png, prompt)
    except Exception as error:  # noqa: BLE001 - every failure must stay a MISSING_OUTPUT unit
        return {**base, "status": "MISSING_OUTPUT", "text_raw": None, "error": f"{type(error).__name__}: {error}"}
    if not isinstance(text, str):
        return {**base, "status": "MISSING_OUTPUT", "text_raw": None, "error": "backend returned no string"}
    return {**base, "status": "PREDICTED", "text_raw": text}


def run(document_id: str, selected: Iterable[Dict], render: Callable[[int], tuple], product_text: Callable[[int], str],
        backend: VlmBackend, run_id: str, prompt: str = PROMPT_V1) -> List[Dict]:
    """Records for the selected pages only; each record is checked against the canonical contract."""
    records = []
    for entry in selected:
        image_png, size = render(entry["page"])
        record = page_record(document_id, entry["page"], size, image_png, backend, run_id, entry["reasons"],
                             product_text(entry["page"]), prompt)
        problems = validate_prediction(record, "page_text")
        if problems:
            raise ValueError(f"page {entry['page']}: non-canonical record: {problems}")
        records.append(record)
    return records
