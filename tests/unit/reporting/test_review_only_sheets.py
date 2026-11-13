"""V8-100 review-only sheets (Q6 B, Q7 A): separate columns, never added to Tong_sau_duyet."""
from ocr_reporting.tiered_workbooks import tiered_rows

DICTIONARY = {"display_columns": ["O2O", "Số hóa"]}


def _record(name, analytics):
    return {"name": name, "id": name, "counts": [0, 2], "alias_analytics": analytics}


def _analytics(**extra):
    return {"tier2_counts": [0, 0], "pending_counts": [0, 0], **extra}


def test_review_only_columns_are_separate_and_unknown_stays_empty():
    records = [_record("VIC.pdf", _analytics(retained_line_counts=[0, 1], confusable_counts=[6, 0])),
               _record("OLD.pdf", _analytics())]  # companion written before the columns existed
    sheets = dict(tiered_rows(records, DICTIONARY))
    assert sheets["Cho_duyet_dong_bi_loai"][1] == ["VIC.pdf", 0, 1]
    assert sheets["Ung_vien_chu_so"][1] == ["VIC.pdf", 6, 0]
    assert sheets["Ung_vien_chu_so"][2] == ["OLD.pdf", None, None]
    assert sheets["Ung_vien_chu_so"][-1] == ["TỔNG CỘNG", None, None]
    assert sheets["Tong_sau_duyet"][1] == ["VIC.pdf", 0, 2]  # literal + accepted only
