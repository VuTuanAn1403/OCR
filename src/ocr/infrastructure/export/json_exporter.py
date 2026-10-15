from pathlib import Path
from typing import Dict, Any
from src.ocr.domain.models.document import ExtractedDocument
from src.ocr.domain.models.page import ExtractedPage
from src.ocr.runtime.atomic_io import atomic_write_json
from src.ocr.infrastructure.export.output_contract import OUTPUT_MODES, RESULT_INDEX_SCHEMA

class JSONExporter:
    """
    Exports ExtractedDocument and ExtractedPage to JSON format adhering to the project contract.
    """
    @classmethod
    def export_page_json(cls, page: ExtractedPage) -> Dict[str, Any]:
        return {
            "page_num": page.page_num,
            "width": page.width,
            "height": page.height,
            "page_type": page.page_type.value,
            "rendered_dpi": page.rendered_dpi,
            "blocks": [b.to_dict() for b in page.blocks],
            "tables": [t.model_dump(mode="json") for t in page.tables],
            "formulas": [f.model_dump(mode="json") for f in page.formulas],
            "diagrams": [d.model_dump(mode="json") for d in page.diagrams],
            "regions": [r.model_dump(mode="json") for r in page.regions],
            "evidence_blocks": [e.model_dump(mode="json") for e in page.evidence_blocks],
            "quality": page.quality.model_dump(mode="json"),
            "metadata": page.metadata
        }

    @classmethod
    def export_document_json(cls, doc: ExtractedDocument) -> Dict[str, Any]:
        mode = doc.manifest.get("output_mode", "legacy")
        if mode not in OUTPUT_MODES:
            raise ValueError(f"Unknown output_mode {mode!r}")
        data = {
            "document_id": doc.document_id,
            "file_path": doc.file_path,
            "file_hash": doc.file_hash,
            "total_pages": doc.total_pages,
            "selected_pages": doc.selected_pages,
            "profile": doc.profile,
            "quality": doc.quality.model_dump(mode="json"),
            "manifest": doc.manifest,
        }
        if mode == "compact":
            data.update(schema_version=RESULT_INDEX_SCHEMA, page_refs=[
                {"page_num": p.page_num, "path": f"pages/page-{p.page_num:04d}.json"} for p in doc.pages])
        else:
            data["pages"] = [cls.export_page_json(p) for p in doc.pages]
        return data

    @classmethod
    def save_json(cls, data: Any, output_file: Path) -> None:
        atomic_write_json(Path(output_file), data)
