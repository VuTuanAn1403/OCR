"""V6.3 workbook projections. All totals are values, never cached formulas."""
from io import BytesIO
from pathlib import Path
import json

from openpyxl import Workbook, load_workbook
from ocr_artifacts.atomic_io import atomic_write_bytes
from ocr_contracts.keyword import KeywordReport, KeywordCount, KeywordCitation
from ocr_reporting.document_workbook import (KeywordExporter, SHEETS, CITATION_HEADERS, WORKBOOK_SCHEMA,
                                              CellRichText, ordered_citations, citation_text, citation_page)


def _model(report, snapshot):
    rows = [KeywordCount(keyword=k, count=n, exact_count=n) for k, n in zip(snapshot["display_columns"], report["display_counts"])]
    return KeywordReport(document_id=report["document_id"], source_file=report["source_file"], keywords=rows,
                         citations=[KeywordCitation.model_validate(c) for c in report.get("citations", [])],
                         total_keywords_searched=len(rows), total_matches=report["total_display_matches"],
                         total_exact_matches=report["total_display_matches"])


def _metadata(report, snapshot):
    return {"schema_version": WORKBOOK_SCHEMA, "keyword_set_version": snapshot["keyword_set_version"],
            "keyword_set_revision": snapshot.get("keyword_set_revision"),
            "counting_policy": "literal_v1", "dictionary_sha256": snapshot["snapshot_sha256"],
            "total_canonical_matches": report["total_canonical_matches"], "total_display_matches": report["total_display_matches"],
            "citation_schema_version": report.get("citation_schema_version")}


def export_document(report, snapshot, output):
    # Write once: reopening without rich_text=True would erase bold citations.
    path = KeywordExporter.export_excel(_model(report, snapshot), Path(output), metadata=_metadata(report, snapshot))
    verify_document(path, report, snapshot)


def verify_document(path, report, snapshot):
    options = {"rich_text": True} if CellRichText is not None else {}
    # openpyxl's streaming reader flattens inline rich strings. Load this
    # per-document workbook normally so bold runs and literal types survive.
    book = load_workbook(path, read_only=False, data_only=False, **options)
    try:
        if book.sheetnames == ["Thống kê từ khóa"] and "citation_schema_version" not in report:
            rows = list(book.active.iter_rows(min_row=5, max_row=4+len(snapshot["display_columns"]), values_only=True))
            if [r[1] for r in rows] != snapshot["display_columns"] or [r[2] for r in rows] != report["display_counts"]:
                raise ValueError("Per-document legacy Excel differs from canonical keyword report")
            return
        if book.sheetnames != list(SHEETS):
            raise ValueError("Per-document Excel must contain the two declared summary/citation sheets")
        summary, details = (book[name] for name in SHEETS)
        rows = list(summary.iter_rows(values_only=True))
        expected = [["File_name", *snapshot["display_columns"]], [report["document_id"], *report["display_counts"]]]
        if [list(row) for row in rows] != expected or any(type(n) is not int for n in rows[1][1:]):
            raise ValueError("Per-document Excel differs from canonical keyword report")
        if summary["A2"].data_type != "s" or any(c.data_type != "s" for c in next(summary.iter_rows(min_row=1, max_row=1))):
            raise ValueError("Per-document names/keywords must be literal strings")
        if json.loads(book.properties.description or "null") != _metadata(report, snapshot):
            raise ValueError("Per-document Excel dictionary/policy metadata mismatch")
        actual = iter(details.iter_rows())
        if [c.value for c in next(actual)] != list(CITATION_HEADERS):
            raise ValueError("Citation sheet header mismatch")
        for number, citation in enumerate(ordered_citations(_model(report, snapshot)), 1):
            row = next(actual, None)
            expected_row = [number, citation.keyword, citation_page(citation), citation_text(citation)]
            if row is None or [str(c.value) if i == 3 and c.value is not None else c.value for i, c in enumerate(row)] != expected_row:
                raise ValueError("Citation sheet differs from canonical occurrence report")
            page = expected_row[2]
            if (type(row[0].value) is not int or row[1].data_type != "s" or row[3].data_type != "s"
                    or type(row[2].value) is not type(page)
                    or isinstance(page, str) and row[2].data_type != "s"):
                raise ValueError("Citation cells must preserve literal strings and physical page types")
            if CellRichText is not None and citation.citation_keyword:
                rich = row[3].value
                bold = [part.text for part in rich if getattr(getattr(part, "font", None), "b", False)] if isinstance(rich, CellRichText) else []
                if bold != [citation.citation_keyword]:
                    raise ValueError("Citation keyword bold formatting is missing or changed")
        if next(actual, None) is not None:
            raise ValueError("Citation sheet contains extra occurrences")
    finally:
        book.close()


def matrix_bytes(batch_id, revision, records, snapshot):
    book = Workbook(write_only=True)
    try:
        sheet = book.create_sheet("Ma trận từ khóa")
        header = ["Tệp PDF", *snapshot["display_columns"]]
        # Write-only cells explicitly treat dictionary entries as literal text.
        from openpyxl.cell import WriteOnlyCell
        cells = [WriteOnlyCell(sheet, value=s) for s in header]
        for cell in cells:
            cell.data_type = "s"
        sheet.append(cells)
        totals = [0]*len(snapshot["display_columns"])
        for row in records:
            counts = row.get("counts")
            name = WriteOnlyCell(sheet, value=row["name"])
            name.data_type = "s"
            sheet.append([name, *(counts if counts is not None else [None]*len(totals))])
            if counts is not None:
                totals = [a+b for a, b in zip(totals, counts)]
        sheet.append(["TỔNG CỘNG", *totals])
        status = book.create_sheet("Trạng thái")
        status.append(["Document ID", "Tệp PDF", "Kết quả", "Validation", "Attempt", "Report hash", "Publication", "Revision", "Lỗi", "Source review", "Pages", "Duplicate of"])
        errors = book.create_sheet("Tệp lỗi")
        errors.append(["Document ID", "Lỗi"])
        for row in records:
            status.append([row["id"], row["name"], row.get("outcome", "PENDING"), row.get("validation"), row.get("attempt", 0),
                           row.get("report_sha256"), "INCLUDED_IN_REVISION" if row.get("outcome") else "PENDING", revision, row.get("error"),row.get("source_review"),row.get("total_pages"),row.get("duplicate_of")])
            if row.get("outcome") == "FAILED_DOCUMENT":
                errors.append([row["id"], row.get("error")])
        summary = book.create_sheet("Tổng quan")
        for key, value in {"Tổng đầu vào": len(records), "Đã công bố": sum(bool(r.get("outcome")) for r in records),
            "Đang chờ": sum(not r.get("outcome") for r in records), "Lỗi": sum(r.get("outcome")=="FAILED_DOCUMENT" for r in records),
            "Cần review": sum(r.get("validation")=="NEEDS_REVIEW" for r in records),
            "Nguồn hash duy nhất": len({r["pdf_sha256"] for r in records if r.get("pdf_sha256")}),
            "Tổng canonical": sum(r.get("total_canonical_matches", 0) for r in records),
            "Tổng display": sum(totals)}.items():
            summary.append([key, value])
        info = book.create_sheet("Thông tin")
        for key, value in {"batch_id": batch_id, "revision": revision, "dictionary_sha256": snapshot["snapshot_sha256"],
                           "schema_version": "keyword-matrix-v1", "policy": "literal_v1", "quality_acceptance": "NOT_EVALUATED"}.items():
            info.append([key, value])
        if any(row.get("analytics_enabled") for row in records):
            from ocr_reporting.tiered_workbooks import append_tiered
            info.append(["alias_rules_sha256", records[0]["analytics_rules_sha256"]])
            info.append(["tiered_schema_version", "keyword-matrix-tiered-v1"])
            append_tiered(book, records, snapshot)
        buffer = BytesIO()
        book.save(buffer)
        return buffer.getvalue()
    finally:
        book.close()


def verify_matrix(path, batch_id, revision, records, snapshot):
    book = load_workbook(path, read_only=True, data_only=False)
    try:
        info = dict(book["Thông tin"].iter_rows(values_only=True))
        if info.get("batch_id") != batch_id or info.get("revision") != revision or info.get("dictionary_sha256") != snapshot["snapshot_sha256"]:
            raise ValueError("Matrix identity/revision mismatch")
        rows = iter(book["Ma trận từ khóa"].iter_rows(min_col=1,max_col=1+len(snapshot["display_columns"]),values_only=True))
        if list(next(rows)) != ["Tệp PDF", *snapshot["display_columns"]]:
            raise ValueError("Matrix header mismatch")
        totals = [0]*len(snapshot["display_columns"])
        for record in records:
            values = list(next(rows))
            expected = record.get("counts")
            if values != [record["name"], *(expected if expected is not None else [None]*len(totals))]:
                raise ValueError("Matrix rows/counts mismatch")
            if expected is not None:
                totals = [a+b for a, b in zip(totals, expected)]
        if list(next(rows)) != ["TỔNG CỘNG", *totals] or next(rows, None) is not None:
            raise ValueError("Matrix totals/row count mismatch")
        if any(row.get("analytics_enabled") for row in records):
            from ocr_reporting.tiered_workbooks import verify_tiered
            if (info.get("alias_rules_sha256") != records[0]["analytics_rules_sha256"]
                    or info.get("tiered_schema_version") != "keyword-matrix-tiered-v1"):
                raise ValueError("Tiered matrix rule identity mismatch")
            verify_tiered(book, records, snapshot)
    finally:
        book.close()
