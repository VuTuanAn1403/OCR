import gc
import hashlib
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional
import pymupdf

from src.ocr.domain.models.document import ExtractedDocument
from src.ocr.infrastructure.export.markdown_exporter import ASSET_MODES, MarkdownExporter
from src.ocr.infrastructure.export.json_exporter import JSONExporter
from src.ocr.infrastructure.export.artifact_validator import validate_document_artifacts
from src.ocr.infrastructure.export.completion import clear_completed
from src.ocr.infrastructure.export.document_contracts import write_document_contracts
from src.ocr.infrastructure.export.output_contract import OUTPUT_CONTRACT_VERSION, V6_ARTIFACTS, OUTPUT_MODES
from src.ocr.runtime.atomic_io import atomic_write_bytes, atomic_write_text

logger = logging.getLogger(__name__)

_JPEG_QUALITY = 85


class ExportDocumentUseCase:
    """
    Exports ExtractedDocument to the target directory following Section 17 Output contract.
    """
    @classmethod
    def execute(
        cls,
        doc: ExtractedDocument,
        output_dir: Path,
        benchmark_data: Optional[Dict[str, Any]] = None,
        accuracy_data: Optional[Dict[str, Any]] = None,
        assets_mode: str = "png",
        output_mode: str = "legacy",
    ) -> Path:
        if assets_mode not in ASSET_MODES:
            raise ValueError(f"Unknown assets_mode '{assets_mode}'. Use one of: {', '.join(ASSET_MODES)}")
        if output_mode not in OUTPUT_MODES:
            raise ValueError(f"Unknown output_mode {output_mode!r}. Use one of: {', '.join(OUTPUT_MODES)}")
        doc_dir = output_dir / doc.document_id
        pages_dir = doc_dir / "pages"
        pages_dir.mkdir(parents=True, exist_ok=True)
        # The directory is about to be rewritten; an old marker would claim
        # completion of a partially rewritten output.
        clear_completed(doc_dir)
        doc.manifest["assets_mode"] = assets_mode
        doc.manifest["output_mode"] = output_mode
        doc.manifest["output_contract"] = {
            "schema_version": OUTPUT_CONTRACT_VERSION,
            "required_artifacts": list(V6_ARTIFACTS),
        }

        cls._export_image_assets(doc, doc_dir, assets_mode)

        # Detect repeated running headers and footers across pages (Proposal A2)
        cls._detect_running_headers_and_footers(doc)

        # 1. Export per-page artifacts (suppress running headers/footers in Markdown by default)
        for p in doc.pages:
            # Preserve lossless structure separately while keeping the user's
            # existing pipe-only Markdown contract.
            for table in p.tables:
                if table.engine == "docling_tableformer":
                    html_path = doc_dir / "structures" / "tables" / f"{table.table_id}.html"
                    # Rendered from the cells, which may have been refilled from
                    # native/OCR text after TableFormer ran (C3.5e). Docling's
                    # own HTML stays in provenance["html"] for reference.
                    atomic_write_text(html_path, table.to_html())
                    table.provenance["html_artifact"] = html_path.relative_to(doc_dir).as_posix()
                    table.provenance["html_artifact_source"] = "cells"
            for formula in p.formulas:
                latex_path = doc_dir / "structures" / "formulas" / f"{formula.formula_id}.tex"
                atomic_write_text(latex_path, formula.latex)
                formula.provenance["latex_artifact"] = latex_path.relative_to(doc_dir).as_posix()
            p.markdown_content = MarkdownExporter.export_page_markdown(
                p, include_running_headers_footers=False, assets_mode=assets_mode)
            p_json_path = pages_dir / f"page-{p.page_num:04d}.json"
            p_md_path = pages_dir / f"page-{p.page_num:04d}.md"

            JSONExporter.save_json(JSONExporter.export_page_json(p), p_json_path)
            atomic_write_text(p_md_path, p.markdown_content)

            validation = p.metadata.get("validation_cascade")
            if validation is not None:
                p_val_path = pages_dir / f"page-{p.page_num:04d}-validation.json"
                JSONExporter.save_json(validation, p_val_path)

        # 2. Export full result.md (suppress running headers/footers in Markdown by default)
        full_md = MarkdownExporter.export_document_markdown(
            doc, include_running_headers_footers=False, assets_mode=assets_mode)
        doc.full_markdown = full_md
        atomic_write_text(doc_dir / "result.md", full_md)

        # 3. Export result.json
        JSONExporter.save_json(JSONExporter.export_document_json(doc), doc_dir / "result.json")

        # 4. Export quality.json
        JSONExporter.save_json(doc.quality.model_dump(mode="json"), doc_dir / "quality.json")

        # 5. Export manifest.json
        JSONExporter.save_json(doc.manifest, doc_dir / "manifest.json")

        # 6. Export benchmark.json if provided
        if benchmark_data:
            JSONExporter.save_json(benchmark_data, doc_dir / "benchmark.json")

        # 7. Export accuracy.json if provided
        if accuracy_data:
            JSONExporter.save_json(accuracy_data, doc_dir / "accuracy.json")

        # 8. V6 document-level contracts (C2.4, C3.7). Additive: the files above
        # keep their format (D3); this step only reads `doc`.
        write_document_contracts(doc, doc_dir, assets_mode)
        markdown_path = doc_dir / "document.md"
        if markdown_path.is_file():
            doc.manifest["output_contract"]["markdown_sha256"] = hashlib.sha256(markdown_path.read_bytes()).hexdigest()
        JSONExporter.save_json(doc.manifest, doc_dir / "manifest.json")

        validation = validate_document_artifacts(doc_dir)
        JSONExporter.save_json(validation, doc_dir / "validation.json")
        if validation["status"] == "FAIL":
            cause = _structure_error(doc_dir)
            raise ValueError(f"Artifact validation failed: {validation['errors'][:3]}"
                             + (f"; structure step error: {cause}" if cause else ""))

        return doc_dir

    @staticmethod
    def _export_image_assets(doc: ExtractedDocument, doc_dir: Path, assets_mode: str) -> None:
        """Write crops of preserved image regions and record each region's
        `asset` path. With assets_mode "none" nothing is written (ENV-10)."""
        image_pages = {p.page_num: MarkdownExporter.image_regions_to_preserve(p) for p in doc.pages}
        for regions in image_pages.values():
            for region in regions:
                region.asset = None
        if assets_mode == "none" or not any(image_pages.values()):
            return
        images_dir = doc_dir / "images"
        output = "jpeg" if assets_mode == "jpeg" else "png"
        with pymupdf.open(doc.file_path) as source_pdf:
            for p in doc.pages:
                source_page = source_pdf[p.page_num - 1]
                for region in image_pages[p.page_num]:
                    clip = source_page.rect & pymupdf.Rect(*region.bbox.to_list())
                    if clip.is_empty:
                        continue
                    name = MarkdownExporter.image_asset_name(p.page_num, region, assets_mode)
                    if _save_crop(source_page, clip, images_dir / name, output):
                        region.asset = f"images/{name}"
                    else:
                        # The validator reports the missing file as an error.
                        logger.warning("Page %d: could not export image region %s", p.page_num, region.region_id)

    @classmethod
    def _detect_running_headers_and_footers(cls, doc: ExtractedDocument) -> None:
        """
        Detects repeated header and footer strings across distinct pages (>= 30% distinct page frequency).
        Marks matching blocks as running_header or running_footer (Proposal A2 / Review V5 Item 9).
        Enforces distinct page counting, position verification, and math.ceil rounding.
        """
        total_pages = len(doc.pages)
        if total_pages < 3:
            return

        import unicodedata
        import re
        import math
        from collections import defaultdict

        def _norm(text: str) -> str:
            t = unicodedata.normalize("NFC", text.strip().lower())
            t = re.sub(r"\d+", "", t)
            t = re.sub(r"[^\w\s]", "", t)
            # Whitespace-free key: letter-spaced variants such as
            # "BÁO CÁ O THƯỜNG NIÊN" must match the same running header (H6).
            return "".join(t.split())

        # Count DISTINCT pages where header or footer appears
        header_pages: Dict[str, set] = defaultdict(set)
        footer_pages: Dict[str, set] = defaultdict(set)

        for p in doc.pages:
            p_h = float(getattr(p, "height", 0) or 0)
            for b in p.blocks:
                if b.block_type == "formula":
                    continue
                norm_str = _norm(b.text)
                if not norm_str or len(norm_str) < 4:
                    continue

                b_ymid = ((b.bbox[1] + b.bbox[3]) / 2.0) if (b.bbox and len(b.bbox) >= 4) else None

                # Position checks: Header within top 15%, Footer within bottom 15%
                if b.block_type == "header":
                    if p_h <= 0 or b_ymid is None or b_ymid <= 0.15 * p_h:
                        header_pages[norm_str].add(p.page_num)
                elif b.block_type == "footer":
                    if p_h <= 0 or b_ymid is None or b_ymid >= 0.85 * p_h:
                        footer_pages[norm_str].add(p.page_num)

        # Threshold using math.ceil(total_pages * 0.30)
        min_distinct_pages = max(2, math.ceil(total_pages * 0.30))
        running_headers = {k for k, p_set in header_pages.items() if len(p_set) >= min_distinct_pages}
        running_footers = {k for k, p_set in footer_pages.items() if len(p_set) >= min_distinct_pages}

        for p in doc.pages:
            p_h = float(getattr(p, "height", 0) or 0)
            for b in p.blocks:
                norm_str = _norm(b.text)
                b_ymid = ((b.bbox[1] + b.bbox[3]) / 2.0) if (b.bbox and len(b.bbox) >= 4) else None
                if b.block_type == "header" and norm_str in running_headers:
                    if p_h <= 0 or b_ymid is None or b_ymid <= 0.15 * p_h:
                        b.block_type = "running_header"
                elif b.block_type == "footer" and norm_str in running_footers:
                    if p_h <= 0 or b_ymid is None or b_ymid >= 0.85 * p_h:
                        b.block_type = "running_footer"


def _save_crop(page: pymupdf.Page, clip: pymupdf.Rect, path: Path, output: str) -> bool:
    """Render a page crop atomically; retry at lower DPI on memory pressure."""
    for dpi in (180, 96):
        try:
            pix = page.get_pixmap(dpi=dpi, clip=clip, alpha=False)
            data = pix.tobytes(output=output, jpg_quality=_JPEG_QUALITY)
            del pix
            atomic_write_bytes(path, data)
            return True
        except Exception as exc:  # MuPDF raises several unrelated error types
            logger.warning("Rendering %s at %d DPI failed: %s", path.name, dpi, exc)
            gc.collect()
    return False


def _structure_error(doc_dir: Path) -> Optional[str]:
    """The recorded structure-step failure, if any, so a validation error
    caused by it names the real exception."""
    try:
        return json.loads((doc_dir / "structure.json").read_text(encoding="utf-8")).get("error")
    except (OSError, ValueError, AttributeError):
        return None
