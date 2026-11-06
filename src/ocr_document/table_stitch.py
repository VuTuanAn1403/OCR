"""Project a proposed table chain without changing its extraction cells."""
from copy import deepcopy
from html import escape

from ocr_text.numeric_guard import preserves_numeric_evidence

from .source_identity import valid_bbox

SCHEMA = "ocr-table-stitch-preview-v1"
BOUNDARIES = {"BETWEEN_ROWS", "SPLIT_ROW", "SPANNING_CELL"}
MAX_GRID_SLOTS = 250_000


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _index(value, minimum):
    return type(value) is int and value >= minimum


def _grid(cells, rows, cols):
    """Assign every observed slot to one source or projected cell anchor."""
    _require(_index(rows, 1) and _index(cols, 1) and rows * cols <= MAX_GRID_SLOTS,
             "Invalid table dimensions or grid exceeds the preview limit")
    occupied = {}
    for cell in cells:
        row, col, height, width = (cell[key] for key in ("row", "col", "row_span", "col_span"))
        _require(_index(row, 0) and _index(col, 0) and _index(height, 1) and _index(width, 1)
                 and row + height <= rows and col + width <= cols, "Table cell span is outside the grid")
        for i in range(row, row + height):
            for j in range(col, col + width):
                _require((i, j) not in occupied, f"Overlapping table cell ownership at row {i}, column {j}")
                occupied[i, j] = cell
    return occupied


def _fragment(table, page, item, chunks):
    """Require exact extraction ownership, independent of visual row guessing."""
    cells, table_id = table["cells"], table["table_id"]
    _require(item["kind"] == "t" and table["pages"] == [page["page"]]
             and all(table[key] == item[key] for key in ("num_rows", "num_cols", "cells")),
             f"Table fragment differs from extraction: {table_id}")
    _require(table.get("table_orientation") == item.get("table_orientation"),
             f"Table orientation differs from extraction: {table_id}")
    _require(bool(cells), f"Table fragment has no observed cells: {table_id}")
    _grid(cells, table["num_rows"], table["num_cols"])
    seen_boxes = set()
    for cell in cells:
        bbox = cell["bbox"]
        _require(cell.get("bbox_source") == "cell" and valid_bbox(bbox)
                 and cell.get("spans") == [{"page": page["page"], "bbox": bbox, "block_ids": [table_id]}],
                 f"Cell lacks exact source location in {table_id} at ({cell['row']}, {cell['col']})")
        _require(tuple(bbox) not in seen_boxes,
                 f"Multiple cells share one source bbox in {table_id} at ({cell['row']}, {cell['col']})")
        _require(isinstance(cell["text_raw"], str) and isinstance(cell["text_corrected"], str)
                 and preserves_numeric_evidence(cell["text_raw"], cell["text_corrected"]),
                 f"Cell changes numeric evidence in {table_id} at ({cell['row']}, {cell['col']})")
        seen_boxes.add(tuple(bbox))
    context = {}
    if caption := table.get("caption"):
        context["caption"] = deepcopy(chunks[caption["chunk_id"]])
        if unit := caption.get("unit_chunk_id"):
            context["unit"] = deepcopy(chunks[unit])
    return {"table_id": table_id, "page": page["page"], "num_rows": table["num_rows"], "num_cols": table["num_cols"],
            "bbox": item["bbox"], "coordinate_space": page["coordinate_space"], "transforms": page["transforms"],
            "engine": item["engine"], "context": context, "cells": cells,
            **({"table_orientation": item["table_orientation"]} if "table_orientation" in item else {})}


def _source(fragment, cell):
    return {"table_id": fragment["table_id"], "page": fragment["page"], "cell": deepcopy(cell)}


def _cell(fragment, cell, row):
    return {"row": row, "col": cell["col"], "row_span": cell["row_span"], "col_span": cell["col_span"],
            "sources": [_source(fragment, cell)], "repeated_header_sources": []}


def _header(cells, count, cols):
    top = {}
    for cell in cells:
        if cell["row"] >= count:
            continue
        _require(cell["row"] + cell["row_span"] <= count, "Repeated header would cut through a rowspan")
        top[cell["row"], cell["col"]] = cell
    _require(len(_grid(top.values(), count, cols)) == count * cols, "Repeated header includes unobserved slots")
    return top


def _same_header(first, following, count, anchors):
    _require(count < min(first["num_rows"], following["num_rows"]), "Repeated header leaves no data rows")
    retained, skipped = (_header(part["cells"], count, part["num_cols"]) for part in (first, following))
    fields = ("row_span", "col_span", "text_raw", "text_corrected")
    _require(retained.keys() == skipped.keys()
             and any(cell["text_raw"].strip() for cell in retained.values())
             and all(all(cell[key] == retained[pos][key] for key in fields) for pos, cell in skipped.items()),
             "Repeated header does not exactly match the retained text and topology")
    for pos, cell in skipped.items():
        anchors[pos]["repeated_header_sources"].append(_source(following, cell))


def _numeric_literal(text):
    return any(char.isdecimal() for char in text) and all(char.isdecimal() or char.isspace() or char in "−+-.(),%‰"
                                                         for char in text)


def _extend(anchors, occupied, total, first, previous, following, boundary):
    kind, headers, columns = (boundary[key] for key in ("kind", "repeated_header_rows", "join_columns"))
    cols = following["num_cols"]
    _require(kind in BOUNDARIES and _index(headers, 0) and isinstance(columns, list)
             and all(_index(col, 0) and col < cols for col in columns) and len(columns) == len(set(columns)),
             "Invalid proposed table boundary")
    _require(not (kind == "BETWEEN_ROWS" and columns or kind == "SPANNING_CELL" and not columns),
             "Join columns must agree with the boundary kind")
    if headers:
        _same_header(first, following, headers, anchors)
    shift = total - headers - (kind == "SPLIT_ROW")
    joined = set()
    for cell in following["cells"]:
        row, col = cell["row"], cell["col"]
        if row < headers:
            continue
        target = row + shift
        if row == headers and col in columns:
            owner = occupied.get((total - 1, col))
            _require(owner is not None and owner["col"] == col and owner["col_span"] == cell["col_span"]
                     and owner["row"] + owner["row_span"] == total
                     and owner["sources"][-1]["table_id"] == previous["table_id"],
                     f"Proposed join has no matching boundary cell at column {col}")
            texts = [part["cell"]["text_raw"] for part in owner["sources"]] + [cell["text_raw"]]
            parts = [text for text in texts if text.strip()]
            _require(len(parts) < 2 or not any(_numeric_literal(part) for part in parts),
                     f"Proposed join combines a numeric literal with other content at column {col}")
            owner["sources"].append(_source(following, cell))
            owner["row_span"] = target + cell["row_span"] - owner["row"]
            joined.add(col)
        else:
            _require((target, col) not in anchors,
                     f"Split row needs an explicit cell join at column {col}")
            anchors[target, col] = _cell(following, cell, target)
    _require(joined == set(columns), "Proposed join columns include a missing first data cell")
    return shift + following["num_rows"]


def project_table(extraction, document, table_ids, boundaries):
    """Build one logical table with one disposition per observed source cell."""
    _require(isinstance(table_ids, list) and len(table_ids) >= 2
             and all(isinstance(key, str) and key for key in table_ids) and len(set(table_ids)) == len(table_ids)
             and isinstance(boundaries, list) and len(boundaries) == len(table_ids) - 1, "Invalid proposed table chain")
    _require(all(isinstance(boundary, dict) and set(boundary) == {"kind", "repeated_header_rows", "join_columns"}
                 for boundary in boundaries), "Invalid proposed table boundary fields")
    selected = set(table_ids)
    sequence = [(index, table) for index, table in enumerate(document["tables"]) if table["table_id"] in selected]
    items = [(page, item) for page in extraction["pages"] for item in page["items"] if item["id"] in selected]
    tables = {table["table_id"]: table for _, table in sequence}
    pages = {item["id"]: (page, item) for page, item in items}
    _require(tables.keys() == pages.keys() == selected and len(sequence) == len(items) == len(selected),
             "Proposed fragments are missing or duplicated in the source document")
    _require(list(tables) == table_ids and [index for index, _ in sequence] == list(range(sequence[0][0], sequence[-1][0] + 1)),
             "Proposed table fragments are not consecutive in document order")
    _require(len({tables[key]["section_id"] for key in table_ids}) == 1, "Proposed table chain crosses a document section")
    chunks = {chunk["chunk_id"]: chunk for chunk in document.get("chunks", [])}
    fragments = [_fragment(tables[key], *pages[key], chunks) for key in table_ids]
    cols = fragments[0]["num_cols"]
    _require(all(frag["num_cols"] == cols for frag in fragments), "Proposed table fragments have different column counts")
    _require(all(right["page"] == left["page"] + 1 for left, right in zip(fragments, fragments[1:])),
             "Proposed table fragments are not on consecutive physical pages")
    units = {fragment["context"]["unit"]["text_raw"] for fragment in fragments if "unit" in fragment["context"]}
    _require(len(units) <= 1, "Proposed table fragments have conflicting source units")
    first = fragments[0]
    anchors = {(cell["row"], cell["col"]): _cell(first, cell, cell["row"]) for cell in first["cells"]}
    rows = first["num_rows"]
    grid = _grid(anchors.values(), rows, cols)
    for index, boundary in enumerate(boundaries):
        rows = _extend(anchors, grid, rows, first, fragments[index], fragments[index + 1], boundary)
        grid = _grid(anchors.values(), rows, cols)
    cells = [anchors[pos] for pos in sorted(anchors)]
    covered = sum(len(cell["sources"]) + len(cell["repeated_header_sources"]) for cell in cells)
    _require(covered == sum(len(fragment["cells"]) for fragment in fragments), "Table preview lost source cell ownership")
    return {"num_rows": rows, "num_cols": cols, "cells": cells, "observed_source_cells": covered,
            "unobserved_grid_slots": rows * cols - len(grid), "boundaries": deepcopy(boundaries),
            "fragments": [{key: value for key, value in fragment.items() if key != "cells"} for fragment in fragments]}


def render_preview_html(table):
    """Render true spans and explicit unobserved slots using escaped cell text."""
    rows, cols = table["num_rows"], table["num_cols"]
    grid = _grid(table["cells"], rows, cols)
    lines = ["<table>"]
    context = [escape(chunk["text_corrected"]).replace("\n", "<br>") for fragment in table["fragments"]
               for chunk in fragment["context"].values()]
    if context:
        lines.append(f"  <caption>{'<br>'.join(dict.fromkeys(context))}</caption>")
    for row in range(rows):
        lines.append("  <tr>")
        for col in range(cols):
            cell = grid.get((row, col))
            if cell is None:
                lines.append('    <td data-state="unobserved"></td>')
            elif (cell["row"], cell["col"]) == (row, col):
                attributes = "".join(f' {name}="{cell[key]}"' for name, key in
                                     (("rowspan", "row_span"), ("colspan", "col_span")) if cell[key] > 1)
                text = "<br>".join(escape(part["cell"]["text_corrected"]).replace("\n", "<br>") for part in cell["sources"])
                lines.append(f"    <td{attributes}>{text}</td>")
        lines.append("  </tr>")
    return "\n".join([*lines, "</table>", ""])


def render_projected_markdown(table):
    """Emit each anchor once; HTML sidecars retain row/column spans."""
    grid = _grid(table["cells"], table["num_rows"], table["num_cols"])
    lines = []
    for row in range(table["num_rows"]):
        values = []
        for col in range(table["num_cols"]):
            cell = grid.get((row, col))
            text = ""
            if cell is not None and (cell["row"], cell["col"]) == (row, col):
                text = "<br>".join(part["cell"]["text_corrected"] for part in cell["sources"] if part["cell"]["text_corrected"])
                text = text.replace("|", "\\|").replace("\r\n", "\n").replace("\n", "<br>")
            values.append(text)
        lines.append("| " + " | ".join(values) + " |")
        if row == 0:
            lines.append("| " + " | ".join(["---"]*table["num_cols"]) + " |")
    return "\n".join(lines)
