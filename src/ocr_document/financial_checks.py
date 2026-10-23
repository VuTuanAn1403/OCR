"""Flag-only consistency checks for financial tables (proposal V6 C3.5b, C3.5c).

Nothing here changes a number. Arithmetic checks compare total rows with their
detail rows and the balance identity "Tổng cộng tài sản = Tổng cộng nguồn
vốn"; a mismatch marks the cells as suspicious for review. Multi-page tables
are only reported as continuation candidates; merging needs GT L5 (KP-11).

Statuses: CONSISTENT, VIOLATION (review the listed cells) and INCONCLUSIVE
(not enough evidence to judge). A VIOLATION needs positive evidence that the
compared rows add up by construction: a code formula such as
"(270 = 100 + 200)", or a "Tổng cộng/Cộng" row whose detail rows all share
one numbering level. Anything else that does not match is INCONCLUSIVE, and
every skipped table, column or unpaired total leaves an INCONCLUSIVE record so
that "no result" never looks like "nothing to check".
"""
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ocr_contracts.table import TableStructure

METHOD = "financial-checks-v2"
_DASHES = {"-", "–", "—", "−"}
_SPACE_GROUPED = re.compile(r"\d{1,3}(?: \d{3})+(?:[.,]\d+)?")
_SHAPES = {
    "vn": re.compile(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?"),
    "en": re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"),
    "plain": re.compile(r"\d+"),
}
_VN_EVIDENCE = re.compile(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+,\d{1,2}")
_EN_EVIDENCE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d{1,2}")
_YEAR = re.compile(r"(?:19|20)\d{2}")
_STRONG_TOTAL = re.compile(r"^(tổng cộng|cộng|total)\b")
_WEAK_TOTAL = re.compile(r"^tổng\b(?!\s+giám\s+đốc)")
_ASSETS_TOTAL = re.compile(r"^(tổng cộng|tổng)\s+tài sản\b")
_EQUITY_TOTAL = re.compile(r"^(tổng cộng|tổng)\s+nguồn vốn\b")
_NON_AMOUNT_HEADER = re.compile(r"\b(mã số|mã|code|stt|thuyết minh|tm|note|notes|ghi chú)\b")
_FORMULA = re.compile(r"\(?\s*(\d{2,3})\s*=\s*(\d{2,3}(?:\s*[+\-]\s*\d{2,3})+)\s*\)?")
_CODE = re.compile(r"\d{2,3}[a-z]?")
# Numbering styles of financial-statement rows; each is tried as its own level.
# A single I/V/X is a Roman numeral; other single capitals (A., B., C. Nợ phải
# trả, D. Vốn chủ sở hữu) are letter levels.
_LEVEL_STYLES = (
    ("letter_rows", re.compile(r"^(?![IVX]\s*[.)\-–]\s)[A-ZĐ]\s*[.)\-–]\s")),
    ("roman_rows", re.compile(r"^(?:[IVX]|[IVXLC]{2,})\s*[.)\-–]\s")),
    ("arabic_rows", re.compile(r"^\d{1,2}\s*[.)]\s")),
)
_CONTINUATION_MARKER = re.compile(r"tiếp theo|\(tiếp\)|continued|cộng chuyển sang|chuyển sang|mang sang",
                                  re.IGNORECASE)
_CAPTION = re.compile(r"^(bảng|biểu|table)\s*\d", re.IGNORECASE)
_UNIT_RATIO_LIMIT = 50  # totals further apart than this are in different units


def _norm(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text or "").casefold().split())


def _signed_digits(text: str) -> Optional[Tuple[bool, str]]:
    """(negative, digit token) of an amount-like cell, or None. Brackets must
    balance; space grouping is accepted only for a whole value ("1 234 567")."""
    raw = unicodedata.normalize("NFC", text or "").strip().replace(" ", " ")
    if raw.startswith("(") != raw.endswith(")"):
        return None
    negative = False
    if raw.startswith("(") and raw.endswith(")"):
        negative, raw = True, raw[1:-1].strip()
    elif raw[:1] in "+-−–" and len(raw) > 1:
        negative, raw = raw[0] != "+", raw[1:].strip()
    if _SPACE_GROUPED.fullmatch(raw):
        raw = raw.replace(" ", "")
    return (negative, raw) if re.fullmatch(r"\d[\d.,]*", raw) else None


def infer_convention(texts: Iterable[str]) -> str:
    """vn ("1.234,5"), en ("1,234.5"), plain (no separators) or ambiguous."""
    vn = en = False
    for text in texts:
        signed = _signed_digits(text)
        if signed is None:
            continue
        vn |= bool(_VN_EVIDENCE.fullmatch(signed[1]))
        en |= bool(_EN_EVIDENCE.fullmatch(signed[1]))
    if vn and en:
        return "ambiguous"
    return "vn" if vn else "en" if en else "plain"


def parse_amount(text: str, convention: str) -> Optional[Decimal]:
    """Parsed value of an amount cell, or None when it is not one amount.
    A lone dash means zero; brackets and leading minus signs mean negative."""
    raw = unicodedata.normalize("NFC", text or "").strip()
    if raw in _DASHES:
        return Decimal(0)
    if not raw or "%" in raw or convention not in _SHAPES:
        return None
    signed = _signed_digits(raw)
    if signed is None or not _SHAPES[convention].fullmatch(signed[1]):
        return None
    token = signed[1]
    if convention == "vn":
        token = token.replace(".", "").replace(",", ".")
    elif convention == "en":
        token = token.replace(",", "")
    try:
        value = Decimal(token)
    except InvalidOperation:
        return None
    return -value if signed[0] else value


class _Grid:
    """Cell texts by (row, col) at each cell's origin, split into header and
    data rows. Header rows precede the first row holding a non-year number."""

    def __init__(self, table: TableStructure):
        self.table = table
        self.cells: Dict[Tuple[int, int], str] = {}
        self.duplicates: List[Tuple[int, int]] = []
        for cell in table.cells:
            key = (cell.row_idx, cell.col_idx)
            if key in self.cells:
                self.duplicates.append(key)
            self.cells[key] = cell.text
        self.rows = sorted({r for r, _ in self.cells})
        self.cols = sorted({c for _, c in self.cells})
        self.convention = infer_convention(self.cells.values())
        first_data = next((r for r in self.rows if self._is_data_row(r)), None)
        self.header_rows = [r for r in self.rows if first_data is None or r < first_data]
        self.data_rows = [r for r in self.rows if r not in self.header_rows]

    def text(self, row: int, col: int) -> str:
        return (self.cells.get((row, col)) or "").strip()

    def value(self, row: int, col: int) -> Optional[Decimal]:
        return parse_amount(self.text(row, col), self.convention)

    def _is_data_row(self, row: int) -> bool:
        return any(self.value(row, col) is not None and not _YEAR.fullmatch(self.text(row, col))
                   for col in self.cols)

    def label(self, row: int) -> str:
        """First non-numeric text of the row."""
        for col in self.cols:
            text = self.text(row, col)
            if text and self.value(row, col) is None and "%" not in text:
                return text
        return ""

    def column_header(self, col: int) -> str:
        return _norm(" ".join(self.text(r, col) for r in self.header_rows))

    def amount_columns(self) -> Tuple[List[int], List[Dict[str, Any]]]:
        """Amount columns of the data rows, and the excluded columns with why."""
        columns, excluded = [], []
        for col in self.cols:
            values = [self.value(r, col) for r in self.data_rows if self.text(r, col)]
            numeric = [v for v in values if v is not None]
            if len(numeric) < 2 or len(numeric) < 0.5 * len(values):
                continue
            if _NON_AMOUNT_HEADER.search(self.column_header(col)):
                excluded.append({"col": col, "reason": "column header names a code or note column"})
            elif self.convention == "plain" and all(abs(v) < 1000 and v == int(v) for v in numeric):
                excluded.append({"col": col, "reason": "small ungrouped integers read as codes, not amounts"})
            else:
                columns.append(col)
        return columns, excluded

    def code(self, row: int, amount_columns: Sequence[int]) -> Optional[str]:
        for col in self.cols:
            text = self.text(row, col)
            if col not in amount_columns and _CODE.fullmatch(text):
                return text
        return None

    def formula(self, row: int) -> Optional[List[Tuple[int, str]]]:
        """Signed codes of a "(270 = 100 + 200)" formula on the row, if any."""
        for col in self.cols:
            match = _FORMULA.search(self.text(row, col))
            if match:
                terms = re.findall(r"([+\-]?)\s*(\d{2,3})", match.group(2))
                return [(-1 if sign == "-" else 1, code) for sign, code in terms]
        return None


def _tolerance(values: Sequence[Decimal]) -> Decimal:
    """Rounding slack: half a unit of the finest decimal place per summand."""
    places = max((-v.as_tuple().exponent for v in values if v.as_tuple().exponent < 0), default=0)
    return Decimal(1).scaleb(-places) * Decimal(len(values)) / 2


def _matches(total: Decimal, parts: Sequence[Decimal]) -> bool:
    return bool(parts) and abs(sum(parts) - total) <= _tolerance([total, *parts])


def _cell(grid: _Grid, row: int, col: int) -> Dict[str, Any]:
    return {"row": row, "col": col, "text_raw": grid.text(row, col)}


def table_total_checks(table: TableStructure, table_id: str) -> List[Dict[str, Any]]:
    grid = _Grid(table)
    base = {"check": "total_row", "table_id": table_id}
    if grid.duplicates:
        return [{**base, "status": "INCONCLUSIVE", "reason": "duplicate cell positions",
                 "cells": [{"row": r, "col": c} for r, c in grid.duplicates]}]
    if grid.convention == "ambiguous":
        return [{**base, "status": "INCONCLUSIVE", "reason": "mixed Vietnamese and English number grouping"}]
    columns, excluded = grid.amount_columns()
    totals = [r for r in grid.data_rows if _STRONG_TOTAL.match(_norm(grid.label(r)))
              or _WEAK_TOTAL.match(_norm(grid.label(r)))]
    if totals and not columns:
        return [{**base, "status": "INCONCLUSIVE", "reason": "no amount columns detected",
                 "excluded_columns": excluded}]
    results: List[Dict[str, Any]] = []
    previous = None
    for row in totals:
        block = [r for r in grid.data_rows if (previous is None or r > previous) and r < row]
        previous = row
        for col in columns:
            results.append(_check_block(grid, table_id, row, col, block, columns))
    return results + _suspect_amount_cells(grid, table_id, columns)


def _check_block(grid: _Grid, table_id: str, total_row: int, col: int, block: List[int],
                 columns: Sequence[int]) -> Dict[str, Any]:
    label = grid.label(total_row)
    base = {"check": "total_row", "table_id": table_id, "row": total_row, "col": col, "label": label}
    total = grid.value(total_row, col)
    if total is None:
        return {**base, "status": "INCONCLUSIVE", "reason": "total cell is blank or not a number"}

    formula = grid.formula(total_row)
    if formula:
        rows_by_code = {grid.code(r, columns): r for r in grid.data_rows}
        rows = [(sign, rows_by_code.get(code)) for sign, code in formula]
        if all(r is not None and grid.value(r, col) is not None for _, r in rows):
            parts = [sign * grid.value(r, col) for sign, r in rows]
            if _matches(total, parts):
                return {**base, "status": "CONSISTENT", "decomposition": "code_formula"}
            return _violation(grid, base, total, parts, [total_row] + [r for _, r in rows], col)

    detail = [r for r in block if grid.text(r, col) or grid.label(r)]
    if len(detail) < 2:
        return {**base, "status": "INCONCLUSIVE", "reason": "fewer than two detail rows"}
    values = {r: grid.value(r, col) for r in detail}
    non_numeric = [_cell(grid, r, col) for r in detail if values[r] is None]
    labels = {r: grid.label(r).strip() for r in detail}
    candidates = [("all_detail_rows", detail)] + [
        (name, [r for r in detail if pattern.match(labels[r])]) for name, pattern in _LEVEL_STYLES]
    # Each decomposition only needs its own rows to be numeric, so a malformed
    # sub-row cannot hide a verifiable sum; the malformed cells are reported.
    for name, rows in candidates:
        if len(rows) >= 2 and all(values[r] is not None for r in rows) and _matches(total, [values[r] for r in rows]):
            return {**base, "status": "CONSISTENT", "decomposition": name, "rows_used": len(rows),
                    "detail_rows": len(detail), "non_numeric_cells": non_numeric}
    if non_numeric:
        return {**base, "status": "INCONCLUSIVE", "reason": "blank or non-numeric detail cell",
                "non_numeric_cells": non_numeric}
    # Positive evidence that the block adds up by construction: a "Tổng cộng"
    # row whose detail rows all share one numbering level.
    flat = _STRONG_TOTAL.match(_norm(label)) and any(rows == detail for _, rows in candidates[1:])
    if not flat:
        return {**base, "status": "INCONCLUSIVE",
                "reason": "no evidence that the detail rows sum to this total (hierarchy or label unknown)"}
    return _violation(grid, base, total, [values[r] for r in detail], [total_row] + detail, col)


def _violation(grid: _Grid, base: Dict[str, Any], total: Decimal, parts: Sequence[Decimal],
               rows: Sequence[int], col: int) -> Dict[str, Any]:
    expected = sum(parts)
    return {**base, "status": "VIOLATION", "expected": str(expected), "found": str(total),
            "difference": str(total - expected), "suspicious_cells": [_cell(grid, r, col) for r in rows]}


def _suspect_amount_cells(grid: _Grid, table_id: str, columns: Sequence[int]) -> List[Dict[str, Any]]:
    """Cells of an amount column that look numeric but do not parse ("6O.000"):
    likely OCR damage, so the cell needs review even when a total matched."""
    suspect = []
    for row in grid.data_rows:
        for col in columns:
            text = grid.text(row, col)
            digits = sum(c.isdigit() for c in text)
            letters = sum(c.isalpha() for c in text)
            if (text and grid.value(row, col) is None and "%" not in text and digits >= 2 and letters <= 2
                    and not _multiple_amounts(text, grid.convention)):
                suspect.append(_cell(grid, row, col))
    if not suspect:
        return []
    return [{"check": "amount_cell", "table_id": table_id, "status": "VIOLATION",
             "reason": "amount-column cell does not parse as a number (possible OCR damage)",
             "suspicious_cells": suspect}]


def _multiple_amounts(text: str, convention: str) -> bool:
    tokens = (text or "").split()
    return (len(tokens) >= 2 and parse_amount(text, convention) is None
            and all(parse_amount(token, convention) is not None for token in tokens))


def multi_value_cells(table: TableStructure, table_id: str) -> List[Dict[str, Any]]:
    """A cell holding several amounts ("(1.079,0) 11,1") means rows were merged
    during extraction; the table structure needs review."""
    grid = _Grid(table)
    if grid.convention == "ambiguous":
        return []
    merged = [_cell(grid, row, col) for (row, col), text in sorted(grid.cells.items())
              if _multiple_amounts(text, grid.convention)]
    if not merged:
        return []
    return [{"check": "single_value_cell", "table_id": table_id, "status": "VIOLATION",
             "reason": "cells hold several amounts; rows were likely merged during extraction",
             "suspicious_cells": merged}]


def _identity_rows(tables: Sequence[Tuple[str, TableStructure]], pattern: re.Pattern) -> List[Dict[str, Any]]:
    found = []
    for order, (table_id, table) in enumerate(tables):
        grid = _Grid(table)
        for row in grid.data_rows:
            if pattern.match(_norm(grid.label(row))):
                found.append({"order": order, "table_id": table_id, "grid": grid, "row": row, "page": table.page})
    return found


def balance_identity_checks(tables: Sequence[Tuple[str, TableStructure]]) -> List[Dict[str, Any]]:
    """Pair each "tổng cộng nguồn vốn" row with the nearest preceding unpaired
    "tổng cộng tài sản" row on the same or the previous page; unpaired totals
    are reported as INCONCLUSIVE rather than dropped."""
    assets = _identity_rows(tables, _ASSETS_TOTAL)
    equity = _identity_rows(tables, _EQUITY_TOTAL)
    results: List[Dict[str, Any]] = []
    paired = set()
    for right in equity:
        candidates = [a for a in assets if id(a) not in paired
                      and (a["order"], a["row"]) < (right["order"], right["row"])
                      and 0 <= right["page"] - a["page"] <= 1]
        if not candidates:
            results.append({"check": "balance_identity", "status": "INCONCLUSIVE",
                            "equity": {"table_id": right["table_id"], "row": right["row"]},
                            "reason": "no preceding tổng cộng tài sản row on the same or previous page"})
            continue
        left = max(candidates, key=lambda a: (a["order"], a["row"]))
        paired.add(id(left))
        results.append(_compare_identity(left, right))
    for left in assets:
        if id(left) not in paired:
            results.append({"check": "balance_identity", "status": "INCONCLUSIVE",
                            "assets": {"table_id": left["table_id"], "row": left["row"]},
                            "reason": "no following tổng cộng nguồn vốn row on the same or next page"})
    return results


def _compare_identity(left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
    base = {"check": "balance_identity", "assets": {"table_id": left["table_id"], "row": left["row"]},
            "equity": {"table_id": right["table_id"], "row": right["row"]}}
    lgrid, rgrid = left["grid"], right["grid"]
    if lgrid.convention != rgrid.convention or "ambiguous" in (lgrid.convention, rgrid.convention):
        return {**base, "status": "INCONCLUSIVE", "reason": "number conventions differ"}
    lcols, rcols = lgrid.amount_columns()[0], rgrid.amount_columns()[0]
    if lgrid is rgrid:
        pairs = [(c, c) for c in lcols]
    else:
        lheads = [lgrid.column_header(c) for c in lcols]
        rheads = [rgrid.column_header(c) for c in rcols]
        # Columns of different tables are matched by their period header only.
        if not lcols or lheads != rheads or not all(lheads):
            return {**base, "status": "INCONCLUSIVE", "reason": "amount columns cannot be aligned by period header"}
        pairs = list(zip(lcols, rcols))
    mismatches, compared = [], 0
    for lc, rc in pairs:
        a, b = lgrid.value(left["row"], lc), rgrid.value(right["row"], rc)
        if a is None and b is None:
            continue
        if a is None or b is None:
            return {**base, "status": "INCONCLUSIVE", "reason": "a period is blank on one side only"}
        small, large = sorted((abs(a), abs(b)))
        if small and large / small > _UNIT_RATIO_LIMIT:
            return {**base, "status": "INCONCLUSIVE", "reason": "values differ by orders of magnitude (units)"}
        compared += 1
        if abs(a - b) > _tolerance([a, b]):
            mismatches.append((lc, a, rc, b))
    if not compared:
        return {**base, "status": "INCONCLUSIVE", "reason": "no comparable amounts"}
    if not mismatches:
        return {**base, "status": "CONSISTENT", "columns_compared": compared}
    return {**base, "status": "VIOLATION", "suspicious_cells": [
        cell for lc, a, rc, b in mismatches for cell in (
            {"table_id": left["table_id"], "row": left["row"], "col": lc, "value": str(a)},
            {"table_id": right["table_id"], "row": right["row"], "col": rc, "value": str(b)})]}


def continuation_candidate(previous: TableStructure, previous_box: Sequence[float], previous_height: float,
                           following: TableStructure, following_box: Sequence[float], following_height: float,
                           between_texts: Sequence[str], heading_between: bool) -> Optional[Dict[str, Any]]:
    """Report whether `following` (next page) may continue `previous`.
    Required: same column count and no heading or new caption in between, a
    continuity signal, and a repeated header or a next table starting with
    data. Conditions that cannot be verified are listed; nothing is merged."""
    if heading_between or previous.num_cols != following.num_cols or previous.num_cols < 2:
        return None
    if any(_CAPTION.match(text.strip()) for text in between_texts):
        return None
    before, after = _Grid(previous), _Grid(following)
    first_prev = [_norm(before.text(before.rows[0], c)) for c in before.cols] if before.rows else []
    first_next = [_norm(after.text(after.rows[0], c)) for c in after.cols] if after.rows else []
    header_repeated = bool(first_prev) and first_prev == first_next
    next_starts_with_data = bool(after.rows) and after.rows[0] in after.data_rows
    signals = []
    if any(_CONTINUATION_MARKER.search(text) for text in [*between_texts, " ".join(first_next)]):
        signals.append("continuation_marker")
    # The geometric signal needs both page heights; unknown heights skip it.
    if (previous_height > 0 and following_height > 0 and len(previous_box) == 4 and len(following_box) == 4
            and previous_box[3] >= 0.85 * previous_height and following_box[1] <= 0.25 * following_height):
        signals.append("previous_touches_bottom_next_starts_top")
    if not signals or not (header_repeated or next_starts_with_data):
        return None
    unverified = []
    if not header_repeated:
        unverified.append("unit_and_period")  # no repeated header to compare
    if between_texts:
        unverified.append("text_between_tables")
    return {"status": "CANDIDATE", "method": METHOD,
            "signals": signals + (["header_repeated"] if header_repeated else ["next_starts_with_data"]),
            "unverified": unverified, "merged": False}
