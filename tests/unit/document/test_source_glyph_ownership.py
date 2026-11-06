"""Observed bridge glyphs can own a cell without shrinking the frozen source."""
from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace

import pymupdf
import pytest

from ocr_contracts.document import ExtractedDocument
from ocr_contracts.geometry import LINE_ORIENTATION_METHOD, placed_line_bbox
from ocr_contracts.page import ExtractedPage
from ocr_contracts.page_type import PageType
from ocr_contracts.quality import DocumentQualityReport, PageQualityReport
from ocr_contracts.table import TableCell, TableStructure
from ocr_contracts.text_block import TextBlock
from ocr_document.contract_schema import validate_extraction
from ocr_document.document_contracts import build_extraction_json
from ocr_document.ids import page_items
from ocr_document.resolve_document_layout import _reconcile_evidence, resolve_document_layout, GLYPH_RECONCILIATION_METHOD
from ocr_document.source_identity import lock_text_evidence
from ocr_structure.ocr_bridge import ocr_bridge


def page_with_glyph_cell(angle=0, *, text="Nợ (020)", box=None):
    box = box or ([10, 10, 180, 24] if angle in (0, 180) else [10, 10, 24, 180])
    block = TextBlock(text=text, text_raw=text, bbox=box, page=1, confidence=.8,
                      recognition_provenance={"method": LINE_ORIENTATION_METHOD, "rotation_clockwise_degrees": angle})
    page = ExtractedPage(page_num=1, width=400, height=500, page_type=PageType.MIXED,
                         blocks=[block], quality=PageQualityReport(page=1, page_type="mixed"))
    lock_text_evidence(page.blocks, "a" * 16, 1, page.metadata)
    placements = []
    with pymupdf.open() as pdf:
        source = pdf.new_page(width=400, height=500)
        with ocr_bridge(source, page, 72, orientation_placements=placements) as bridge:
            line, = [line for group in bridge[0].get_text("dict")["blocks"] for line in group.get("lines", [])]
            assert placements[0]["placed_text_bbox"] == list(line["bbox"])
    glyph = placements[0]["placed_text_bbox"]
    assert placed_line_bbox(page.metadata["text_evidence"]["items"][0], placements[0]) == glyph
    page.metadata["ocr_structure_bridge"] = {"orientation_placements": placements}
    page.tables = [TableStructure(table_id="table", page=1, bbox=[0, 0, 400, 300], num_rows=1, num_cols=1,
                                  cells=[TableCell(row_idx=0, col_idx=0, text=block.text, bbox=glyph)])]
    page.blocks = []
    return page


@pytest.mark.parametrize("angle", [0, 90, 180, 270])
def test_real_bridge_geometry_owns_exact_cell_and_preserves_frozen_source(angle):
    page = page_with_glyph_cell(angle)
    frozen = deepcopy(page.metadata["text_evidence"])
    _reconcile_evidence(page)
    decision, = page.metadata["source_dispositions"].values()
    assert decision["status"] == "REPLACED_BY_TABLE"
    assert decision["reason"] == "PLACED_GLYPHS_AND_EXACT_TEXT_OCCURRENCE"
    assert page.metadata["source_reconciliation_method"] == GLYPH_RECONCILIATION_METHOD
    assert page.blocks == [] and page.tables[0].cells[0].text == "Nợ (020)"
    assert page.metadata["text_evidence"] == frozen
    _reconcile_evidence(page)
    assert page.blocks == [] and page.metadata["text_evidence"] == frozen


@pytest.mark.parametrize(("field", "value"), [
    ("placed_text_sha256", sha256(b"No (020)").hexdigest()),
    ("bbox", [0, 0, 200, 200]), ("crop_rotation_clockwise_degrees", 180),
    ("placed_text_bbox", [0, 0, 100, 20]), ("placed_text_bbox", [10, 10, float("nan"), 20]),
    ("placement_geometry_method", "unknown"), ("coordinate_space", "pdf_bottom_left"),
])
def test_stale_or_unrelated_placement_cannot_absorb_source(field, value):
    page = page_with_glyph_cell()
    page.metadata["ocr_structure_bridge"]["orientation_placements"][0][field] = value
    _reconcile_evidence(page)
    assert next(iter(page.metadata["source_dispositions"].values()))["status"] == "KEPT_FOR_REVIEW"
    assert page.blocks[0].text_raw == "Nợ (020)" and page.blocks[0].bbox == [10, 10, 180, 24]


@pytest.mark.parametrize("case", ["legacy", "duplicate_placement", "wrong_number", "cross_cell", "protected"])
def test_missing_or_ambiguous_evidence_preserves_review(case):
    page = page_with_glyph_cell()
    records = page.metadata["ocr_structure_bridge"]["orientation_placements"]
    if case == "legacy":
        for key in ("placed_text_bbox", "placed_text_sha256", "placement_geometry_method"):
            records[0].pop(key)
    elif case == "duplicate_placement":
        records.append(deepcopy(records[0]))
    elif case == "wrong_number":
        page.tables[0].cells[0].text = "Nợ (0200)"
    elif case == "protected":
        page.metadata["text_evidence"]["items"][0]["protected_from_furniture"] = True
    else:
        glyph = records[0]["placed_text_bbox"]
        page.tables[0].cells[0].bbox = [glyph[0], glyph[1], (glyph[0] + glyph[2]) / 2, glyph[3]]
    _reconcile_evidence(page)
    assert next(iter(page.metadata["source_dispositions"].values()))["status"] == "KEPT_FOR_REVIEW"
    assert page.blocks[0].text_raw == "Nợ (020)"


def extraction_with_glyph_source():
    page = page_with_glyph_cell()
    doc = ExtractedDocument(document_id="test", file_path="unused.pdf", file_hash="a" * 16, total_pages=1,
                            selected_pages=[1], pages=[page],
                            quality=DocumentQualityReport(document_id="test", total_pages=1))
    resolve_document_layout(doc)
    extraction = build_extraction_json(doc, [page_items(doc.file_hash, page)], "cuda")
    assert validate_extraction(extraction) == []
    return extraction


@pytest.mark.parametrize("case", ["hash", "tokens", "cell_box", "bridge_record"])
def test_exported_contract_replays_glyph_ownership_instead_of_trusting_claim(case):
    extraction = extraction_with_glyph_source()
    page = extraction["pages"][0]
    decision, = page["source_dispositions"].values()
    if case == "hash":
        decision["placement_geometry"]["placed_text_sha256"] = "0" * 64
    elif case == "tokens":
        page["items"][0]["cells"][0]["text_raw"] = "Nợ (0200)"
        page["items"][0]["cells"][0]["text_corrected"] = "Nợ (0200)"
    elif case == "cell_box":
        page["items"][0]["cells"][0]["bbox"] = [0, 0, 5, 5]
    else:
        page["ocr_structure_bridge"]["orientation_placements"] = []
    assert any("glyph" in error for error in validate_extraction(extraction))


def test_duplicate_hidden_lines_do_not_get_a_unique_glyph_claim():
    block = TextBlock(text="020", bbox=[10, 10, 180, 24], source_id="one", page=1,
                      recognition_provenance={"method": LINE_ORIENTATION_METHOD, "rotation_clockwise_degrees": 0})
    placements = []
    with pymupdf.open() as pdf:
        source = pdf.new_page(width=400, height=500)
        page = SimpleNamespace(width=400, height=500, blocks=[block, block.model_copy(update={"source_id": "two"})])
        with ocr_bridge(source, page, 72, orientation_placements=placements):
            pass
    assert len(placements) == 2
    assert all("placed_text_bbox" not in record for record in placements)


def test_observed_docling_float32_edges_match_at_the_exported_precision():
    page = page_with_glyph_cell(text="Thuyết", box=[319.74, 133.25, 354.51, 146.42])
    # Actual Docling cell from AGR 2022 physical page 37; PyMuPDF reports
    # x1=351.166748046875 instead of 351.166718961 for the same hidden line.
    cell_box = [323.08329, 133.90847463299997, 351.166718961, 145.761474399]
    page.tables[0].cells[0].bbox = list(cell_box)
    frozen = deepcopy(page.metadata["text_evidence"])
    _reconcile_evidence(page)
    assert next(iter(page.metadata["source_dispositions"].values()))["status"] == "REPLACED_BY_TABLE"
    assert page.tables[0].cells[0].bbox == cell_box and page.metadata["text_evidence"] == frozen


def test_a_real_gap_of_two_hundredths_of_a_point_still_requires_review():
    page = page_with_glyph_cell()
    page.tables[0].cells[0].bbox[2] -= .02
    _reconcile_evidence(page)
    assert next(iter(page.metadata["source_dispositions"].values()))["status"] == "KEPT_FOR_REVIEW"
    assert page.blocks[0].text_raw == "Nợ (020)"


def test_rounded_geometry_cannot_choose_between_duplicate_cell_owners():
    page = page_with_glyph_cell()
    cell = page.tables[0].cells[0]
    cell.bbox[2] -= .00003
    page.tables[0].cells.append(cell.model_copy(update={"row_idx": 1}, deep=True))
    page.tables[0].num_rows = 2
    _reconcile_evidence(page)
    assert next(iter(page.metadata["source_dispositions"].values()))["status"] == "KEPT_FOR_REVIEW"
    assert page.tables[0].provenance["derived_from_source_ids"] == []


def test_a_restored_protected_source_keeps_its_review_disposition_on_reexport():
    page = page_with_glyph_cell()
    page.metadata["text_evidence"]["items"][0]["protected_from_furniture"] = True
    _reconcile_evidence(page)
    decision = deepcopy(page.metadata["source_dispositions"])
    frozen = deepcopy(page.metadata["text_evidence"])
    count = page.quality.review_required_count
    assert next(iter(decision.values()))["status"] == "KEPT_FOR_REVIEW"
    _reconcile_evidence(page)
    assert page.metadata["source_dispositions"] == decision
    assert page.metadata["text_evidence"] == frozen
    assert len(page.blocks) == len(page.evidence_blocks) == 1
    assert page.quality.review_required_count == count
