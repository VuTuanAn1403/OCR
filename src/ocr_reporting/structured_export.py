"""DOCX and XLSX exports that keep table structure (V8-130).

Input is a finished document's `document.json` (sections, chunks, tables). The
DOCX has headings, paragraphs and list items in reading order, and every table
as a real Word table: horizontal merges are `gridSpan`, vertical merges are
`vMerge`. The XLSX has an index sheet and one sheet per table with each cell
at its address and every span as a merged range. Neither file flattens a table.

Every cell keeps its address and its text. When a cell's address lies inside an
earlier cell's span, that span is shrunk; when two cells share one address their
texts are joined; a span that would cover another cell becomes 1x1. Each case
is reported as a warning. Numbers stay strings exactly as recognized.
`docx_table_grids` and `xlsx_table_grids` read the files back, so a caller
can prove the round trip instead of assuming it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from typing import Any, Dict, Iterable, List, Optional, Tuple
from xml.etree import ElementTree
from xml.sax.saxutils import escape
import zipfile

from openpyxl import Workbook, load_workbook

TEXT_FIELDS = ("text_corrected", "text_raw")
NL = chr(10)
_ALLOWED_CONTROL = (chr(9), chr(10), chr(13))
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
Grid = Dict[Tuple[int, int], Tuple[str, int, int]]


def clean_text(value: Any) -> str:
    """Text as XML 1.0 can carry it: other control characters are removed."""
    text = "" if value is None else str(value)
    return "".join(char for char in text if char in _ALLOWED_CONTROL or ord(char) >= 0x20).replace(chr(13), "")


def cell_text(cell: Dict[str, Any], text_field: str) -> str:
    if text_field not in TEXT_FIELDS:
        raise ValueError(f"text_field must be one of {TEXT_FIELDS}")
    value = cell.get(text_field)
    if value is None and text_field == "text_corrected":
        value = cell.get("text_raw")
    if value is None:
        value = cell.get("text")
    return clean_text(value)


@dataclass
class TableLayout:
    rows: int
    cols: int
    anchors: Dict[Tuple[int, int], Dict[str, Any]] = field(default_factory=dict)
    owner: Dict[Tuple[int, int], Tuple[int, int]] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def grid(self) -> Grid:
        return {position: (anchor["text"], anchor["rs"], anchor["cs"]) for position, anchor in self.anchors.items()
                if anchor["text"] or anchor["rs"] > 1 or anchor["cs"] > 1}


def _span(value: Any) -> int:
    try:
        return max(1, int(value or 1))
    except (TypeError, ValueError):
        return 1


def _shrink(layout: TableLayout, owner: Tuple[int, int], position: Tuple[int, int]) -> None:
    """Cut the owner's rectangle just before `position` (rows first), so it stays a rectangle."""
    anchor = layout.anchors[owner]
    if position[0] > owner[0]:
        anchor["rs"] = position[0] - owner[0]
    else:
        anchor["cs"] = position[1] - owner[1]
    for key in [key for key, value in layout.owner.items() if value == owner]:
        if not (owner[0] <= key[0] < owner[0] + anchor["rs"] and owner[1] <= key[1] < owner[1] + anchor["cs"]):
            del layout.owner[key]


def table_layout(table: Dict[str, Any], text_field: str = "text_corrected") -> TableLayout:
    """Place every cell at its own address; collisions are reported, text is never dropped."""
    cells = []
    for index, cell in enumerate(table.get("cells") or []):
        row = cell.get("row", cell.get("row_idx"))
        col = cell.get("col", cell.get("col_idx"))
        cells.append((index, row, col, cell))
    layout = TableLayout(rows=max(0, int(table.get("num_rows") or 0)), cols=max(0, int(table.get("num_cols") or 0)))
    table_id = table.get("table_id", "?")
    for index, row, col, cell in sorted(cells, key=lambda item: (item[1] if isinstance(item[1], int) else -1,
                                                                 item[2] if isinstance(item[2], int) else -1,
                                                                 item[0])):
        text = cell_text(cell, text_field).strip(NL)  # edge newlines carry no meaning
        if not isinstance(row, int) or not isinstance(col, int) or row < 0 or col < 0:
            layout.warnings.append(f"{table_id}: cell {index} has no valid address; text appended below the table")
            row, col = layout.rows, 0
        rs, cs = _span(cell.get("row_span")), _span(cell.get("col_span"))
        if row + rs > layout.rows or col + cs > layout.cols:
            layout.warnings.append(f"{table_id}: cell ({row},{col}) extends the declared size; grid enlarged")
            layout.rows, layout.cols = max(layout.rows, row + rs), max(layout.cols, col + cs)
        owner = layout.owner.get((row, col))
        if owner == (row, col):  # two cells at one anchor: one cell, both texts
            target = layout.anchors[owner]
            target["text"] = target["text"] + (NL if target["text"] and text else "") + text
            layout.warnings.append(f"{table_id}: two cells at ({row},{col}); texts joined")
            continue
        if owner is not None:  # an earlier span covers this address: shrink it, keep every address
            _shrink(layout, owner, (row, col))
            layout.warnings.append(f"{table_id}: span of cell {owner} shrunk so cell ({row},{col}) keeps its address")
        covered = [(r, c) for r in range(row, row + rs) for c in range(col, col + cs)]
        if any(position in layout.owner for position in covered):
            layout.warnings.append(f"{table_id}: span of cell ({row},{col}) overlaps another cell; kept as 1x1")
            rs, cs, covered = 1, 1, [(row, col)]
        layout.anchors[(row, col)] = {"text": text, "rs": rs, "cs": cs}
        for position in covered:
            layout.owner[position] = (row, col)
    return layout


# --- DOCX -----------------------------------------------------------------

def _run_xml(text: str) -> str:
    parts = text.split(NL)
    runs = []
    for index, part in enumerate(parts):
        if index:
            runs.append("<w:br/>")
        runs.append(f'<w:t xml:space="preserve">{escape(part)}</w:t>')
    return f"<w:r>{''.join(runs)}</w:r>"


def _paragraph(text: str, style: Optional[str] = None) -> str:
    properties = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{properties}{_run_xml(text) if text else ''}</w:p>"


def _table_xml(layout: TableLayout) -> str:
    if layout.rows == 0 or layout.cols == 0:
        return ""
    width = max(600, 9000 // layout.cols)
    rows = []
    for r in range(layout.rows):
        cells, c = [], 0
        while c < layout.cols:
            owner = layout.owner.get((r, c))
            if owner is None:
                cells.append("<w:tc><w:p/></w:tc>")
                c += 1
                continue
            anchor = layout.anchors[owner]
            span = f'<w:gridSpan w:val="{anchor["cs"]}"/>' if anchor["cs"] > 1 else ""
            if owner == (r, c):
                merge = '<w:vMerge w:val="restart"/>' if anchor["rs"] > 1 else ""
                body = "".join(_paragraph(line) for line in anchor["text"].split(NL)) if anchor["text"] else "<w:p/>"
                cells.append(f"<w:tc><w:tcPr>{span}{merge}</w:tcPr>{body}</w:tc>")
            else:  # continuation of a vertical merge started in an earlier row
                cells.append(f"<w:tc><w:tcPr>{span}<w:vMerge/></w:tcPr><w:p/></w:tc>")
            c = owner[1] + anchor["cs"]
        rows.append(f"<w:tr>{''.join(cells)}</w:tr>")
    grid = "".join(f'<w:gridCol w:w="{width}"/>' for _ in range(layout.cols))
    return ('<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/><w:tblW w:w="0" w:type="auto"/></w:tblPr>'
            f"<w:tblGrid>{grid}</w:tblGrid>{''.join(rows)}</w:tbl><w:p/>")


_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    f'<w:styles xmlns:w="{W}">'
    '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
    + "".join(f'<w:style w:type="paragraph" w:styleId="Heading{level}"><w:name w:val="heading {level}"/>'
              f'<w:basedOn w:val="Normal"/><w:pPr><w:outlineLvl w:val="{level - 1}"/></w:pPr>'
              f'<w:rPr><w:b/><w:sz w:val="{36 - 3 * level}"/></w:rPr></w:style>' for level in range(1, 7))
    + '<w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/><w:tblPr><w:tblBorders>'
    + "".join(f'<w:{side} w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
              for side in ("top", "left", "bottom", "right", "insideH", "insideV"))
    + "</w:tblBorders></w:tblPr></w:style></w:styles>")
_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '<Override PartName="/word/styles.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>')
_ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    'Target="word/document.xml"/></Relationships>')
_DOCUMENT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
    'Target="styles.xml"/></Relationships>')


def _zip(parts: Iterable[Tuple[str, str]]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in parts:
            info = zipfile.ZipInfo(name, date_time=_FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, text.encode("utf-8"))
    return buffer.getvalue()


def docx_bytes(document: Dict[str, Any], text_field: str = "text_corrected") -> Tuple[bytes, List[str]]:
    """Reading-order DOCX of a document.json; deterministic for identical input."""
    sections = {section.get("section_id"): section for section in document.get("sections") or []}
    tables = {table.get("chunk_id"): table for table in document.get("tables") or []}
    body, warnings, emitted = [], [], set()
    for chunk in document.get("chunks") or []:
        section_id = chunk.get("section_id")
        if section_id in sections and section_id not in emitted:
            emitted.add(section_id)
            section = sections[section_id]
            title = clean_text(section.get("title"))
            if title:
                level = min(6, max(1, int(section.get("level") or 1)))
                body.append(_paragraph(title, f"Heading{level}"))
        kind = chunk.get("type")
        if kind == "table":
            table = tables.get(chunk.get("chunk_id"))
            if table is None:
                warnings.append(f"{chunk.get('chunk_id')}: table chunk without a table record")
                continue
            layout = table_layout(table, text_field)
            warnings.extend(layout.warnings)
            body.append(_table_xml(layout))
        elif kind == "image":
            asset = clean_text(chunk.get("asset") or chunk.get("chunk_id"))
            body.append(_paragraph(f"[Hình: {asset}]"))
        else:
            text = cell_text(chunk, text_field)
            if text:
                body.append(_paragraph(("• " if kind == "list_item" else "") + text))
    xml = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="{W}"><w:body>'
           f"{''.join(body)}<w:sectPr/></w:body></w:document>")
    parts = [("[Content_Types].xml", _CONTENT_TYPES), ("_rels/.rels", _ROOT_RELS),
             ("word/_rels/document.xml.rels", _DOCUMENT_RELS), ("word/styles.xml", _STYLES),
             ("word/document.xml", xml)]
    return _zip(parts), warnings


def docx_table_grids(data: bytes) -> List[Grid]:
    """Read every Word table back as {(row, col): (text, row_span, col_span)}."""
    with zipfile.ZipFile(BytesIO(data)) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    q = lambda tag: f"{{{W}}}{tag}"  # noqa: E731
    grids = []
    for table in root.iter(q("tbl")):
        grid: Dict[Tuple[int, int], List[Any]] = {}
        for r, row in enumerate(table.findall(q("tr"))):
            c = 0
            for cell in row.findall(q("tc")):
                properties = cell.find(q("tcPr"))
                span_element = properties.find(q("gridSpan")) if properties is not None else None
                merge = properties.find(q("vMerge")) if properties is not None else None
                cs = int(span_element.get(q("val"))) if span_element is not None else 1
                if merge is not None and merge.get(q("val"), "continue") == "continue":
                    owner = next(position for position in sorted(grid, reverse=True)
                                 if position[1] == c and position[0] + grid[position][1] == r)
                    grid[owner][1] += 1
                else:
                    paragraphs = []
                    for paragraph in cell.findall(q("p")):
                        pieces = []
                        for node in paragraph.iter():
                            if node.tag == q("t"):
                                pieces.append(node.text or "")
                            elif node.tag == q("br"):
                                pieces.append(NL)
                        paragraphs.append("".join(pieces))
                    text = NL.join(paragraphs).strip(NL) if any(paragraphs) else ""
                    grid[(r, c)] = [text, 1, cs]
                c += cs
        grids.append({position: (value[0], value[1], value[2]) for position, value in grid.items()
                      if value[0] or value[1] > 1 or value[2] > 1})
    return grids


# --- XLSX -----------------------------------------------------------------

def sheet_name(index: int) -> str:
    return f"T{index:04d}"


def xlsx_bytes(document: Dict[str, Any], text_field: str = "text_corrected") -> Tuple[bytes, List[str]]:
    """Index sheet plus one sheet per table, cells at their addresses, spans as merged ranges."""
    book = Workbook()
    index_sheet = book.active
    index_sheet.title = "Index"
    index_sheet.append(["sheet", "table_id", "pages", "rows", "cols", "engine", "needs_review", "warnings"])
    warnings: List[str] = []
    for number, table in enumerate(document.get("tables") or [], start=1):
        layout = table_layout(table, text_field)
        warnings.extend(layout.warnings)
        sheet = book.create_sheet(sheet_name(number))
        for (r, c), anchor in sorted(layout.anchors.items()):
            target = sheet.cell(row=r + 1, column=c + 1)
            if anchor["text"]:
                target.value = anchor["text"]
                target.number_format = "@"  # keep recognized numbers as text, never reformatted
            if anchor["rs"] > 1 or anchor["cs"] > 1:
                sheet.merge_cells(start_row=r + 1, start_column=c + 1,
                                  end_row=r + anchor["rs"], end_column=c + anchor["cs"])
        pages = ",".join(str(page) for page in table.get("pages") or [])
        index_sheet.append([sheet.title, table.get("table_id"), pages, layout.rows, layout.cols,
                            table.get("engine"), bool(table.get("needs_review")), len(layout.warnings)])
    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue(), warnings


def xlsx_table_grids(data: bytes) -> Dict[str, Grid]:
    book = load_workbook(BytesIO(data))
    try:
        grids = {}
        for sheet in book.worksheets:
            if sheet.title == "Index":
                continue
            spans = {(rng.min_row - 1, rng.min_col - 1): (rng.max_row - rng.min_row + 1, rng.max_col - rng.min_col + 1)
                     for rng in sheet.merged_cells.ranges}
            grid: Grid = {}
            for row in sheet.iter_rows():
                for cell in row:
                    if type(cell).__name__ == "MergedCell":
                        continue
                    position = (cell.row - 1, cell.column - 1)
                    rs, cs = spans.get(position, (1, 1))
                    text = "" if cell.value is None else str(cell.value)
                    if text or rs > 1 or cs > 1:
                        grid[position] = (text, rs, cs)
            for position, (rs, cs) in spans.items():
                grid.setdefault(position, ("", rs, cs))
            grids[sheet.title] = grid
        return grids
    finally:
        book.close()


def round_trip(document: Dict[str, Any], docx: bytes, xlsx: bytes,
               text_field: str = "text_corrected") -> Dict[str, Any]:
    """Compare every table's grid with what the DOCX and XLSX files hold."""
    tables = document.get("tables") or []
    layouts = [table_layout(table, text_field) for table in tables]
    by_chunk = {table.get("chunk_id"): layout for table, layout in zip(tables, layouts)}
    # The DOCX holds the tables reached through table chunks, in reading order; an empty grid writes none.
    in_docx = [by_chunk[chunk.get("chunk_id")] for chunk in document.get("chunks") or []
               if chunk.get("type") == "table" and chunk.get("chunk_id") in by_chunk]
    expected_docx = [layout.grid() for layout in in_docx if layout.rows and layout.cols]
    docx_read = docx_table_grids(docx)
    xlsx_read = xlsx_table_grids(xlsx)
    docx_mismatches = [index for index, (want, got) in enumerate(zip(expected_docx, docx_read)) if want != got]
    xlsx_mismatches = [sheet_name(number) for number, layout in enumerate(layouts, start=1)
                       if xlsx_read.get(sheet_name(number)) != layout.grid()]
    count_ok = len(docx_read) == len(expected_docx) and len(xlsx_read) == len(layouts)
    return {"tables": len(layouts), "docx_tables": len(docx_read), "xlsx_sheets": len(xlsx_read),
            "table_counts_match": count_ok, "docx_mismatches": docx_mismatches, "xlsx_mismatches": xlsx_mismatches,
            "status": "ROUND_TRIP_OK" if count_ok and not docx_mismatches and not xlsx_mismatches
            else "ROUND_TRIP_FAILED"}
