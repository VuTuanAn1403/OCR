"""Exact observed bridge tokens can own multiple cells of one physical row."""
from copy import deepcopy

import pytest

from ocr_contracts.document import ExtractedDocument
from ocr_contracts.geometry import placed_line_tokens
from ocr_contracts.quality import DocumentQualityReport
from ocr_contracts.table import TableCell
from ocr_document.contract_schema import validate_extraction
from ocr_document.document_contracts import build_extraction_json
from ocr_document.ids import page_items
from ocr_document.resolve_document_layout import _reconcile_evidence, resolve_document_layout, TOKEN_RECONCILIATION_METHOD
from test_source_glyph_ownership import page_with_glyph_cell


def cross_cell_page(angle=0):
    page = page_with_glyph_cell(angle)
    source = page.metadata["text_evidence"]["items"][0]
    placement = page.metadata["ocr_structure_bridge"]["orientation_placements"][0]
    tokens = placed_line_tokens(source, placement)
    assert [t["text"] for t in tokens] == ["Nợ", "(020)"]
    page.tables[0].num_cols = 2
    page.tables[0].cells = [TableCell(row_idx=0, col_idx=n, text=t["text"], bbox=t["bbox"])
                            for n, t in enumerate(tokens)]
    return page


@pytest.mark.parametrize("angle", [0, 90, 180, 270])
def test_observed_token_geometry_maps_both_cells_and_preserves_raw_box(angle):
    page = cross_cell_page(angle)
    frozen = deepcopy(page.metadata["text_evidence"])
    cells = [c.model_dump() for c in page.tables[0].cells]
    _reconcile_evidence(page)
    decision, = page.metadata["source_dispositions"].values()
    assert decision["status"] == "REPLACED_BY_TABLE" and decision["placement_granularity"] == "TOKEN"
    assert [p["col_idx"] for p in decision["occurrence_mapping"]] == [0, 1]
    assert page.metadata["source_reconciliation_method"] == TOKEN_RECONCILIATION_METHOD
    assert not page.blocks and page.metadata["text_evidence"] == frozen
    assert [c.model_dump() for c in page.tables[0].cells] == cells
    _reconcile_evidence(page)
    assert page.metadata["text_evidence"] == frozen and not page.blocks


@pytest.mark.parametrize("case", ["legacy", "token_text", "token_box", "missing_token", "wrong_number",
                                  "cross_rows", "duplicate_owner", "protected", "split_number"])
def test_incomplete_ambiguous_or_altered_tokens_keep_the_whole_source(case):
    page = cross_cell_page()
    placement = page.metadata["ocr_structure_bridge"]["orientation_placements"][0]
    if case == "legacy":
        placement.pop("placed_tokens")
        placement.pop("placed_token_geometry_method")
    elif case == "token_text":
        placement["placed_tokens"][1]["text"] = "(O2O)"
    elif case == "token_box":
        placement["placed_tokens"][1]["bbox"] = [0, 0, 400, 300]
    elif case == "missing_token":
        placement["placed_tokens"].pop()
    elif case == "wrong_number":
        page.tables[0].cells[1].text = "(0200)"
    elif case == "cross_rows":
        page.tables[0].num_rows = 2
        page.tables[0].cells[1].row_idx = 1
    elif case == "duplicate_owner":
        page.tables.append(page.tables[0].model_copy(deep=True, update={"table_id": "duplicate"}))
    elif case == "protected":
        page.metadata["text_evidence"]["items"][0]["protected_from_furniture"] = True
    else:
        page.tables[0].cells[1].text = "(0 20)"
    _reconcile_evidence(page)
    assert next(iter(page.metadata["source_dispositions"].values()))["status"] == "KEPT_FOR_REVIEW"
    assert page.blocks[0].text_raw == "Nợ (020)"


def cross_cell_extraction():
    page = cross_cell_page()
    doc = ExtractedDocument(document_id="test", file_path="unused.pdf", file_hash="a" * 16,
                            total_pages=1, selected_pages=[1], pages=[page],
                            quality=DocumentQualityReport(document_id="test", total_pages=1))
    resolve_document_layout(doc)
    extraction = build_extraction_json(doc, [page_items(doc.file_hash, page)], "cuda")
    assert validate_extraction(extraction) == []
    return extraction


@pytest.mark.parametrize("case", ["missing_proof", "changed_source", "mapping", "number", "cell_box", "row"])
def test_exported_contract_replays_cross_cell_proof(case):
    extraction = cross_cell_extraction()
    page = extraction["pages"][0]
    decision, = page["source_dispositions"].values()
    table, = [item for item in page["items"] if item["kind"] == "t"]
    if case == "missing_proof":
        page["ocr_structure_bridge"]["orientation_placements"] = []
    elif case == "changed_source":
        page["text_evidence"]["items"][0]["text"] = "Nợ (O2O)"
    elif case == "mapping":
        decision["occurrence_mapping"][1]["token_index"] = 99
    elif case == "number":
        table["cells"][1]["text_raw"] = "(0200)"
        table["cells"][1]["text_corrected"] = "(0200)"
    elif case == "cell_box":
        table["cells"][1]["bbox"] = [0, 0, 1, 1]
    else:
        table["cells"][1]["row"] = 1
    assert any("glyph" in error for error in validate_extraction(extraction))


def test_token_geometry_does_not_round_away_a_real_cell_gap():
    page = cross_cell_page()
    page.tables[0].cells[1].bbox[2] -= .02
    _reconcile_evidence(page)
    assert next(iter(page.metadata["source_dispositions"].values()))["status"] == "KEPT_FOR_REVIEW"


def test_only_a_proven_presentation_marker_can_be_excluded():
    page = page_with_glyph_cell(text="• Nợ (020)")
    source = page.metadata["text_evidence"]["items"][0]
    source["block_type"] = "list_item"
    tokens = page.metadata["ocr_structure_bridge"]["orientation_placements"][0]["placed_tokens"][1:]
    page.tables[0].num_cols = 2
    page.tables[0].cells = [TableCell(row_idx=0, col_idx=n, text=t["text"], bbox=t["bbox"])
                            for n, t in enumerate(tokens)]
    _reconcile_evidence(page)
    decision, = page.metadata["source_dispositions"].values()
    assert decision["status"] == "REPLACED_BY_TABLE"
    assert decision["excluded_presentation_tokens"] == ["•"]
    assert source["text"] == "• Nợ (020)"


def test_contract_rejects_a_second_source_claiming_the_same_cell_occurrences():
    extraction = cross_cell_extraction()
    page = extraction["pages"][0]
    source = deepcopy(page["text_evidence"]["items"][0])
    original = source["source_id"]
    source["source_id"] += ":duplicate"
    page["text_evidence"]["items"].append(source)
    decision = deepcopy(page["source_dispositions"][original])
    decision["placement_geometry"]["source_id"] = source["source_id"]
    page["source_dispositions"][source["source_id"]] = decision
    page["ocr_structure_bridge"]["orientation_placements"].append(deepcopy(decision["placement_geometry"]))
    table, = [item for item in page["items"] if item["kind"] == "t"]
    table["derived_from_source_ids"].append(source["source_id"])
    assert any("reuses" in error for error in validate_extraction(extraction))


def test_export_reconciles_a_cached_v14_document_with_new_token_proof(tmp_path):
    from ocr_document.export import DocumentExporter
    from ocr_document.resolve_document_layout import ALGORITHM_VERSION

    page = cross_cell_page()
    record = page.metadata["ocr_structure_bridge"]["orientation_placements"][0]
    token_proof = {key: record.pop(key) for key in ("placed_tokens", "placed_token_geometry_method")}
    doc = ExtractedDocument(document_id="cached", file_path="unused.pdf", file_hash="a" * 16,
                            total_pages=1, selected_pages=[1], pages=[page],
                            quality=DocumentQualityReport(document_id="cached", total_pages=1),
                            manifest={"device": "cuda", "selected_pages": [1], "total_pages": 1,
                                      "configuration": {"document_layout": {"method": "region_tree_graph_v1"}}})
    resolve_document_layout(doc)
    assert next(iter(page.metadata["source_dispositions"].values()))["status"] == "KEPT_FOR_REVIEW"
    # Simulate a persisted document resolved by the preceding algorithm.
    doc.manifest["document_layout"]["algorithm_version"] = "region-tree-graph-v1.4"
    record.update(token_proof)
    DocumentExporter.execute(doc, tmp_path, assets_mode="none")
    assert next(iter(page.metadata["source_dispositions"].values()))["placement_granularity"] == "TOKEN"
    assert doc.manifest["document_layout"]["algorithm_version"] == ALGORITHM_VERSION
