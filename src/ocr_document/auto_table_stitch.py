"""Conservative automatic projections; physical extraction cells stay immutable."""
from statistics import median
import re

from ocr_contracts.table import TableCell, TableStructure
from .financial_checks import continuation_candidate
from .table_stitch import _grid, _header, _numeric_literal, project_table
from .source_identity import valid_bbox

METHOD = "table-stitch-auto-v1"
_HEADER_LABEL = re.compile(r"\b(?:chỉ tiêu|nội dung|thuyết minh|mã số|tài sản|nguồn vốn|"
                           r"số đầu|số cuối|đầu năm|cuối năm|tên|giá trị|tỷ lệ|năm|kỳ|ngày|stt)\b", re.I)


def _source_table(page, item):
    return TableStructure(table_id=item["id"], page=page["page"], bbox=item["bbox"],
                          num_rows=item["num_rows"], num_cols=item["num_cols"], engine=item["engine"],
                          cells=[TableCell(row_idx=c["row"], col_idx=c["col"], row_span=c["row_span"],
                                           col_span=c["col_span"], text=c["text_raw"], bbox=c["bbox"],
                                           column_header=c.get("column_header"), row_header=c.get("row_header"),
                                           row_section=c.get("row_section"))
                                 for c in item["cells"]])


def _header_rows(left, right):
    count = 0
    for candidate in range(1, min(4, left["num_rows"], right["num_rows"])):
        try:
            a, b = (_header(table["cells"], candidate, table["num_cols"]) for table in (left, right))
        except ValueError:
            # A shorter prefix may cut a valid rowspan. Only a complete,
            # source-observed grid can establish the repeated header below.
            continue
        roles = [c.get("column_header") for c in (*a.values(), *b.values())]
        known_roles = any(role is not None for role in roles)
        if known_roles and not all(role is True for role in roles):
            break  # A model-labelled data/mixed row cannot become a header by equality.
        # Equality alone is not header evidence: repeated zero/value rows are
        # real observations. A bare year can also be a monetary value. With no
        # explicit header-role evidence, retain such a row for review.
        if not known_roles and (any(_numeric_literal(c["text_raw"].strip()) for c in a.values())
                or any(c["col"] == 0 and c["text_raw"].strip() and not _HEADER_LABEL.search(c["text_raw"])
                       for c in a.values())):
            break
        fields = ("row_span", "col_span", "text_raw", "text_corrected")
        if a.keys() != b.keys() or not all(all(cell[k] == a[pos][k] for k in fields) for pos, cell in b.items()):
            break
        if sum(bool(cell["text_raw"].strip()) for cell in a.values()) < 2:
            break
        count = candidate
    return count


def _column_geometry(item):
    box = item["bbox"]
    if not valid_bbox(box):
        raise ValueError("missing_table_geometry")
    positions = []
    for col in range(item["num_cols"]):
        cells = [c for c in item["cells"] if c["col"] == col and c["col_span"] == 1
                 and c.get("bbox_source") == "cell" and valid_bbox(c["bbox"])]
        if not cells:
            raise ValueError("unobserved_column_geometry")
        positions.append((median((c["bbox"][0]-box[0])/(box[2]-box[0]) for c in cells),
                          median((c["bbox"][2]-box[0])/(box[2]-box[0]) for c in cells)))
    return positions


def _boundary(left, right, headers):
    """Infer a cut row only with complementary cells and a lowercase continuation."""
    previous = {c["col"]: c for c in left["cells"] if c["row"] == left["num_rows"]-1}
    following = {c["col"]: c for c in right["cells"] if c["row"] == headers}
    common = sorted(set(previous) & set(following))
    textual = [col for col in common if any(c.isalpha() for c in previous[col]["text_raw"])
               and any(c.isalpha() for c in following[col]["text_raw"])]
    labelled = [col for col in textual if any(c["col"] == col and c["row"] < headers
                and re.search(r"\b(?:chỉ tiêu|nội dung|khoản mục|diễn giải|tên)\b", c["text_raw"], re.I)
                for c in left["cells"])]
    if len(labelled) == 1:
        label_col = labelled[0]
    elif len(textual) == 1:
        label_col = textual[0]
    else:
        raise ValueError("ambiguous_boundary_label_column")
    a, b = previous.get(label_col), following.get(label_col)
    if a is None or b is None:
        raise ValueError("missing_boundary_label_cell")
    before, after = a["text_raw"].strip(), b["text_raw"].strip()
    split_hint = bool(before and after and after[:1].islower() and not before.endswith((".", ";", ":", "!", "?")))
    if not split_hint:
        if before.casefold().startswith(("tổng cộng", "cộng", "total")):
            raise ValueError("previous_table_ends_with_total")
        if not before or not after or not any(_numeric_literal(c["text_raw"].strip()) for col, c in previous.items() if col != label_col):
            raise ValueError("ambiguous_row_boundary")
        return {"kind": "BETWEEN_ROWS", "repeated_header_rows": headers, "join_columns": []}
    _grid(left["cells"], left["num_rows"], left["num_cols"])
    _grid(right["cells"], right["num_rows"], right["num_cols"])
    if any(c["row_span"] != 1 for c in (*previous.values(), *following.values())):
        raise ValueError("spanning_boundary_requires_review")
    if any(previous[col]["text_raw"].strip() and following[col]["text_raw"].strip()
           for col in common if col != label_col):
        raise ValueError("split_row_conflicting_other_cells")
    if not any(_numeric_literal(c["text_raw"].strip()) for row in (previous, following)
               for col, c in row.items() if col != label_col):
        raise ValueError("split_row_has_no_numeric_values")
    covered = {col for row in (previous, following) for c in row.values()
               for col in range(c["col"], c["col"]+c["col_span"])}
    if covered != set(range(left["num_cols"])):
        raise ValueError("unobserved_boundary_columns")
    columns = sorted(set(previous) & set(following))
    if any(previous[col]["col_span"] != following[col]["col_span"] for col in columns):
        raise ValueError("boundary_column_span_differs")
    return {"kind": "SPLIT_ROW", "repeated_header_rows": headers, "join_columns": columns}


def build_auto_stitches(extraction, document):
    """Emit source-owned logical tables and explain every adjacent-page abstention."""
    tables = document["tables"]
    source = {item["id"]: (page, item) for page in extraction["pages"] for item in page["items"] if item["kind"] == "t"}
    chunks = document.get("chunks", [])
    chunk_positions = {chunk["chunk_id"]: n for n, chunk in enumerate(chunks)}
    decisions, groups = [], []
    for left, right in zip(tables, tables[1:]):
        if len(left["pages"]) != 1 or right["pages"] != [left["pages"][0]+1]:
            continue
        ids = [left["table_id"], right["table_id"]]
        decision = {"table_ids": ids, "status": "KEPT_SEPARATE", "needs_review": True}
        decisions.append(decision)
        try:
            if left["section_id"] != right["section_id"] or left["num_cols"] != right["num_cols"]:
                raise ValueError("section_or_column_count_differs")
            if left.get("table_orientation") != right.get("table_orientation"):
                raise ValueError("table_orientation_differs_or_unavailable")
            if right.get("caption"):
                raise ValueError("following_table_has_new_caption")
            li, ri = chunk_positions[left["chunk_id"]], chunk_positions[right["chunk_id"]]
            if ri != li+1:
                raise ValueError("intervening_document_content")
            left_page, left_item = source[ids[0]]
            right_page, right_item = source[ids[1]]
            signal = continuation_candidate(
                _source_table(left_page, left_item), left_item["bbox"], left_page["height"],
                _source_table(right_page, right_item), right_item["bbox"], right_page["height"], [], False)
            if not signal or signal.get("unverified"):
                raise ValueError("continuation_not_verified_by_signals")
            if left_page["coordinate_space"] != right_page["coordinate_space"]:
                raise ValueError("coordinate_space_differs")
            geometry = [_column_geometry(item) for item in (left_item, right_item)]
            if any(abs(a-b) > .04 for x, y in zip(*geometry) for a, b in zip(x, y)):
                raise ValueError("column_geometry_differs")
            headers = _header_rows(left, right)
            if not headers:
                raise ValueError("exact_repeated_header_required")
            boundary = _boundary(left, right, headers)
            existing = groups[-1] if groups and groups[-1]["table_ids"][-1] == ids[0] else None
            chain = [*existing["table_ids"], ids[1]] if existing else ids
            boundaries = [*existing["projection"]["boundaries"], boundary] if existing else [boundary]
            projected = project_table(extraction, document, chain, boundaries)
            entry = {"logical_table_id": chain[0]+":logical", "table_ids": chain,
                     "status": "AUTOMATIC_REQUIRES_REVIEW", "needs_review": True, "projection": projected}
            if existing:
                groups[-1] = entry
            else:
                groups.append(entry)
            decision.update(status="PROJECTED", boundary=boundary, reason="exact_header_geometry_complementary_rows")
        except (ValueError, KeyError) as exc:
            decision["reason"] = str(exc)
    for index, group in enumerate(groups, 1):
        group["html_path"] = f"structures/tables/logical-{index:04d}.html"
    return {"method": METHOD, "status": "COMPLETED", "acceptance": "NOT_EVALUATED",
            "logical_tables": groups, "decisions": decisions}
