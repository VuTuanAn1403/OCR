"""Versioned C3.7 JSON Schemas and semantic source checks.

The same Pydantic models generate Draft 2020-12 JSON Schema and validate the
contracts without an extra runtime dependency. Cross-file references, page
ownership and tree consistency require the additional pair validation below.
Additive fields are allowed for backward-compatible schema evolution.
"""
from __future__ import annotations

from typing import Annotated, Any, Dict, List, Literal, Optional

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError, model_validator


def _valid_bbox(box: List[float]) -> List[float]:
    if box[2] < box[0] or box[3] < box[1]:
        raise ValueError("bbox has reversed coordinates")
    return box


Coordinate = Annotated[float, Field(allow_inf_nan=False)]
BBox = Annotated[List[Coordinate], Field(min_length=4, max_length=4), AfterValidator(_valid_bbox)]
ElementId = Annotated[str, Field(pattern=r"^[^:\s]+:p\d{4}:[btfi]\d{4}$")]
SectionId = Annotated[str, Field(pattern=r"^[^:\s]+:s\d{4}$")]
PageNumber = Annotated[int, Field(ge=1)]
Confidence = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)


class Span(ContractModel):
    page: PageNumber
    bbox: BBox
    block_ids: Annotated[List[ElementId], Field(min_length=1)]


class TextProvenance(ContractModel):
    text_raw: str
    text_corrected: str
    correction_source: Optional[str]
    source: Annotated[str, Field(min_length=1)]
    device: Annotated[str, Field(min_length=1)]
    confidence: Optional[Confidence]
    confidence_source: Annotated[str, Field(min_length=1)]

    @model_validator(mode="after")
    def truthful_provenance(self):
        if self.confidence is None and self.confidence_source != "unavailable":
            raise ValueError("null confidence requires confidence_source=unavailable")
        if self.text_raw != self.text_corrected and not self.correction_source:
            raise ValueError("changed text requires correction_source")
        return self


class Cell(TextProvenance):
    row: Annotated[int, Field(ge=0)]
    col: Annotated[int, Field(ge=0)]
    row_span: Annotated[int, Field(ge=1)]
    col_span: Annotated[int, Field(ge=1)]
    bbox: BBox
    bbox_source: Literal["cell", "table_fallback"]
    spans: Annotated[List[Span], Field(min_length=1)]


class ExtractionItem(TextProvenance):
    id: ElementId
    kind: Literal["b", "t", "f", "i"]
    bbox: BBox
    cells: List[Cell] = Field(default_factory=list)


class ExtractionPage(ContractModel):
    page: PageNumber
    width: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    height: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    page_type: str
    coordinate_space: Literal["pdf_points_top_left", "pdf_points_top_left_rotated"]
    transforms: List[Dict[str, Any]]
    items: List[ExtractionItem]


class ExtractionContract(ContractModel):
    schema_version: Literal["extraction-v1"]
    doc_id: str
    doc_sha16: str
    pipeline_version: str
    profile: str
    total_pages: Annotated[int, Field(ge=0)]
    pages: List[ExtractionPage]


class DocumentSection(ContractModel):
    section_id: SectionId
    level: Annotated[int, Field(ge=0, le=4)]
    title: str
    title_en: Optional[str]
    parent_id: Optional[SectionId]
    page_start: Optional[PageNumber]
    page_end: Optional[PageNumber]
    heading_item_ids: List[ElementId]
    spans: List[Span]
    chunk_ids: List[ElementId]


class Chunk(TextProvenance):
    chunk_id: ElementId
    section_id: SectionId
    type: Literal["paragraph", "list_item", "table", "formula", "image"]
    lang: Literal["vi", "en", "unknown"]
    spans: Annotated[List[Span], Field(min_length=1)]
    needs_review: bool


class DocumentTable(ContractModel):
    table_id: ElementId
    chunk_id: ElementId
    section_id: SectionId
    pages: Annotated[List[PageNumber], Field(min_length=1)]
    num_rows: Annotated[int, Field(ge=0)]
    num_cols: Annotated[int, Field(ge=0)]
    has_merged_cells: bool
    engine: str
    html_path: Optional[str]
    cells: List[Cell]


class DocumentFormula(ContractModel):
    formula_id: ElementId
    chunk_id: ElementId
    section_id: SectionId


class DocumentImage(ContractModel):
    image_id: ElementId
    chunk_id: ElementId
    section_id: SectionId
    asset: Optional[str]


class DocumentContract(ContractModel):
    schema_version: Literal["doc-v1"]
    doc_id: str
    doc_sha16: str
    source: Dict[str, Any]
    extraction: Literal["extraction.json"]
    sections: List[DocumentSection]
    chunks: List[Chunk]
    tables: List[DocumentTable]
    formulas: List[DocumentFormula]
    images: List[DocumentImage]


def contract_json_schemas() -> Dict[str, Dict[str, Any]]:
    """Return portable JSON Schemas with explicit dialect and version IDs."""
    result = {}
    for name, model in (("extraction-v1", ExtractionContract), ("doc-v1", DocumentContract)):
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"urn:ocr-pdf:{name}"
        result[name] = schema
    return result


def validate_contract_pair(extraction: Dict[str, Any], document: Dict[str, Any]) -> List[str]:
    """Return structural/schema/source errors, suitable for the artifact validator."""
    errors: List[str] = []
    parsed = []
    for name, model, payload in (("extraction.json", ExtractionContract, extraction),
                                 ("document.json", DocumentContract, document)):
        try:
            parsed.append(model.model_validate(payload))
        except ValidationError as exc:
            errors.extend(f"{name} {'.'.join(str(p) for p in e['loc'])}: {e['msg']}"
                          for e in exc.errors(include_url=False, include_input=False))
    if errors:
        return errors
    source, doc = parsed
    if (source.doc_id, source.doc_sha16) != (doc.doc_id, doc.doc_sha16):
        errors.append("document.json identity differs from extraction.json")

    known = {}
    page_numbers = set()
    for page in source.pages:
        if page.page in page_numbers:
            errors.append(f"extraction.json duplicate page {page.page}")
        page_numbers.add(page.page)
        for item in page.items:
            if item.id in known:
                errors.append(f"extraction.json duplicate element id {item.id}")
            known[item.id] = (page.page, item)
            if not item.id.startswith(f"{source.doc_sha16}:p{page.page:04d}:{item.kind}"):
                errors.append(f"extraction.json {item.id} does not belong to its document/page/kind")

    def check_spans(spans: List[Span], where: str, file_name: str = "document.json") -> None:
        for span in spans:
            if span.page not in page_numbers:
                errors.append(f"{file_name} {where} references unknown page {span.page}")
            for ref in span.block_ids:
                if ref not in known:
                    errors.append(f"{file_name} {where} references unknown id {ref}")
                elif known[ref][0] != span.page:
                    errors.append(f"{file_name} {where} id {ref} is on a different page than its span")

    for page in source.pages:
        for item in page.items:
            for cell in item.cells:
                check_spans(cell.spans, f"cell {item.id} {cell.row},{cell.col}", "extraction.json")
                if any(ref != item.id for span in cell.spans for ref in span.block_ids):
                    errors.append(f"extraction.json table {item.id} cell does not reference its owning table")

    sections = {s.section_id: s for s in doc.sections}
    if len(sections) != len(doc.sections):
        errors.append("document.json duplicate section ids")
    chunks = {c.chunk_id: c for c in doc.chunks}
    if len(chunks) != len(doc.chunks):
        errors.append("document.json duplicate chunk ids")
    for section in doc.sections:
        if not section.section_id.startswith(f"{doc.doc_sha16}:s"):
            errors.append(f"document.json section {section.section_id} belongs to a different document")
        parent = sections.get(section.parent_id)
        if section.parent_id and (parent is None or parent.level >= section.level):
            errors.append(f"document.json section {section.section_id} has an invalid parent")
        if section.page_start is not None and (section.page_end is None or section.page_end < section.page_start):
            errors.append(f"document.json section {section.section_id} has an invalid page range")
        refs = [ref for span in section.spans for ref in span.block_ids]
        if set(refs) != set(section.heading_item_ids):
            errors.append(f"document.json section {section.section_id} heading spans differ from heading_item_ids")
        check_spans(section.spans, f"section {section.section_id}")
        for ref in section.chunk_ids:
            if ref not in chunks or chunks[ref].section_id != section.section_id:
                errors.append(f"document.json section {section.section_id} has an invalid chunk id {ref}")
    for chunk in doc.chunks:
        section = sections.get(chunk.section_id)
        if section is None or section.chunk_ids.count(chunk.chunk_id) != 1:
            errors.append(f"document.json chunk {chunk.chunk_id} is outside the section tree")
        check_spans(chunk.spans, f"chunk {chunk.chunk_id}")
        if chunk.chunk_id != chunk.spans[0].block_ids[0]:
            errors.append(f"document.json chunk {chunk.chunk_id} does not use its first source id")
        allowed = {"paragraph": {"b"}, "list_item": {"b"}, "table": {"t"},
                   "formula": {"b", "f"}, "image": {"i"}}[chunk.type]
        if any(ref in known and known[ref][1].kind not in allowed
               for span in chunk.spans for ref in span.block_ids):
            errors.append(f"document.json chunk {chunk.chunk_id} references the wrong element kind")
    for collection, field in ((doc.tables, "table_id"), (doc.formulas, "formula_id"), (doc.images, "image_id")):
        for entry in collection:
            ref = getattr(entry, field)
            chunk = chunks.get(entry.chunk_id)
            if ref not in known:
                errors.append(f"document.json {field} references unknown id {ref}")
            if chunk is None or chunk.section_id != entry.section_id or ref != entry.chunk_id:
                errors.append(f"document.json {field} {ref} has an invalid chunk reference")
            expected_type = {"table_id": "table", "formula_id": "formula", "image_id": "image"}[field]
            if chunk and chunk.type != expected_type:
                errors.append(f"document.json {field} {ref} references a chunk of the wrong type")
    for table in doc.tables:
        chunk = chunks.get(table.chunk_id)
        owning_sources = ({ref for span in chunk.spans for ref in span.block_ids}
                          if chunk and chunk.type == "table" else {table.table_id})
        if chunk and (chunk.type != "table" or set(table.pages) != {span.page for span in chunk.spans}):
            errors.append(f"document.json table {table.table_id} pages/type differ from its chunk")
        for cell in table.cells:
            check_spans(cell.spans, f"table {table.table_id} cell {cell.row},{cell.col}")
            if any(ref not in owning_sources for span in cell.spans for ref in span.block_ids):
                errors.append(f"document.json table {table.table_id} cell does not reference its owning table")
            if any(span.page not in table.pages for span in cell.spans):
                errors.append(f"document.json table {table.table_id} cell page is outside table pages")
            if cell.row + cell.row_span > table.num_rows or cell.col + cell.col_span > table.num_cols:
                errors.append(f"document.json table {table.table_id} cell is outside table dimensions")
    return errors
