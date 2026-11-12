"""compare_table_number_review.locate: geometric lookup, independent of source_id ranks."""
from scripts.compare_table_number_review import locate

ITEM = {"number": "1.234", "line_bboxes": [[10, 10, 100, 20]], "line_source_ids": ["old:p0001:b000007"]}


def test_a_number_in_an_overlapping_table_cell_is_in_table():
    page = {"items": [{"kind": "t", "bbox": [0, 0, 200, 100], "cells": [{"text_raw": "1.234"}]}]}
    assert locate(ITEM, page) == {"in_table": True, "visible": False}


def test_a_visible_line_is_found_by_geometry_even_when_its_source_id_changed():
    page = {"items": [{"kind": "b", "bbox": [12, 11, 98, 19], "source_id": "new:p0001:b000009", "text_raw": "Tổng 1.234"},
                      {"kind": "b", "bbox": [10, 300, 100, 310], "source_id": "old:p0001:b000007", "text_raw": "khác"}]}
    assert locate(ITEM, page) == {"in_table": False, "visible": True}
