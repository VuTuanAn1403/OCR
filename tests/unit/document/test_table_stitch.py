"""Cross-page projection must preserve each source cell and grid ownership."""
from copy import deepcopy

import pytest

from ocr_document.table_stitch import project_table, render_preview_html


def fixture(*parts):
    extraction, document = {"pages": []}, {"tables": []}
    for page, (rows, cols, entries) in enumerate(parts, 1):
        table_id = f"table-{page}"
        cells = []
        for row, col, height, width, text in entries:
            bbox = [10 * col, 10 * row, 10 * (col + width), 10 * (row + height)]
            cells.append({"row": row, "col": col, "row_span": height, "col_span": width,
                          "text_raw": text, "text_corrected": text, "bbox_source": "cell", "bbox": bbox,
                          "spans": [{"page": page, "bbox": bbox, "block_ids": [table_id]}]})
        grid = {"num_rows": rows, "num_cols": cols, "cells": cells}
        item = {**grid, "id": table_id, "kind": "t", "engine": "fixture", "bbox": [0, 0, cols * 10, rows * 10]}
        extraction["pages"].append({"page": page, "coordinate_space": "pdf_points_top_left", "transforms": [], "items": [item]})
        document["tables"].append({**deepcopy(grid), "table_id": table_id, "pages": [page], "section_id": "section"})
    return extraction, document, [row["table_id"] for row in document["tables"]]


def boundary(kind, headers=0, columns=()):
    return {"kind": kind, "repeated_header_rows": headers, "join_columns": list(columns)}


def test_split_row_reuses_one_row_and_keeps_the_repeated_header_sources():
    head = [(0, 0, 1, 1, "Chỉ tiêu"), (0, 1, 1, 1, "Năm 2025")]
    source = fixture((2, 2, [*head, (1, 0, 1, 1, "Nội dung <tiếp>")]),
                     (3, 2, [*head, (1, 0, 1, 1, "giữ dấu"), (1, 1, 1, 1, "(020)"), (2, 1, 1, 1, "0")]))
    before = deepcopy(source)
    result = project_table(*source, [boundary("SPLIT_ROW", 1, [0])])
    assert source == before and result["num_rows"] == 3
    assert result["observed_source_cells"] == 8 and result["unobserved_grid_slots"] == 1
    cells = {(cell["row"], cell["col"]): cell for cell in result["cells"]}
    assert [item["page"] for item in cells[1, 0]["sources"]] == [1, 2]
    assert cells[0, 1]["repeated_header_sources"][0]["cell"]["text_raw"] == "Năm 2025"
    html = render_preview_html(result)
    assert html.count("<table>") == 1 and html.count("Năm 2025") == 1
    assert "Nội dung &lt;tiếp&gt;<br>giữ dấu" in html and "(020)" in html
    assert '<td data-state="unobserved"></td>' in html
    with pytest.raises(ValueError, match="explicit cell join"):
        project_table(*source, [boundary("SPLIT_ROW", 1)])


def test_spanning_cell_extends_across_pages_without_losing_the_next_numeric_row():
    source = fixture((2, 3, [(0, 0, 2, 2, "Nhóm"), (0, 2, 1, 1, "020"), (1, 2, 1, 1, "(30)")]),
                     (2, 3, [(0, 0, 1, 2, "tiếp theo"), (0, 2, 1, 1, "04,5"), (1, 0, 1, 3, "Tổng & kết")]))
    result = project_table(*source, [boundary("SPANNING_CELL", columns=[0])])
    assert result["num_rows"] == 4 and result["observed_source_cells"] == 6 and not result["unobserved_grid_slots"]
    html = render_preview_html(result)
    assert 'rowspan="3" colspan="2">Nhóm<br>tiếp theo</td>' in html
    assert "020" in html and "(30)" in html and "04,5" in html and "Tổng &amp; kết" in html


def test_different_headers_and_numeric_literal_joins_are_rejected():
    source = fixture((2, 1, [(0, 0, 1, 1, "2025"), (1, 0, 1, 1, "020")]),
                     (2, 1, [(0, 0, 1, 1, "2024"), (1, 0, 1, 1, "30")]))
    with pytest.raises(ValueError, match="exactly match"):
        project_table(*source, [boundary("BETWEEN_ROWS", 1)])
    with pytest.raises(ValueError, match="numeric literal"):
        project_table(*source, [boundary("SPLIT_ROW", columns=[0])])


def test_unobserved_and_multiply_owned_cells_are_distinct_from_empty_cells():
    extraction, document, ids = fixture((1, 2, [(0, 0, 1, 1, "")]),
                                        (1, 2, [(0, 0, 1, 1, "020"), (0, 1, 1, 1, "30")]))
    plan = [boundary("BETWEEN_ROWS")]
    result = project_table(extraction, document, ids, plan)
    assert result["observed_source_cells"] == 3 and result["unobserved_grid_slots"] == 1
    assert "<td></td>" in render_preview_html(result)
    second = extraction["pages"][1]["items"][0]["cells"]
    second[1].update(bbox=second[0]["bbox"], spans=second[0]["spans"])
    document["tables"][1]["cells"] = deepcopy(second)
    with pytest.raises(ValueError, match="share one source bbox"):
        project_table(extraction, document, ids, plan)


def test_source_units_and_section_boundaries_are_not_silently_changed():
    extraction, document, ids = fixture((1, 1, [(0, 0, 1, 1, "020")]), (1, 1, [(0, 0, 1, 1, "40")]))
    document["chunks"] = [{"chunk_id": "caption", "text_raw": "Bảng tài chính", "text_corrected": "Bảng tài chính"},
                          {"chunk_id": "unit", "text_raw": "Triệu VND", "text_corrected": "Triệu VND"}]
    document["tables"][0]["caption"] = {"chunk_id": "caption", "unit_chunk_id": "unit"}
    plan = [boundary("BETWEEN_ROWS")]
    html = render_preview_html(project_table(extraction, document, ids, plan))
    assert "<caption>Bảng tài chính<br>Triệu VND</caption>" in html
    document["tables"][1]["section_id"] = "new-section"
    with pytest.raises(ValueError, match="crosses a document section"):
        project_table(extraction, document, ids, plan)
