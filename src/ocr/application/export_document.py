import json
from pathlib import Path
from typing import Dict, Any, Optional
import pymupdf

from src.ocr.domain.models.document import ExtractedDocument
from src.ocr.infrastructure.export.markdown_exporter import MarkdownExporter
from src.ocr.infrastructure.export.json_exporter import JSONExporter
from src.ocr.infrastructure.export.manifest_exporter import ManifestExporter
from src.ocr.infrastructure.export.artifact_validator import validate_document_artifacts

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
        accuracy_data: Optional[Dict[str, Any]] = None
    ) -> Path:
        doc_dir = output_dir / doc.document_id
        pages_dir = doc_dir / "pages"
        pages_dir.mkdir(parents=True, exist_ok=True)

        image_pages = {
            p.page_num: MarkdownExporter.image_regions_to_preserve(p)
            for p in doc.pages
        }
        if any(image_pages.values()):
            images_dir = doc_dir / "images"
            images_dir.mkdir(parents=True, exist_ok=True)
            with pymupdf.open(doc.file_path) as source_pdf:
                for p in doc.pages:
                    source_page = source_pdf[p.page_num - 1]
                    for region in image_pages[p.page_num]:
                        clip = source_page.rect & pymupdf.Rect(*region.bbox.to_list())
                        if clip.is_empty:
                            continue
                        name = MarkdownExporter.image_asset_name(p.page_num, region)
                        try:
                            pix = source_page.get_pixmap(dpi=180, clip=clip, alpha=False)
                            pix.save(images_dir / name)
                            del pix
                        except Exception:
                            import gc
                            gc.collect()
                            try:
                                pix = source_page.get_pixmap(dpi=96, clip=clip, alpha=False)
                                pix.save(images_dir / name)
                                del pix
                            except Exception:
                                pass

        # Detect repeated running headers and footers across pages (Proposal A2)
        cls._detect_running_headers_and_footers(doc)

        # 1. Export per-page artifacts (suppress running headers/footers in Markdown by default)
        for p in doc.pages:
            # Preserve lossless structure separately while keeping the user's
            # existing pipe-only Markdown contract.
            for table in p.tables:
                if table.engine == "docling_tableformer":
                    structure_dir = doc_dir / "structures" / "tables"
                    structure_dir.mkdir(parents=True, exist_ok=True)
                    html_path = structure_dir / f"{table.table_id}.html"
                    html_path.write_text(table.provenance.get("html") or table.to_html(), encoding="utf-8")
                    table.provenance["html_artifact"] = html_path.relative_to(doc_dir).as_posix()
            for formula in p.formulas:
                structure_dir = doc_dir / "structures" / "formulas"
                structure_dir.mkdir(parents=True, exist_ok=True)
                latex_path = structure_dir / f"{formula.formula_id}.tex"
                latex_path.write_text(formula.latex, encoding="utf-8")
                formula.provenance["latex_artifact"] = latex_path.relative_to(doc_dir).as_posix()
            p.markdown_content = MarkdownExporter.export_page_markdown(p, include_running_headers_footers=False)
            p_json_path = pages_dir / f"page-{p.page_num:04d}.json"
            p_md_path = pages_dir / f"page-{p.page_num:04d}.md"

            JSONExporter.save_json(JSONExporter.export_page_json(p), p_json_path)
            with open(p_md_path, "w", encoding="utf-8") as f:
                f.write(p.markdown_content)

            validation = p.metadata.get("validation_cascade")
            if validation is not None:
                p_val_path = pages_dir / f"page-{p.page_num:04d}-validation.json"
                JSONExporter.save_json(validation, p_val_path)

        # 2. Export full result.md (suppress running headers/footers in Markdown by default)
        full_md = MarkdownExporter.export_document_markdown(doc, include_running_headers_footers=False)
        doc.full_markdown = full_md
        with open(doc_dir / "result.md", "w", encoding="utf-8") as f:
            f.write(full_md)

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

        validation = validate_document_artifacts(doc_dir)
        JSONExporter.save_json(validation, doc_dir / "validation.json")
        if validation["status"] == "FAIL":
            raise ValueError(f"Artifact validation failed: {validation['errors'][:3]}")

        return doc_dir

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
            return " ".join(t.split())

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

