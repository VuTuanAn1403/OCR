"""Read back formulas, booleans and extra columns even in unknown total cells."""
from io import BytesIO

import openpyxl
import pytest

from ocr_keywords.contract import dictionary_snapshot
from ocr_reporting.workbooks import matrix_bytes, verify_matrix


@pytest.mark.parametrize("damage", ["formula-in-unknown", "boolean-count", "extra-column"])
def test_tiered_matrix_rejects_nonliteral_or_extra_values(tmp_path, damage):
    keys = tmp_path / "keys.txt"
    keys.write_text("chuyển đổi số\n", encoding="utf-8")
    dictionary = dictionary_snapshot(keys, "matrix-test")
    records = [{"id": "doc", "name": "=document.pdf", "outcome": "SUCCEEDED", "counts": [0],
                "analytics_enabled": True, "analytics_rules_sha256": "a"*64,
                "alias_analytics": {"tier2_counts": [0], "pending_counts": [1]}}]
    path = tmp_path / "matrix.xlsx"
    path.write_bytes(matrix_bytes("batch", 1, records, dictionary))
    verify_matrix(path, "batch", 1, records, dictionary)
    book = openpyxl.load_workbook(path)
    if damage == "formula-in-unknown": book["Tong_sau_duyet"]["B2"] = "=1+1"
    if damage == "boolean-count": book["Dem_Tier2"]["B2"] = False
    if damage == "extra-column": book["Dem_Tier2"]["C2"] = "extra"
    book.save(path)
    book.close()
    with pytest.raises(ValueError): verify_matrix(path, "batch", 1, records, dictionary)
