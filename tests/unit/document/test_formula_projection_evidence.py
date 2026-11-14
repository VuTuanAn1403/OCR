"""The CPU export validates the formula projection of an actual phase B page shape."""

import json
from unittest.mock import Mock

import pytest

from tests.unit.document_test_helpers import block, make_doc
from ocr_contracts.formula import Formula
from ocr_document.export import DocumentExporter
from ocr_document.source_identity import lock_text_evidence
from ocr_document.validation import validate_document
from ocr_structure.enrichment import enrich_structures


@pytest.fixture
def formula_export(tmp_path):
    doc = make_doc([[block("Số dư 125,00", 1, text_raw="Số dư 125,00")]])
    page = doc.pages[0]
    lock_text_evidence(page.blocks, doc.file_hash, 1, page.metadata)
    formulas = [
        Formula(formula_id="f1", page=1, latex=r"x=\frac{a}{b}", bbox=[40, 100, 150, 115]),
        Formula(formula_id="f2", page=1, latex="y=z^2", bbox=[40, 140, 150, 155]),
    ]
    extractor = Mock(enabled=True, options={"page_selection": "all"})
    extractor.cache_fingerprint.return_value = "formula-fixture"
    extractor.extract_page.return_value = {"tables": [], "formulas": formulas, "metadata": {"status": "success"}}
    page.blocks, page.tables, page.formulas = enrich_structures(
        extractor, None, 1, page.page_type, page.blocks, page.tables, page.regions, page.metadata,
    )
    return DocumentExporter.execute(
        doc, tmp_path, assets_mode="none", output_mode="compact", document_layout={"method": "region_tree_graph_v1"},
    )


def test_docling_formula_projections_use_formula_evidence(formula_export):
    page = json.loads((formula_export / "pages/page-0001.json").read_bytes())
    assert len(page["evidence_blocks"]) == 1
    source, = page["metadata"]["text_evidence"]["items"]
    assert source["text_raw"] == "Số dư 125,00"
    assert page["metadata"]["source_dispositions"][source["source_id"]]["status"] == "VISIBLE_OR_FURNITURE"
    projections = [block for block in page["blocks"] if block["source"] == "docling"]
    assert len(projections) == len(page["formulas"]) == 2
    markdown = (formula_export / "result.md").read_text(encoding="utf-8")
    for formula, projection in zip(page["formulas"], projections, strict=True):
        assert (projection["text"], projection["bbox"]) == (formula["latex"], formula["bbox"])
        assert formula["status"] == "NEEDS_REVIEW"
        assert markdown.count(f'$$\n{formula["latex"]}\n$$') == 1
    validation = validate_document(formula_export)
    assert validation["status"] == "NEEDS_REVIEW"
    assert validation["errors"] == []


@pytest.mark.parametrize("mismatch", ["missing_text", "wrong_engine", "wrong_box", "duplicate_projection"])
def test_formula_projection_cannot_cover_unrelated_blocks(formula_export, mismatch):
    path = formula_export / "pages/page-0001.json"
    page = json.loads(path.read_bytes())
    formula = next(block for block in page["blocks"] if block["source"] == "docling")
    if mismatch == "missing_text":
        page["evidence_blocks"] = []
    elif mismatch == "wrong_engine":
        formula["engine"] = "other_engine"
    elif mismatch == "wrong_box":
        formula["bbox"][0] += 1
    else:
        page["blocks"].append(formula.copy())
    path.write_text(json.dumps(page, ensure_ascii=False), encoding="utf-8")
    validation = validate_document(formula_export)
    assert validation["status"] == "FAIL"
    assert "Page 1: evidence count differs from text block count" in validation["errors"]
