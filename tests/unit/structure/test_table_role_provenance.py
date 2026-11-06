from copy import deepcopy

import pytest
from pydantic import ValidationError

from ocr_contracts.table import TableCell
from ocr_structure.docling_client import DoclingStructureExtractor


def response():
    return {"tables": [{"bbox": [0, 0, 100, 60], "num_rows": 2, "num_cols": 1,
                        "orientation": "rot_180", "cells": [
                            {"row": 0, "col": 0, "row_span": 1, "col_span": 1, "text": "2025", "bbox": [0, 0, 100, 30],
                             "column_header": True, "row_header": False, "row_section": False},
                            {"row": 1, "col": 0, "row_span": 1, "col_span": 1, "text": "2025", "bbox": [0, 30, 100, 60],
                             "column_header": False, "row_header": False, "row_section": False}]}]}


def test_actual_roles_and_orientation_survive_rpc_without_inventing_legacy_roles():
    raw = response()
    mapped = DoclingStructureExtractor.map_response(raw, 1)["tables"][0]
    assert mapped.cells[0].column_header is True and mapped.cells[1].column_header is False
    assert mapped.provenance["table_orientation"] == "rot_180"
    assert mapped.provenance["cell_role_source"] == "docling_tableformer"
    legacy = deepcopy(raw)
    for cell in legacy["tables"][0]["cells"]:
        for name in ("column_header", "row_header", "row_section"):
            cell.pop(name)
    table = DoclingStructureExtractor.map_response(legacy, 1)["tables"][0]
    assert "column_header" not in table.cells[0].model_dump()
    assert "cell_role_source" not in table.provenance


@pytest.mark.parametrize("value", ["true", 1, 0, "false"])
def test_role_flags_are_observed_booleans_without_coercion(value):
    with pytest.raises(ValidationError):
        TableCell(row_idx=0, col_idx=0, column_header=value)


def test_unknown_orientation_is_rejected_instead_of_assumed_upright():
    raw = response()
    raw["tables"][0]["orientation"] = "rot_unknown"
    with pytest.raises(ValueError, match="orientation"):
        DoclingStructureExtractor.map_response(raw, 1)
