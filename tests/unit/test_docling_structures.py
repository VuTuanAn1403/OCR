"""Regression contracts for the isolated TableFormer/formula integration.

No downloaded weights are needed; scripts/smoke_docling_structures.py checks
real model inference separately. These tests cannot establish OCR accuracy.
"""
import json
from pathlib import Path
import queue
from types import SimpleNamespace
from unittest.mock import Mock

import pymupdf
import pytest

from src.ocr.application.process_page import ProcessPageUseCase
from src.ocr.application.export_document import ExportDocumentUseCase
from src.ocr.cli.batch_runner import BatchOCRRunner
from src.ocr.domain.models.document import ExtractedDocument
from src.ocr.domain.models.page import ExtractedPage
from src.ocr.domain.models.quality import DocumentQualityReport, PageQualityReport
from src.ocr.domain.models.text_block import TextBlock
from src.ocr.domain.routing.page_type import PageType
from src.ocr.infrastructure.export.artifact_validator import validate_document_artifacts
from src.ocr.infrastructure.export.json_exporter import JSONExporter
from src.ocr.infrastructure.export.markdown_exporter import MarkdownExporter
from src.ocr.infrastructure.layout.docling_structure import (
    DoclingStructureError, DoclingStructureExtractor, block_is_covered,
    native_formula_hints,
)


def response():
    return {"status": "success", "provenance": {"device": "cpu", "docling_version": "2.137.0"},
        "tables": [{"bbox": [10, 40, 110, 100], "num_rows": 2, "num_cols": 2,
            "cells": [{"row": 0, "col": 0, "row_span": 1, "col_span": 2, "text": "Measurements"},
                      {"row": 1, "col": 0, "row_span": 1, "col_span": 1, "text": "x"},
                      {"row": 1, "col": 1, "row_span": 1, "col_span": 1, "text": "0.5"}],
            "html": '<table><tr><th colspan="2">Measurements</th></tr><tr><td>x</td><td>0.5</td></tr></table>'}],
        "formulas": [{"bbox": [10, 120, 100, 145], "latex": r"E=mc^2"}]}


def processor(extractor):
    proc = ProcessPageUseCase.__new__(ProcessPageUseCase)
    proc.structure_extractor = extractor
    return proc


def enrich(extractor, blocks=(), tables=(), regions=None, page_type=PageType.NATIVE_TEXT):
    meta = {"width": 595, "height": 842}
    regions = regions if regions is not None else []
    values = processor(extractor)._enrich_structures(None, 4, page_type, list(blocks), list(tables), regions, meta)
    return values, meta, regions


def test_mapping_preserves_spans_and_does_not_invent_confidence():
    mapped = DoclingStructureExtractor.map_response(response(), 4)
    table, formula = mapped["tables"][0], mapped["formulas"][0]
    assert table.page == 4 and table.cells[0].col_span == 2
    assert table.bbox == [10, 40, 110, 100]
    assert table.engine == "docling_tableformer" and table.needs_review
    assert table.confidence == 0 and not table.provenance["confidence_available"]
    assert formula.page == 4 and formula.confidence is None and formula.status == "NEEDS_REVIEW"
    assert "colspan" not in table.to_pipe_table()
    assert "colspan" in table.provenance["html"]


def test_math_hint_groups_fraction_and_excludes_prose_and_equation_number():
    page = Mock()
    page.get_text.return_value = [
        (10, 100, 20, 140, "∫", 0, 0),
        (25, 95, 35, 110, "1", 1, 0),
        (25, 115, 100, 135, "x² dx = 1/3", 2, 0),
        (115, 115, 130, 135, "(1)", 3, 0),
        (10, 60, 200, 80, "A paragraph discussing the method", 4, 0),
    ]
    hints = native_formula_hints(page)
    assert len(hints) == 1 and hints[0]["bbox"] == [10, 95, 100, 140]
    assert hints[0]["source"] == "native_math_hint"


def test_math_symbol_in_long_prose_is_not_a_formula_crop():
    page = Mock()
    page.get_text.return_value = [(10, 10, 450, 40,
        "This paragraph discusses the integral ∫ and several properties of numerical integration.", 0, 0)]
    assert native_formula_hints(page) == []


@pytest.mark.parametrize("bad", ["bbox", "span"])
def test_malformed_structure_cannot_replace_existing_content(bad):
    raw = response()
    if bad == "bbox":
        raw["tables"][0]["bbox"] = [10, 20, 5, 20]
    else:
        raw["tables"][0]["cells"][0]["col_span"] = 3
    with pytest.raises(ValueError):
        DoclingStructureExtractor.map_response(raw, 1)


@pytest.mark.parametrize("wrapped", [r"$$E=mc^2$$", r"\[E=mc^2\]", r"\(E=mc^2\)"])
def test_formula_delimiters_are_not_doubled(wrapped):
    raw = response()
    raw["formulas"][0]["latex"] = wrapped
    formula = DoclingStructureExtractor.map_response(raw, 1)["formulas"][0]
    assert formula.to_markdown() == "$$\nE=mc^2\n$$"


def test_empty_model_result_keeps_text_and_heuristic_table():
    raw = response()
    raw["tables"][0]["cells"] = []
    raw["formulas"] = []
    extractor = Mock(enabled=True, options={"page_selection": "all"})
    extractor.extract_page.return_value = DoclingStructureExtractor.map_response(raw, 4)
    original = TextBlock(text="Original text", page=4, bbox=[20, 50, 100, 75])
    table = DoclingStructureExtractor.map_response(response(), 4)["tables"][0].model_copy(update={"engine": "heuristic"})
    (blocks, tables, formulas), meta, _ = enrich(extractor, [original], [table])
    assert blocks == [original] and tables == [table] and formulas == []
    assert meta["docling_structure"]["status"] == "success"


def test_structure_replacement_preserves_body_and_partial_overlap():
    mapped = DoclingStructureExtractor.map_response(response(), 4)
    extractor = Mock(enabled=True, options={"page_selection": "all"})
    extractor.extract_page.return_value = mapped
    originals = [TextBlock(text="Measurements", page=4, bbox=[15, 45, 100, 70]),
        TextBlock(text="Introduction", page=4, bbox=[10, 10, 200, 30]),
        TextBlock(text="Footnote beside table", page=4, bbox=[100, 85, 220, 105]),
        TextBlock(text="(1)", page=4, bbox=[80, 125, 98, 140]),
        TextBlock(text="Poor formula OCR", page=4, bbox=[15, 125, 95, 140])]
    heuristic = mapped["tables"][0].model_copy(update={"engine": "heuristic"})
    (blocks, tables, formulas), _, regions = enrich(extractor, originals, [heuristic])
    assert {b.text for b in blocks} == {"Introduction", "Footnote beside table", "E=mc^2", "(1)"}
    assert len(tables) == 1 and tables[0].engine == "docling_tableformer"
    assert len(formulas) == 1 and len(regions) == 2
    assert all(r.status == "NEEDS_REVIEW" for r in regions)
    assert not block_is_covered(originals[2].bbox, tables)


def test_missing_environment_preserves_content_and_records_failure():
    extractor = DoclingStructureExtractor({"enabled": True, "page_selection": "all",
        "python_executable": "missing-docling-python.exe"})
    original = TextBlock(text="Original evidence", page=4, bbox=[10, 10, 200, 30])
    (blocks, tables, formulas), meta, regions = enrich(extractor, [original])
    assert blocks == [original] and not tables and not formulas
    assert meta["docling_structure"]["status"] == "FAILED_FALLBACK"
    assert regions[0].status == "NEEDS_REVIEW"


def test_disabled_and_auto_plain_native_page_do_not_start_models():
    for options, expected in (({"enabled": False}, "DISABLED"),
                              ({"enabled": True, "page_selection": "auto"}, "SKIPPED_NO_STRUCTURE_CANDIDATE")):
        extractor = DoclingStructureExtractor(options)
        extractor.extract_page = Mock(side_effect=AssertionError("Model unexpectedly called"))
        original = TextBlock(text="A plain paragraph", page=4, bbox=[10, 10, 200, 30])
        values, meta, _ = enrich(extractor, [original])
        assert values[0] == [original] and meta["docling_structure"]["status"] == expected
        extractor.extract_page.assert_not_called()


def test_timeout_terminates_worker_instead_of_leaving_inference_running(tmp_path, monkeypatch):
    extractor = DoclingStructureExtractor({"enabled": True, "timeout_seconds": 0.01})
    fake = Mock()
    fake.poll.return_value = None
    child = Mock()
    process_info = Mock()
    process_info.children.return_value = [child]
    monkeypatch.setattr("src.ocr.infrastructure.layout.docling_structure.psutil.Process", Mock(return_value=process_info))
    monkeypatch.setattr("src.ocr.infrastructure.layout.docling_structure.psutil.wait_procs", Mock())
    extractor._process = fake
    extractor._job_dir = tmp_path
    extractor._responses = queue.Queue()
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        with pytest.raises(DoclingStructureError, match="terminated"):
            extractor.extract_page(page, 1)
    fake.kill.assert_called_once()
    child.kill.assert_called_once()
    fake.wait.assert_called_once()
    assert extractor._process is None


def formula_page():
    mapped = DoclingStructureExtractor.map_response(response(), 1)
    formula = mapped["formulas"][0]
    return ExtractedPage(page_num=1, width=595, height=842, page_type=PageType.NATIVE_TEXT,
        tables=mapped["tables"], formulas=[formula],
        blocks=[TextBlock(text="The result is", page=1, bbox=[10, 115, 150, 125]),
                TextBlock(text=formula.latex, page=1, bbox=formula.bbox, block_type="formula", source="docling"),
                TextBlock(text="Conclusion", page=1, bbox=[10, 148, 150, 160])],
        quality=PageQualityReport(page=1, page_type="NATIVE_TEXT"))


def test_formula_survives_markdown_merging_and_json_roundtrip():
    page = formula_page()
    md = MarkdownExporter.export_page_markdown(page)
    assert md.count("$$\nE=mc^2\n$$") == 1
    assert "The result is" in md and "Conclusion" in md
    dumped = JSONExporter.export_page_json(page)
    restored = ExtractedPage.model_validate(dumped)
    assert restored.blocks[1].block_type == "formula"
    assert restored.formulas[0].latex == "E=mc^2"
    assert MarkdownExporter.export_page_markdown(restored) == md
    # The diagram-style branch must not flatten a formula-only page either.
    page.tables = []
    assert "$$\nE=mc^2\n$$" in MarkdownExporter.export_page_markdown(page)


@pytest.mark.parametrize("y", [5, 800])
def test_formula_at_page_edge_cannot_be_suppressed_as_running_text(y):
    from src.ocr.infrastructure.postprocessing.reading_order import ReadingOrderSorter
    pages = []
    for page_num in (1, 2, 3):
        page = formula_page()
        page.page_num = page_num
        page.tables = []
        formula_block = page.blocks[1].model_copy(update={"page": page_num, "bbox": [20, y, 100, y+20]})
        page.blocks = ReadingOrderSorter().sort_blocks([formula_block])
        pages.append(page)
    doc = ExtractedDocument(document_id="edge", file_path="unused.pdf", file_hash="abc", total_pages=3,
        pages=pages, quality=DocumentQualityReport(document_id="edge", total_pages=3))
    ExportDocumentUseCase._detect_running_headers_and_footers(doc)
    assert all(p.blocks[0].block_type == "formula" for p in pages)
    assert MarkdownExporter.export_document_markdown(doc).count("$$\nE=mc^2\n$$") == 3


def test_export_preserves_structure_sidecars_and_validator_detects_lost_formula(tmp_path):
    page = formula_page()
    # Supply evidence for the existing validator's block/evidence contract.
    from src.ocr.domain.models.evidence_block import EvidenceBlock
    from src.ocr.domain.models.region import ContentType, Region, BoundingBox
    page.regions = [Region(region_id="r1", bbox=BoundingBox(x0=0, y0=0, x1=595, y1=842),
                           content_type=ContentType.TEXT, status="EXTRACTED")]
    page.evidence_blocks = [EvidenceBlock(block_id=f"b{i}", page=1, region_id="r1", bbox=b.bbox,
        orientation=0, text=b.text, content_type=ContentType.TEXT, source="native") for i, b in enumerate(page.blocks)]
    doc = ExtractedDocument(document_id="fixture", file_path="unused.pdf", file_hash="abc", total_pages=1,
        selected_pages=[1], pages=[page], manifest={"selected_pages": [1]},
        quality=DocumentQualityReport(document_id="fixture", total_pages=1))
    out = ExportDocumentUseCase.execute(doc, tmp_path)
    table_html = out / page.tables[0].provenance["html_artifact"]
    formula_tex = out / page.formulas[0].provenance["latex_artifact"]
    assert 'colspan="2"' in table_html.read_text(encoding="utf-8")
    assert formula_tex.read_text(encoding="utf-8") == "E=mc^2"
    report = validate_document_artifacts(out)
    assert report["status"] == "NEEDS_REVIEW" and report["counts"]["formulas_json"] == 1
    (out / "result.md").write_text("Formula removed", encoding="utf-8")
    assert any("missing from result.md" in e for e in validate_document_artifacts(out)["errors"])


def test_cache_invalidates_old_artifacts_and_backend_options(tmp_path):
    options = {"enabled": True, "page_selection": "all", "formulas": True}
    expected = DoclingStructureExtractor(options).cache_fingerprint()
    assert expected != DoclingStructureExtractor({**options, "formulas": False}).cache_fingerprint()
    runner = BatchOCRRunner.__new__(BatchOCRRunner)
    runner.force, runner.output_dir, runner.profile = False, tmp_path, "accuracy"
    runner.converter = SimpleNamespace(profiles={"accuracy": {"docling": options}})
    doc_dir = tmp_path / "fixture"
    (doc_dir / "pages").mkdir(parents=True)
    (doc_dir / "pages/page-0001.md").write_text("x")
    for name in ("result", "manifest", "quality", "benchmark"):
        (doc_dir / f"{name}.json").write_text("{}")
    (doc_dir / "result.md").write_text("x")
    (doc_dir / "validation.json").write_text('{"status":"PASS"}')
    (doc_dir / "result.json").write_text('{"pages":[{"metadata":{}}]}')
    assert runner.is_cached("fixture", 1) is None
    for status, hit in (("success", True), ("FAILED_FALLBACK", False)):
        data = {"pages": [{"metadata": {"docling_structure": {"status": status, "cache_fingerprint": expected}}}]}
        (doc_dir / "result.json").write_text(json.dumps(data))
        assert (runner.is_cached("fixture", 1) is not None) == hit
