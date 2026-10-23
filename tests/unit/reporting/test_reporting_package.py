"""ocr_reporting: per-document workbook, batch matrix and read-back checks.

Runs with pydantic, openpyxl and pytest only. Workbooks are compared by
values and structure, never by XLSX bytes (ZIP metadata varies).
"""
import json
from pathlib import Path

import openpyxl
import pytest

from ocr_artifacts import atomic_io
from ocr_keywords.contract import count_report, dictionary_snapshot
from ocr_reporting.validation import validate_document_workbook
from ocr_reporting.workbooks import export_document, matrix_bytes, verify_document, verify_matrix

ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT = dictionary_snapshot(ROOT / "config/keywords.txt", "v1")


def report_for(tmp_path, text, doc_id="doc"):
    out = tmp_path / doc_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.md").write_text(text, encoding="utf-8")
    return out, count_report(doc_id, None, out / "result.md", SNAPSHOT, [1])


def test_document_workbook_rows_totals_and_policy_line(tmp_path):
    out, report = report_for(tmp_path, "Internet di động; chuyển đổi số")
    export_document(report, SNAPSHOT, out)
    validate_document_workbook(out, report, SNAPSHOT)
    book = openpyxl.load_workbook(out / "count_keywords.xlsx", data_only=True)
    sheet = book.active
    rows = list(sheet.iter_rows(min_row=5, max_row=4 + 88, values_only=True))
    assert [r[1] for r in rows] == SNAPSHOT["display_columns"] and [r[2] for r in rows] == report["display_counts"]
    assert sheet.cell(5 + 88, 3).value == report["total_display_matches"]
    assert "literal_v1" in sheet["A3"].value and f"canonical={report['total_canonical_matches']}" in sheet["A3"].value
    book.close()


def test_modified_document_workbook_is_detected(tmp_path):
    out, report = report_for(tmp_path, "Internet di động")
    export_document(report, SNAPSHOT, out)
    book = openpyxl.load_workbook(out / "count_keywords.xlsx")
    book.active.cell(5, 3).value = 99
    book.save(out / "count_keywords.xlsx")
    with pytest.raises(ValueError):
        verify_document(out / "count_keywords.xlsx", report, SNAPSHOT)


def test_failed_write_keeps_previous_workbook(tmp_path, monkeypatch):
    out, report = report_for(tmp_path, "Internet di động")
    export_document(report, SNAPSHOT, out)
    before = (out / "count_keywords.xlsx").read_bytes()
    monkeypatch.setattr(atomic_io.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    _, other = report_for(tmp_path, "chuyển đổi số chuyển đổi số")
    with pytest.raises(OSError, match="disk full"):
        export_document(other, SNAPSHOT, out)
    assert (out / "count_keywords.xlsx").read_bytes() == before


def records(tmp_path):
    _, a = report_for(tmp_path, "Internet di động", "a")
    return [
        {"id": "a", "name": "=SUM(A1:A9).pdf", "outcome": "SUCCEEDED", "counts": a["display_counts"],
         "total_canonical_matches": a["total_canonical_matches"], "validation": "NEEDS_REVIEW"},
        {"id": "b", "name": "b.pdf", "outcome": "FAILED_DOCUMENT", "counts": None, "error": "bad pdf"},
        {"id": "c", "name": "c.pdf", "counts": None},
    ]


def test_matrix_values_blanks_totals_and_literal_names(tmp_path):
    rows = records(tmp_path)
    path = tmp_path / "matrix.xlsx"
    path.write_bytes(matrix_bytes("batch-1", 3, rows, SNAPSHOT))
    verify_matrix(path, "batch-1", 3, rows, SNAPSHOT)
    book = openpyxl.load_workbook(path, data_only=True)
    matrix = list(book["Ma trận từ khóa"].iter_rows(values_only=True))
    assert len(matrix[0]) == 89 and matrix[0][0] == "Tệp PDF"
    assert matrix[1][0] == "=SUM(A1:A9).pdf" and book["Ma trận từ khóa"]["A2"].data_type == "s"
    assert matrix[2][1:] == (None,) * 88 and matrix[3][1:] == (None,) * 88   # failed and pending stay blank
    assert list(matrix[4][1:]) == rows[0]["counts"] and 0 in matrix[1][1:]  # zero is a real count
    summary = dict(book["Tổng quan"].iter_rows(values_only=True))
    assert summary["Lỗi"] == 1 and summary["Đang chờ"] == 1 and summary["Cần review"] == 1
    info = dict(book["Thông tin"].iter_rows(values_only=True))
    assert info["revision"] == 3 and info["dictionary_sha256"] == SNAPSHOT["snapshot_sha256"]
    errors = list(book["Tệp lỗi"].iter_rows(values_only=True))
    assert errors[1] == ("b", "bad pdf")
    book.close()


@pytest.mark.parametrize("change", ["count", "revision", "extra_row", "batch"])
def test_tampered_or_stale_matrix_is_rejected(tmp_path, change):
    rows = records(tmp_path)
    path = tmp_path / "matrix.xlsx"
    path.write_bytes(matrix_bytes("batch-1", 3, rows, SNAPSHOT))
    if change == "count":
        book = openpyxl.load_workbook(path)
        book["Ma trận từ khóa"]["B2"].value = 1234
        book.save(path)
        expected = ("batch-1", 3, rows)
    elif change == "revision":
        expected = ("batch-1", 4, rows)
    elif change == "batch":
        expected = ("batch-2", 3, rows)
    else:
        expected = ("batch-1", 3, rows[:-1])
    with pytest.raises((ValueError, StopIteration)):
        verify_matrix(path, *expected[:2], expected[2], SNAPSHOT)


def test_reporting_never_recounts(tmp_path):
    out, report = report_for(tmp_path, "Internet di động")
    report = json.loads(json.dumps(report))
    report["display_counts"] = [7] * 88
    report["total_display_matches"] = 7 * 88
    export_document(report, SNAPSHOT, out)  # writes the given counts, never result.md counts
    verify_document(out / "count_keywords.xlsx", report, SNAPSHOT)
