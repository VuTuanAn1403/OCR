"""Separate Tier 2/Pending projections; a pending value never becomes a final total."""
import json

from openpyxl.cell import WriteOnlyCell

TIER_SHEETS = ("Dem_Tier2", "Cho_duyet", "Tong_sau_duyet", "Cho_duyet_dong_bi_loai", "Ung_vien_chu_so",
               "Trich_dan_chi_tiet", "Trich_dan_Tier2")
# V8-100 review-only columns: keywords in OCR lines the A1 gate kept out (Q6 B) and alphanumeric
# look-alike candidates such as 020 for O2O (Q7 A). Never added to Tong_sau_duyet.
REVIEW_ONLY_SHEETS = (("Cho_duyet_dong_bi_loai", "retained_line_counts"), ("Ung_vien_chu_so", "confusable_counts"))
LITERAL_HEADERS = ["Document ID", "Keyword", "Page", "Page status", "Start", "End", "Citation"]
ALIAS_HEADERS = ["Document ID", "Keyword", "Page", "Page status", "Start NFC", "End NFC", "Observed", "Source", "Rule ID", "Decision ID", "Context"]


def tiered_rows(records, dictionary):
    header = ["Tệp PDF", *dictionary["display_columns"]]
    columns = len(dictionary["display_columns"])
    for name, key in (("Dem_Tier2", "tier2_counts"), ("Cho_duyet", "pending_counts"), ("Tong_sau_duyet", None),
                      *REVIEW_ONLY_SHEETS):
        rows, totals, known = [header], [0] * columns, [True] * columns
        for record in records:
            projection = record.get("alias_analytics")
            if projection is not None and key and projection.get(key) is None:
                projection = None  # a companion without this column: unknown, never zero
            values = ([None] * columns if projection is None else projection[key] if key else
                      [literal + accepted if pending == 0 else None for literal, accepted, pending in
                       zip(record["counts"], projection["tier2_counts"], projection["pending_counts"])])
            if len(values) != columns or any(value is not None and (type(value) is not int or value < 0) for value in values):
                raise ValueError("Invalid tiered matrix projection")
            rows.append([record["name"], *values])
            for i, value in enumerate(values):
                known[i] &= value is not None
                totals[i] += value or 0
        rows.append(["TỔNG CỘNG", *[value if known[i] else None for i, value in enumerate(totals)]])
        yield name, rows
    literal, aliases = [LITERAL_HEADERS], [ALIAS_HEADERS]
    for record in records:
        for citation in record.get("literal_citations", []):
            literal.append([record["id"], citation["keyword"], citation.get("page_number") or json.dumps(citation.get("page_numbers", [])),
                            citation.get("page_status"), citation["match_start"], citation["match_end"],
                            " ".join(citation.get(k, "") for k in ("citation_before", "citation_keyword", "citation_after"))])
        for item in record.get("alias_resolutions", []):
            if item["review_status"] == "ACCEPTED":
                aliases.append([record["id"], item["keyword"], item["page_number"] or json.dumps(item["page_numbers"]), item["page_status"],
                                item["match_start"], item["match_end"], item["observed_text"], item["resolution_source"],
                                item["rule_id"], item["decision_id"], item["context"]])
    yield "Trich_dan_chi_tiet", literal
    yield "Trich_dan_Tier2", aliases


def append_tiered(book, records, dictionary):
    for name, rows in tiered_rows(records, dictionary):
        sheet = book.create_sheet(name)
        for row in rows:
            cells = [WriteOnlyCell(sheet, value=value) for value in row]
            for cell, value in zip(cells, row):
                if isinstance(value, str):
                    cell.data_type = "s"
            sheet.append(cells)


def verify_tiered(book, records, dictionary):
    for name, expected in tiered_rows(records, dictionary):
        if name not in book.sheetnames:
            raise ValueError("Missing tiered matrix sheet")
        sheet = book[name]
        actual = sheet.iter_rows(min_row=1, values_only=False)
        for row in expected:
            values = next(actual, None)
            raw = [] if values is None else [cell.value for cell in values]
            padded = raw + [None] * max(0, len(row)-len(raw))
            if (values is None or padded != row
                    or any(type(value) is not type(wanted) for value, wanted in zip(padded, row))):
                raise ValueError("Tiered matrix rows/counts mismatch")
            if any(cell.data_type == "f" for cell in values):
                raise ValueError("Tiered matrix values must be literals")
        if next(actual, None) is not None:
            raise ValueError("Extra tiered matrix rows")
