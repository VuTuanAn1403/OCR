"""C3.5(b)/(c): flag-only arithmetic checks and continuation candidates.
Values are never corrected and tables never merged; ambiguity is INCONCLUSIVE."""
import json
from decimal import Decimal

import pytest

from src.ocr.application.export_document import ExportDocumentUseCase
from src.ocr.domain.models.document import ExtractedDocument
from src.ocr.domain.models.page import ExtractedPage
from src.ocr.domain.models.quality import DocumentQualityReport, PageQualityReport
from src.ocr.domain.models.region import BoundingBox, ContentType, Region
from src.ocr.domain.models.table import TableCell, TableStructure
from src.ocr.domain.routing.page_type import PageType
from src.ocr.infrastructure.export.artifact_validator import validate_document_artifacts
from src.ocr.infrastructure.table.financial_checks import (
    balance_identity_checks, continuation_candidate, infer_convention, multi_value_cells, parse_amount,
    table_total_checks,
)


def table(rows, table_id="t", page=1, bbox=(50, 100, 545, 400)):
    cells = [TableCell(row_idx=r, col_idx=c, text=text, bbox=[])
             for r, row in enumerate(rows) for c, text in enumerate(row)]
    return TableStructure(table_id=table_id, page=page, bbox=list(bbox), num_rows=len(rows),
                          num_cols=max(len(r) for r in rows), cells=cells)


@pytest.mark.parametrize("text,convention,expected", [
    ("1.234.567", "vn", Decimal(1234567)), ("(1.234)", "vn", Decimal(-1234)), ("-5", "plain", Decimal(-5)),
    ("−2.000", "vn", Decimal(-2000)), ("–", "vn", Decimal(0)), ("1.234,5", "vn", Decimal("1234.5")),
    ("1,234.50", "en", Decimal("1234.50")), ("1 234 567", "plain", Decimal(1234567)),
    ("2025", "plain", Decimal(2025)), ("12,5%", "vn", None), ("Doanh thu", "vn", None),
    ("1.234", "ambiguous", None),
])
def test_parse_amount(text, convention, expected):
    assert parse_amount(text, convention) == expected


def test_convention_inference():
    assert infer_convention(["1.234.567", "(12.000)"]) == "vn"
    assert infer_convention(["1,234,567"]) == "en"
    assert infer_convention(["1.234.567", "1,234,567"]) == "ambiguous"
    assert infer_convention(["2025", "100"]) == "plain"


HEADER = ["Chỉ tiêu", "Mã số", "Năm 2025", "Năm 2024"]


def test_flat_total_consistent_and_code_column_ignored():
    checks = table_total_checks(table([HEADER,
                                       ["Doanh thu bán hàng", "01", "1.000.000", "900.000"],
                                       ["Doanh thu dịch vụ", "02", "234.000", "(100.000)"],
                                       ["Tổng cộng", "10", "1.234.000", "800.000"]]), "t")
    assert [(c["col"], c["status"]) for c in checks] == [(2, "CONSISTENT"), (3, "CONSISTENT")]


def test_total_mismatch_flags_cells_without_changing_values():
    rows = [HEADER, ["1. Doanh thu A", "01", "1.000", "900"], ["2. Doanh thu B", "02", "234", "100"],
            ["Tổng cộng", "10", "1.300", "1.000"]]
    original = table(rows)
    checks = table_total_checks(original, "t")
    violation = next(c for c in checks if c["col"] == 2)
    assert violation["status"] == "VIOLATION"
    assert violation["expected"] == "1234" and violation["found"] == "1300" and violation["difference"] == "66"
    assert {cell["row"] for cell in violation["suspicious_cells"]} == {1, 2, 3}
    assert original.cells[14].text == "1.300"  # still the extracted value


def test_hierarchical_block_uses_top_level_rows_or_stays_inconclusive():
    rows = [HEADER, ["I. Tiền", "110", "300.000", "200.000"], ["1. Tiền mặt", "111", "100.000", "50.000"],
            ["2. Tiền gửi ngân hàng", "112", "200.000", "150.000"],
            ["II. Đầu tư tài chính", "120", "500.000", "400.000"], ["Tổng cộng", "100", "800.000", "600.000"]]
    checks = table_total_checks(table(rows), "t")
    assert [c["status"] for c in checks] == ["CONSISTENT", "CONSISTENT"]
    assert checks[0]["decomposition"] == "roman_rows"
    rows[-1] = ["Tổng cộng", "100", "999.000", "601.000"]
    assert {c["status"] for c in table_total_checks(table(rows), "t")} == {"INCONCLUSIVE"}


# Rows as extracted from a real summarized balance sheet (AGR 2025, page 15):
# two rows were merged into one cell by the heuristic table detector.
AGR_ROWS = [
    ["TÀI SẢN", "2024", "2025"],
    ["A. TÀI SẢN NGẮN HẠN", "3.244,8", "3.898,1"],
    ["I. Tài sản tài chính", "3.233,7", "3.891,9"],
    ["1. Tiền và các khoản tương đương tiền", "453,9", "146,7"],
    ["13. Dự phòng suy giảm giá trị các khoản phải thu II. Tài sản ngắn hạn khác", "(1.079,0) 11,1", "(1.061,0) 6,2"],
    ["B. TÀI SẢN DÀI HẠN", "227,4", "535,7"],
    ["I. Tài sản tài chính dài hạn II. Tài sản cố định", "5,1 193,1", "310,9 201,1"],
    ["TỔNG CỘNG TÀI SẢN", "3.472,2", "4.433,8"],
]


def test_letter_level_total_is_verified_despite_merged_sub_rows():
    checks = table_total_checks(table(AGR_ROWS), "t")
    assert [(c["status"], c.get("decomposition")) for c in checks] == [
        ("CONSISTENT", "letter_rows"), ("CONSISTENT", "letter_rows")]


def test_cells_holding_several_amounts_flag_merged_rows():
    (check,) = multi_value_cells(table(AGR_ROWS), "t")
    assert check["status"] == "VIOLATION"
    assert {(c["row"], c["col"]) for c in check["suspicious_cells"]} == {(4, 1), (4, 2), (6, 1), (6, 2)}
    assert multi_value_cells(table([["Chỉ tiêu", "2025"], ["Doanh thu", "1 234 567"]]), "t") == []


def test_flat_numbered_block_mismatch_is_a_violation():
    rows = [HEADER, ["1. Doanh thu A", "01", "1.000.000", "900.000"], ["2. Doanh thu B", "02", "234.000", "100.000"],
            ["Tổng cộng", "10", "1.300.000", "1.000.000"]]
    assert [c["status"] for c in table_total_checks(table(rows), "t")] == ["VIOLATION", "CONSISTENT"]


def test_small_ungrouped_integers_are_treated_as_codes_and_the_skip_is_recorded():
    rows = [HEADER, ["A", "01", "300", "200"], ["B", "02", "500", "400"], ["Tổng cộng", "10", "999", "1"]]
    (check,) = table_total_checks(table(rows), "t")
    assert check["status"] == "INCONCLUSIVE" and check["reason"] == "no amount columns detected"
    assert {c["col"] for c in check["excluded_columns"]} == {1, 2, 3}


def test_bare_year_header_is_not_a_detail_row():
    rows = [["Chỉ tiêu", "2025", "2024"], ["Doanh thu A", "1.000", "900"], ["Doanh thu B", "234", "100"],
            ["Tổng cộng", "1.234", "1.000"]]
    assert [c["status"] for c in table_total_checks(table(rows), "t")] == ["CONSISTENT", "CONSISTENT"]


def test_unnumbered_mismatch_is_inconclusive_not_a_violation():
    kpi = [["Chỉ tiêu", "2025", "2024"], ["Doanh thu thuần", "12.345", "11.000"],
           ["Lợi nhuận sau thuế", "1.234", "1.000"], ["Tổng tài sản", "45.678", "40.000"],
           ["Vốn chủ sở hữu", "20.000", "18.000"]]
    assert {c["status"] for c in table_total_checks(table(kpi), "t")} == {"INCONCLUSIVE"}
    hierarchy = [["Chỉ tiêu", "2025"], ["Tài sản ngắn hạn", "3.000"], ["Tiền", "1.000"], ["Phải thu", "2.000"],
                 ["Tài sản dài hạn", "2.000"], ["Tổng cộng tài sản", "5.000"]]
    assert [c["status"] for c in table_total_checks(table(hierarchy), "t")] == ["INCONCLUSIVE"]


def test_job_title_is_not_a_total_row():
    rows = [["Họ tên", "Thù lao"], ["Chủ tịch HĐQT", "1.200.000"], ["Tổng Giám đốc", "2.400.000"],
            ["Kế toán trưởng", "900.000"]]
    assert table_total_checks(table(rows), "t") == []


def test_code_formula_decides_consistency():
    rows = [HEADER, ["Tài sản ngắn hạn", "100", "3.000.000", "2.500.000"], ["Tiền", "110", "1.000.000", "900.000"],
            ["Tài sản dài hạn", "200", "2.000.000", "1.500.000"],
            ["TỔNG CỘNG TÀI SẢN (270 = 100 + 200)", "270", "5.000.000", "4.100.000"]]
    checks = table_total_checks(table(rows), "t")
    assert [(c["status"], c.get("decomposition")) for c in checks] == [
        ("CONSISTENT", "code_formula"), ("VIOLATION", None)]
    assert checks[1]["expected"] == "4000000" and checks[1]["found"] == "4100000"


def test_corrupted_amount_cell_is_flagged_even_when_total_matches():
    rows = [HEADER, ["I. Tiền", "110", "100.000", "90.000"], ["1. Tiền mặt", "111", "6O.000", "50.000"],
            ["2. Tiền gửi", "112", "40.000", "40.000"], ["II. Đầu tư", "120", "200.000", "100.000"],
            ["Tổng cộng", "100", "300.000", "190.000"]]
    checks = table_total_checks(table(rows), "t")
    first = next(c for c in checks if c.get("col") == 2)
    assert first["status"] == "CONSISTENT" and first["non_numeric_cells"][0]["text_raw"] == "6O.000"
    damaged = next(c for c in checks if c["check"] == "amount_cell")
    assert damaged["status"] == "VIOLATION" and damaged["suspicious_cells"] == [{"row": 2, "col": 2, "text_raw": "6O.000"}]


def test_merged_integer_amounts_and_unbalanced_brackets_do_not_parse_as_one_number():
    assert parse_amount("12.000 345.000", "vn") is None
    assert parse_amount("(1.234", "vn") is None and parse_amount("1.234)", "vn") is None
    assert parse_amount("1.23", "vn") is None and parse_amount("12,5", "en") is None
    (check,) = multi_value_cells(table([["Chỉ tiêu", "2025"], ["Tiền", "5.000.000 345.000.000"],
                                        ["Phải thu", "1.000.000"]]), "t")
    assert check["suspicious_cells"] == [{"row": 1, "col": 1, "text_raw": "5.000.000 345.000.000"}]


def test_decimal_comma_tables_are_checked_not_skipped():
    rows = [["Chỉ tiêu", "2025"], ["1. Doanh thu", "523,4"], ["2. Thu nhập khác", "87,1"], ["Tổng cộng", "999,9"]]
    (check,) = table_total_checks(table(rows), "t")
    assert check["status"] == "VIOLATION" and check["expected"] == "610.5"


def test_duplicate_cell_positions_are_inconclusive():
    duplicated = table([["Chỉ tiêu", "2025"], ["1. A", "1.000"], ["2. B", "2.000"], ["Tổng cộng", "3.000"]])
    duplicated.cells.append(TableCell(row_idx=1, col_idx=1, text="9.000"))
    (check,) = table_total_checks(duplicated, "t")
    assert check["status"] == "INCONCLUSIVE" and check["reason"] == "duplicate cell positions"


def test_blank_detail_and_mixed_grouping_are_inconclusive():
    blank = table_total_checks(table([HEADER, ["A", "01", "1.000", "900"], ["B", "02", "", "100"],
                                      ["Cộng", "10", "1.000", "1.000"]]), "t")
    assert blank[0]["status"] == "INCONCLUSIVE" and "blank" in blank[0]["reason"]
    mixed = table_total_checks(table([HEADER, ["A", "01", "1.000.000", "1,000,000"],
                                      ["Tổng cộng", "10", "1.000.000", "1,000,000"]]), "t")
    assert mixed == [{"check": "total_row", "table_id": "t", "status": "INCONCLUSIVE",
                      "reason": "mixed Vietnamese and English number grouping"}]


def _sheet(label, current, previous, table_id):
    return (table_id, table([HEADER, ["Tài sản ngắn hạn", "100", "3.000", "2.500"],
                             ["Tài sản dài hạn", "200", "2.000", "1.500"], [label, "270", current, previous]],
                            table_id=table_id))


def test_balance_identity_does_not_let_a_kpi_row_steal_the_equity_total():
    kpi = ("kpi", table([["Chỉ tiêu", "Năm 2025"], ["Doanh thu", "1.000,5"], ["Tổng tài sản", "3.472,2"],
                         ["Vốn chủ sở hữu", "2.000,1"]], table_id="kpi", page=3))
    sheet = [_sheet("TỔNG CỘNG TÀI SẢN", "5.000", "4.000", "a"), _sheet("TỔNG CỘNG NGUỒN VỐN", "5.000", "4.000", "b")]
    for name, page in (("a", 20), ("b", 21)):
        sheet[["a", "b"].index(name)][1].page = page
    results = balance_identity_checks([kpi, *sheet])
    pair = next(r for r in results if "assets" in r and "equity" in r)
    assert pair["assets"]["table_id"] == "a" and pair["status"] == "CONSISTENT"
    unpaired = next(r for r in results if r["assets"]["table_id"] == "kpi")
    assert unpaired["status"] == "INCONCLUSIVE" and "no following" in unpaired["reason"]


def test_balance_identity_needs_aligned_periods_and_units():
    blank_one_side = [_sheet("TỔNG CỘNG TÀI SẢN", "5.000", "", "a"), _sheet("TỔNG CỘNG NGUỒN VỐN", "", "5.000", "b")]
    assert balance_identity_checks(blank_one_side)[0]["status"] == "INCONCLUSIVE"
    other_header = ("b", table([["Chỉ tiêu", "Mã số", "Số cuối năm", "Số đầu năm"],
                                ["Nợ phải trả", "300", "1.000", "900"], ["TỔNG CỘNG NGUỒN VỐN", "440", "5.000", "4.000"]],
                               table_id="b"))
    (check,) = balance_identity_checks([_sheet("TỔNG CỘNG TÀI SẢN", "5.000", "4.000", "a"), other_header])
    assert check["status"] == "INCONCLUSIVE" and "period header" in check["reason"]
    units = [_sheet("TỔNG CỘNG TÀI SẢN", "5.000", "4.000", "a"),
             _sheet("TỔNG CỘNG NGUỒN VỐN", "5.000.000.000", "4.000.000.000", "b")]
    assert "units" in balance_identity_checks(units)[0]["reason"]


def test_balance_identity_pairs_assets_with_following_equity():
    tables = [_sheet("TỔNG CỘNG TÀI SẢN", "5.000", "4.000", "a"), _sheet("TỔNG CỘNG NGUỒN VỐN", "5.000", "4.000", "b")]
    assert [c["status"] for c in balance_identity_checks(tables)] == ["CONSISTENT"]
    tables[1] = _sheet("TỔNG CỘNG NGUỒN VỐN", "5.100", "4.000", "b")
    (check,) = balance_identity_checks(tables)
    assert check["status"] == "VIOLATION"
    assert {(c["table_id"], c["col"]) for c in check["suspicious_cells"]} == {("a", 2), ("b", 2)}


def _continuation(prev_rows, next_rows, prev_box=(50, 500, 545, 800), next_box=(50, 60, 545, 300),
                  between=(), heading=False):
    return continuation_candidate(table(prev_rows), list(prev_box), 842.0, table(next_rows), list(next_box),
                                  842.0, list(between), heading)


def test_continuation_candidate_requires_structure_and_a_signal():
    head = ["Chỉ tiêu", "Năm 2025", "Năm 2024"]
    prev = [head, ["Doanh thu", "1.000", "900"], ["Giá vốn", "(600)", "(500)"]]
    nxt = [head, ["Lợi nhuận gộp", "400", "400"]]
    candidate = _continuation(prev, nxt)
    assert candidate["status"] == "CANDIDATE" and candidate["merged"] is False
    assert "header_repeated" in candidate["signals"] and "previous_touches_bottom_next_starts_top" in candidate["signals"]
    data_first = _continuation(prev, [["Lợi nhuận gộp", "400", "400"]])
    assert data_first and "unit_and_period" in data_first["unverified"]
    assert _continuation(prev, nxt, heading=True) is None
    assert _continuation(prev, [["A", "B"], ["x", "1"]]) is None  # column count differs
    assert _continuation(prev, nxt, between=["Bảng 5: Chi phí"]) is None  # new caption
    assert _continuation(prev, nxt, prev_box=(50, 100, 545, 300)) is None  # no continuity signal
    marked = _continuation(prev, nxt, prev_box=(50, 100, 545, 300), between=["(tiếp theo)"])
    assert marked and "continuation_marker" in marked["signals"]


def _page(number, tables):
    return ExtractedPage(page_num=number, width=595, height=842, page_type=PageType.NATIVE_TEXT,
                         tables=tables, regions=[Region(region_id=f"r{number}", bbox=BoundingBox(
                             x0=0, y0=0, x1=595, y1=842), content_type=ContentType.TEXT, status="EXTRACTED")],
                         quality=PageQualityReport(page=number, page_type="NATIVE_TEXT"))


def test_export_records_checks_and_marks_review_only(tmp_path):
    head = ["Chỉ tiêu", "Năm 2025", "Năm 2024"]
    first = table([head, ["1. Doanh thu A", "1.000", "900"], ["2. Doanh thu B", "234", "100"],
                   ["Tổng cộng", "1.300", "1.000"]], table_id="p1_t1", page=1, bbox=(50, 500, 545, 800))
    second = table([head, ["Chi phí", "200", "150"], ["Lãi vay", "50", "40"]],
                   table_id="p2_t1", page=2, bbox=(50, 60, 545, 300))
    pages = [_page(1, [first]), _page(2, [second])]
    doc = ExtractedDocument(document_id="fin", file_path="unused.pdf", file_hash="0123456789abcdef",
                            total_pages=2, selected_pages=[1, 2], pages=pages,
                            manifest={"selected_pages": [1, 2], "device": "cpu"},
                            quality=DocumentQualityReport(document_id="fin", total_pages=2))
    out = ExportDocumentUseCase.execute(doc, tmp_path, assets_mode="none")
    assert validate_document_artifacts(out)["status"] != "FAIL"
    document = json.loads((out / "document.json").read_text(encoding="utf-8"))
    by_id = {t["table_id"].split(":")[1]: t for t in document["tables"]}
    total = by_id["p0001"]
    assert total["needs_review"] is True
    assert [c["status"] for c in total["arithmetic_checks"]] == ["VIOLATION", "CONSISTENT"]  # 900+100=1.000
    assert by_id["p0002"]["continuation"]["status"] == "CANDIDATE"
    assert document["consistency_checks"]["continuation_candidates"][0]["merged"] is False
    assert len(document["tables"]) == 2  # nothing merged
    cells = {c["text_raw"] for c in total["cells"]}
    assert "1.300" in cells  # extracted value kept


def _two_page_doc():
    head = ["Chỉ tiêu", "Năm 2025", "Năm 2024"]
    first = table([head, ["1. Doanh thu A", "1.000", "900"], ["2. Doanh thu B", "234", "100"],
                   ["Tổng cộng", "1.234", "1.000"]], table_id="p1_t1", page=1)
    pages = [_page(1, [first])]
    return ExtractedDocument(document_id="fin", file_path="unused.pdf", file_hash="0123456789abcdef",
                             total_pages=1, selected_pages=[1], pages=pages,
                             manifest={"selected_pages": [1], "device": "cpu"},
                             quality=DocumentQualityReport(document_id="fin", total_pages=1))


def test_check_crash_is_recorded_and_keeps_the_export(tmp_path, monkeypatch):
    def broken(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("src.ocr.infrastructure.export.document_contracts.table_total_checks", broken)
    out = ExportDocumentUseCase.execute(_two_page_doc(), tmp_path, assets_mode="none")
    document = json.loads((out / "document.json").read_text(encoding="utf-8"))
    assert document["consistency_checks"] == {"method": "financial-checks-v2", "status": "FAILED",
                                              "error": "RuntimeError: boom"}
    assert all(t["needs_review"] is True for t in document["tables"])  # unchecked tables are not cleared
    assert validate_document_artifacts(out)["status"] != "FAIL"


def test_every_table_entry_states_its_review_flag_and_summary(tmp_path):
    out = ExportDocumentUseCase.execute(_two_page_doc(), tmp_path, assets_mode="none")
    document = json.loads((out / "document.json").read_text(encoding="utf-8"))
    (entry,) = document["tables"]
    chunk = next(c for c in document["chunks"] if c["chunk_id"] == entry["chunk_id"])
    assert entry["needs_review"] == chunk["needs_review"]
    summary = document["consistency_checks"]["summary"]
    assert summary["CONSISTENT"] == 2 and summary["tables"] == 1 and summary["tables_with_checks"] == 1


def test_schema_rejects_merged_continuations_and_unknown_statuses():
    from pydantic import ValidationError
    from src.ocr.infrastructure.export.contract_schema import ConsistencyCheck, ContinuationCandidate
    with pytest.raises(ValidationError):
        ConsistencyCheck.model_validate({"check": "total_row", "status": "OK"})
    with pytest.raises(ValidationError):
        ContinuationCandidate.model_validate({"status": "CANDIDATE", "merged": True, "signals": ["x"],
                                              "previous_table_id": "a:p0001:t0001", "table_id": "a:p0002:t0001"})


def test_violations_and_candidates_reach_the_batch_review_queue(tmp_path):
    from src.ocr.cli.batch_runner import consistency_review_items
    head = ["Chỉ tiêu", "Năm 2025", "Năm 2024"]
    first = table([head, ["1. Doanh thu A", "1.000", "900"], ["2. Doanh thu B", "234", "100"],
                   ["Tổng cộng", "1.300", "1.000"]], table_id="p1_t1", page=1, bbox=(50, 500, 545, 800))
    second = table([head, ["Chi phí", "200", "150"], ["Lãi vay", "50", "40"]],
                   table_id="p2_t1", page=2, bbox=(50, 60, 545, 300))
    doc = ExtractedDocument(document_id="fin", file_path="unused.pdf", file_hash="0123456789abcdef",
                            total_pages=2, selected_pages=[1, 2], pages=[_page(1, [first]), _page(2, [second])],
                            manifest={"selected_pages": [1, 2], "device": "cpu"},
                            quality=DocumentQualityReport(document_id="fin", total_pages=2))
    out = ExportDocumentUseCase.execute(doc, tmp_path, assets_mode="none")
    reasons = [item["reason"] for item in consistency_review_items(out, "fin.pdf")]
    assert any(r.startswith("financial_total_row:") for r in reasons)
    assert any(r.startswith("table_continuation_candidate:") for r in reasons)
    (out / "document.json").write_text("{broken", encoding="utf-8")
    (item,) = consistency_review_items(out, "fin.pdf")
    assert item["priority"] == "CRITICAL" and "unreadable" in item["reason"]
