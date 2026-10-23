"""Legacy document export: the document exporter plus keyword counting.

`DocumentExporter` (document_export.py) writes and validates the document
artifacts and never counts keywords. This subclass keeps the historical API,
where `count_keywords=True` (the default) runs the standalone legacy counter
afterwards. V6.3 exports with `DocumentExporter` and counts in the document
owner, behind the batch publication gate.
"""
from pathlib import Path
from typing import Any, Dict, Optional

from src.ocr.application.document_export import DocumentExporter
from src.ocr.domain.models.document import ExtractedDocument


class ExportDocumentUseCase(DocumentExporter):
    @classmethod
    def execute(
        cls,
        doc: ExtractedDocument,
        output_dir: Path,
        benchmark_data: Optional[Dict[str, Any]] = None,
        accuracy_data: Optional[Dict[str, Any]] = None,
        assets_mode: str = "png",
        output_mode: str = "legacy",
        document_layout: Optional[Dict[str, Any]] = None,
        keywords_file: Optional[str] = None,
        count_keywords: bool = True,
    ) -> Path:
        doc_dir = super().execute(doc, output_dir, benchmark_data, accuracy_data, assets_mode,
                                  output_mode, document_layout)
        if count_keywords:
            from src.ocr.application.count_keywords import CountKeywordsUseCase
            CountKeywordsUseCase.execute(doc_dir, doc.document_id, keywords_file)
        return doc_dir
