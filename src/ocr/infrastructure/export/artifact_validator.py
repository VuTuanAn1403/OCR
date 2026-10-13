"""Validate the PDF-to-Markdown artifact contract after export."""

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List

from src.ocr.domain.models.table import TableStructure
from src.ocr.domain.models.region import Region
from src.ocr.infrastructure.export.markdown_exporter import ASSET_MODES, MarkdownExporter


_IMAGE_LINK = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
_PIPE_SEPARATOR = re.compile(r"^\|(?:\s*:?-{3,}:?\s*\|)+\s*$")
_HTML_TABLE = re.compile(r"</?(?:table|thead|tbody|tr|td|th)\b", re.IGNORECASE)


def validate_document_artifacts(
    doc_dir: Path, ground_truth_manifest: Path | None = None
) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    counts = {
        "formulas_json": 0,
        "pages_json": 0,
        "pages_markdown": 0,
        "tables_json": 0,
        "pipe_tables_markdown": 0,
        "table_candidates_as_paragraphs": 0,
        "image_links": 0,
        "broken_image_links": 0,
        "evidence_blocks": 0,
        "review_required_lines": 0,
        "large_unread_image_regions": 0,
        "ground_truth_cases": 0,
    }
    root = doc_dir.resolve()
    page_files = sorted(
        path for path in (doc_dir / "pages").glob("page-*.json")
        if re.fullmatch(r"page-\d{4}\.json", path.name)
    )
    manifest_path = doc_dir / "manifest.json"
    assets_mode = "png"
    if not manifest_path.is_file():
        errors.append("manifest.json is missing")
        expected_pages = []
    else:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected_pages = manifest.get("selected_pages") or []
        # Outputs written before --assets existed always exported PNG files.
        assets_mode = manifest.get("assets_mode", "png")
        if assets_mode not in ASSET_MODES:
            errors.append(f"manifest.json has unknown assets_mode {assets_mode!r}")
        if len(page_files) != len(expected_pages):
            errors.append(
                f"Page JSON count {len(page_files)} differs from selected pages {len(expected_pages)}"
            )
        found_pages = [int(path.stem.split("-")[1]) for path in page_files]
        if sorted(found_pages) != sorted(expected_pages):
            errors.append(f"Page numbers {found_pages} differ from selected pages {expected_pages}")

    markdown_files: List[Path] = []
    result_path = doc_dir / "result.md"
    result_markdown = ""
    if result_path.is_file():
        markdown_files.append(result_path)
        result_markdown = result_path.read_text(encoding="utf-8")
    else:
        errors.append("result.md is missing")
    # V6 document-level Markdown gets the same table/image checks (C3.7).
    if (doc_dir / "document.md").is_file():
        markdown_files.append(doc_dir / "document.md")

    for json_path in page_files:
        counts["pages_json"] += 1
        page_data = json.loads(json_path.read_text(encoding="utf-8"))
        page_num = page_data.get("page_num")
        if page_num != int(json_path.stem.split("-")[1]):
            errors.append(f"{json_path.name}: page_num {page_num} does not match filename")
        markdown_path = json_path.with_suffix(".md")
        if not markdown_path.is_file():
            errors.append(f"Page {page_num}: Markdown is missing")
            continue
        counts["pages_markdown"] += 1
        markdown_files.append(markdown_path)
        markdown = markdown_path.read_text(encoding="utf-8")
        separator_count = sum(bool(_PIPE_SEPARATOR.fullmatch(line)) for line in markdown.splitlines())
        counts["pipe_tables_markdown"] += separator_count
        if "```mermaid" in markdown:
            source_text = " ".join(str(block.get("text", "")) for block in page_data.get("blocks") or []).casefold()
            if not any(title in source_text for title in (
                "mô hình tổ chức", "sơ đồ tổ chức", "cơ cấu tổ chức", "sơ đồ bộ máy",
            )):
                warnings.append(
                    f"Page {page_num}: Mermaid diagram has no explicit title in extracted source text; inspect for false diagram"
                )

        expected_tables = 0
        for table_data in page_data.get("tables") or []:
            counts["tables_json"] += 1
            table = TableStructure.model_validate(table_data)
            if table.needs_review:
                warnings.append(f"Page {page_num}: table {table.table_id} requires independent review")
            rendered = table.to_markdown(format="pipe")
            if table.cells and not rendered:
                errors.append(f"Page {page_num}: table {table.table_id} lost all cell content")
            elif rendered and rendered not in markdown:
                errors.append(f"Page {page_num}: table {table.table_id} is missing from Markdown")
            normalized_rendered = re.sub(
                r"\s+", " ", unicodedata.normalize("NFC", rendered.replace("\\|", "|"))
            ).casefold()
            for cell in table.cells:
                cell_text = re.sub(r"<br\s*/?>", " ", cell.text, flags=re.IGNORECASE)
                normalized_cell = re.sub(
                    r"\s+", " ", unicodedata.normalize("NFC", cell_text)
                ).strip().casefold()
                if normalized_cell and normalized_cell not in normalized_rendered:
                    errors.append(
                        f"Page {page_num}: table {table.table_id} lost cell ({cell.row_idx}, {cell.col_idx})"
                    )
            if any(_PIPE_SEPARATOR.fullmatch(line) for line in rendered.splitlines()):
                expected_tables += 1
            elif rendered:
                counts["table_candidates_as_paragraphs"] += 1
                warnings.append(
                    f"Page {page_num}: table candidate {table.table_id} rendered as paragraphs"
                )
            rows: dict[int, dict[int, str]] = {}
            for cell in table.cells:
                rows.setdefault(cell.row_idx, {})[cell.col_idx] = cell.text.strip()
            for row_number in sorted(rows)[:-1]:
                current = rows[row_number]
                following = rows.get(row_number + 1, {})
                current_numeric = sum(bool(re.search(r"\d{3,}", text)) for col, text in current.items() if col > 0)
                following_numeric = sum(bool(re.search(r"\d{3,}", text)) for col, text in following.items() if col > 0)
                if (len(current.get(0, "")) >= 18 and current_numeric == 0
                        and following_numeric >= 2 and len(following.get(0, "")) < 40):
                    warnings.append(
                        f"Page {page_num}: table {table.table_id} may split a row label from numeric cells"
                    )
        if separator_count != expected_tables:
            errors.append(
                f"Page {page_num}: {separator_count} Pipe Tables, expected {expected_tables}"
            )

        for formula in page_data.get("formulas") or []:
            counts["formulas_json"] += 1
            latex = str(formula.get("latex", "")).strip()
            rendered_formula = "$$\n" + latex + "\n$$"
            if not latex or rendered_formula not in markdown:
                errors.append(f"Page {page_num}: formula {formula.get('formula_id')} is missing from Markdown")
            if latex and rendered_formula not in result_markdown:
                errors.append(f"Page {page_num}: formula {formula.get('formula_id')} is missing from result.md")
            if formula.get("status") != "VALIDATED":
                warnings.append(f"Page {page_num}: formula {formula.get('formula_id')} requires independent review")

        backend = page_data.get("metadata", {}).get("docling_structure", {})
        if backend.get("status") == "FAILED_FALLBACK":
            warnings.append(f"Page {page_num}: Docling unavailable or failed; heuristic fallback used")
        elif backend.get("status") == "partial_success" or backend.get("errors"):
            warnings.append(f"Page {page_num}: Docling returned a partial result or conversion errors")

        regions = page_data.get("regions") or []
        region_ids = {region.get("region_id") for region in regions}
        evidence_blocks = page_data.get("evidence_blocks") or []
        if len(evidence_blocks) < len(page_data.get("blocks") or []):
            errors.append(f"Page {page_num}: evidence count differs from text block count")
        for region in regions:
            if not region.get("status"):
                errors.append(f"Page {page_num}: region {region.get('region_id')} has no status")
            if region.get("orientation_status") == "UNKNOWN":
                warnings.append(f"Page {page_num}: region {region.get('region_id')} orientation unknown")
            if region.get("status") == "NEEDS_REVIEW" or region.get("needs_fallback"):
                warnings.append(
                    f"Page {page_num}: region {region.get('region_id')} needs review: {region.get('failure_reason')}"
                )
            bbox = region.get("bbox") or {}
            page_w = float(page_data.get("width", 0) or 0)
            page_h = float(page_data.get("height", 0) or 0)
            page_area = page_w * page_h
            rx0 = float(bbox.get("x0", 0))
            ry0 = float(bbox.get("y0", 0))
            rx1 = float(bbox.get("x1", 0))
            ry1 = float(bbox.get("y1", 0))
            # Regions completely outside visible page boundary have no source pixels and are not preserved
            if (
                rx1 <= 0 or ry1 <= 0
                or (page_w > 0 and rx0 >= page_w)
                or (page_h > 0 and ry0 >= page_h)
            ):
                continue
            image_area = max(0.0, rx1 - rx0) * max(0.0, ry1 - ry0)
            if (region.get("status") == "PRESERVED"
                    and region.get("content_type") in ("IMAGE", "IMAGE_TABLE", "FIGURE")
                    and page_area > 0 and image_area / page_area >= 0.25):
                counts["large_unread_image_regions"] += 1
                warnings.append(
                    f"Page {page_num}: large image {region.get('region_id')} was preserved without OCR text; inspect for silent content loss"
                )
            if (
                region.get("content_type") in ("IMAGE", "IMAGE_TABLE", "FIGURE")
                and (region.get("status") == "PRESERVED"
                     or (page_area > 0 and image_area / page_area >= 0.20))
            ):
                region_id = region.get("region_id")
                if assets_mode == "none":
                    if region.get("asset") is not None:
                        errors.append(f"Page {page_num}: region {region_id} has an asset although assets_mode is none")
                    if MarkdownExporter.image_omitted_marker(region_id) not in markdown:
                        errors.append(f"Page {page_num}: preserved region {region_id} has no omitted-image note")
                    continue
                asset_name = MarkdownExporter.image_asset_name(
                    page_num, Region.model_validate(region), assets_mode
                )
                if f"../images/{asset_name}" not in markdown:
                    errors.append(f"Page {page_num}: preserved region {region_id} has no Markdown image")
                if not (doc_dir / "images" / asset_name).is_file():
                    errors.append(f"Page {page_num}: preserved region {region_id} has no {assets_mode.upper()} asset")
        for evidence in evidence_blocks:
            counts["evidence_blocks"] += 1
            block_id = evidence.get("block_id")
            if not evidence.get("region_id") or evidence.get("region_id") not in region_ids:
                errors.append(f"Page {page_num}: evidence {block_id} has no valid region")
            if evidence.get("orientation") is None:
                errors.append(f"Page {page_num}: evidence {block_id} has no orientation")
            if not evidence.get("status"):
                errors.append(f"Page {page_num}: evidence {block_id} has no status")

        quality = page_data.get("quality") or {}
        counts["review_required_lines"] += quality.get("review_required_count") or 0
        if quality.get("content_status") in ("IMAGE_PRESERVED_NO_TEXT", "UNRESOLVED_NO_CONTENT"):
            warnings.append(f"Page {page_num}: {quality.get('content_status')}")

    for markdown_path in markdown_files:
        markdown = markdown_path.read_text(encoding="utf-8")
        if any(char in markdown for char in "┌┬┐├┼┤└┴┘"):
            errors.append(f"{markdown_path.relative_to(doc_dir)} contains box drawing tables")
        if _HTML_TABLE.search(markdown):
            errors.append(f"{markdown_path.relative_to(doc_dir)} contains HTML table tags")
        for image_path in _IMAGE_LINK.findall(markdown):
            counts["image_links"] += 1
            target = (markdown_path.parent / image_path).resolve()
            if not target.is_relative_to(root) or not target.is_file():
                counts["broken_image_links"] += 1
                errors.append(f"{markdown_path.relative_to(doc_dir)} has broken image {image_path}")

    _validate_document_contracts(doc_dir, errors, warnings, counts)

    if counts["review_required_lines"]:
        warnings.append(f"{counts['review_required_lines']} OCR lines require review")
    if ground_truth_manifest is not None:
        from benchmark.accuracy_first import evaluate_case

        reference = json.loads(Path(ground_truth_manifest).read_text(encoding="utf-8"))
        for case in reference.get("cases", []):
            if Path(case["pdf"]).stem != doc_dir.name or case["page"] not in expected_pages:
                continue
            counts["ground_truth_cases"] += 1
            measured = evaluate_case(case, doc_dir.parent)
            page_num = case["page"]
            if not measured["prediction_exists"]:
                errors.append(f"Page {page_num}: ground truth page output is missing")
                continue
            if measured["orientation_correct"] is False:
                errors.append(f"Page {page_num}: orientation differs from ground truth")
            if measured["missing_anchors"]:
                errors.append(
                    f"Page {page_num}: visible text missing from image: {measured['missing_anchors']}"
                )
            if measured["missing_numeric_values"]:
                errors.append(
                    f"Page {page_num}: numeric values differ from ground truth: {measured['missing_numeric_values']}"
                )
            if measured["table_cell_f1"] is not None and measured["table_cell_f1"] < 0.95:
                errors.append(f"Page {page_num}: table cell association F1 {measured['table_cell_f1']:.2f} < 0.95")
            if (measured["reading_order_accuracy"] is not None
                    and measured["reading_order_accuracy"] < 1.0):
                errors.append(
                    f"Page {page_num}: reading order disagrees with ground truth"
                )
    status = "FAIL" if errors else "NEEDS_REVIEW" if warnings else "PASS"
    return {"status": status, "counts": counts, "errors": errors, "warnings": warnings}


# `{doc_sha16}:p{page:04d}:{kind}{n:04d}`; the document part is not checked
# for hex so synthetic fixtures with short hashes stay valid.
_ELEMENT_ID = re.compile(r"^[^:\s]+:p\d{4}:[btfi]\d{4}$")


def _validate_document_contracts(doc_dir: Path, errors: List[str], warnings: List[str],
                                 counts: Dict[str, Any]) -> None:
    """C3.7: every id that document.json uses must exist in extraction.json.
    Outputs written before V6 have no document.json and are skipped."""
    document_path = doc_dir / "document.json"
    extraction_path = doc_dir / "extraction.json"
    if not document_path.is_file():
        if extraction_path.is_file():
            from src.ocr.infrastructure.export.contract_schema import ExtractionContract
            try:
                extraction = json.loads(extraction_path.read_text(encoding="utf-8"))
                ExtractionContract.model_validate(extraction)
            except (OSError, ValueError, TypeError) as exc:
                errors.append(f"extraction.json is invalid: {exc}")
                return
            warnings.append("V6 structure is incomplete: extraction.json exists but document.json is missing")
        return
    if not extraction_path.is_file():
        errors.append("document.json exists but extraction.json is missing")
        return
    try:
        extraction = json.loads(extraction_path.read_text(encoding="utf-8"))
        document = json.loads(document_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        errors.append(f"V6 contracts cannot be read: {exc}")
        return
    from src.ocr.infrastructure.export.contract_schema import validate_contract_pair
    contract_errors = validate_contract_pair(extraction, document)
    if contract_errors:
        errors.extend(contract_errors)
        return
    ids = [item["id"] for page in extraction.get("pages", []) for item in page.get("items", [])]
    known = set(ids)
    if len(known) != len(ids):
        errors.append("extraction.json has duplicate element ids")
    malformed = [i for i in ids if not _ELEMENT_ID.match(i)]
    if malformed:
        errors.append(f"extraction.json has malformed ids, e.g. {malformed[0]}")

    def check(ref: str, where: str) -> None:
        if ref not in known:
            errors.append(f"document.json {where} references unknown id {ref}")

    sections = {s["section_id"] for s in document.get("sections", [])}
    chunk_ids = [c["chunk_id"] for c in document.get("chunks", [])]
    if len(set(chunk_ids)) != len(chunk_ids):
        errors.append("document.json has duplicate chunk ids")
    for section in document.get("sections", []):
        for ref in section.get("heading_item_ids", []):
            check(ref, f"section {section['section_id']}")
    for chunk in document.get("chunks", []):
        if chunk.get("section_id") not in sections:
            errors.append(f"chunk {chunk['chunk_id']} is outside the section tree")
        if not chunk.get("spans"):
            errors.append(f"chunk {chunk['chunk_id']} has no spans")
        for span in chunk.get("spans", []):
            for ref in span.get("block_ids", []):
                check(ref, f"chunk {chunk['chunk_id']}")
    for key, field in (("tables", "table_id"), ("formulas", "formula_id"), ("images", "image_id")):
        for entry in document.get(key, []):
            check(entry[field], key)
    counts["structure_sections"] = len(sections)
    counts["structure_chunks"] = len(chunk_ids)
    review = sum(1 for chunk in document.get("chunks", []) if chunk.get("needs_review"))
    if review:
        warnings.append(f"{review} document chunks need review")
