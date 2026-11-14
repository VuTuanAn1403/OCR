"""V8-100, reviewer decisions Q6 B and Q7 A: review-only keyword evidence, never counted."""
import json

from ocr_keywords import review_evidence as ev
from ocr_keywords.tiered import build_tiered_report

KEYWORDS = ["O2O", "B2B", "Số hóa", "Đổi mới"]


def test_zero_for_letter_o_is_a_candidate_and_numbers_or_codes_are_not():
    text = "mô hình 020, mạng lưới O2O, năm 2020, 1.020 tỷ, mã 1600169024-020, (02O)"
    rows = ev.find_confusable_candidates(text, KEYWORDS)
    assert [(r["keyword"], r["observed_text"]) for r in rows] == [("O2O", "020"), ("O2O", "02O")]
    assert all(r["counted"] is False for r in rows)
    assert text[rows[0]["match_start"]:rows[0]["match_end"]] == "020"


def _extraction(tmp_path, lines):
    page = {"page": 95, "rejected_ocr_lines": {"items": [
        {"source_id": f"d:p0095:r{i:06d}", "text": text, "confidence": 0.535, "gate_status": "REJECTED_LOW_CONFIDENCE",
         "bbox": [1, 2, 3, 4]} for i, text in enumerate(lines)]}}
    (tmp_path / "extraction.json").write_text(json.dumps({"pages": [page]}, ensure_ascii=False), encoding="utf-8")
    return tmp_path


def test_retained_line_keywords_are_a_separate_column(tmp_path):
    source = _extraction(tmp_path, ["số hóa tài liệu đào tạo", "không có gì"])
    out = ev.retained_line_keywords(source, KEYWORDS)
    assert out["retained_line_status"] == "EVALUATED" and out["retained_line_total"] == 1
    row = out["retained_line_occurrences"][0]
    assert (row["keyword"], row["page"], row["counted"]) == ("Số hóa", 95, False)


def test_without_extraction_the_column_is_not_evaluated_never_zero(tmp_path):
    out = ev.retained_line_keywords(tmp_path, KEYWORDS)
    assert out["retained_line_status"] == "NOT_EVALUATED" and out["retained_line_counts"] is None
    assert ev.retained_line_keywords(None, KEYWORDS)["retained_line_total"] is None


def test_tiered_report_carries_the_evidence_and_keeps_every_count(tmp_path):
    from ocr_keywords.contract import count_report, dictionary_snapshot

    keys = tmp_path / "keywords.txt"
    keys.write_text("\n".join(KEYWORDS), encoding="utf-8")
    snapshot = dictionary_snapshot(keys, "custom-review-evidence")
    text = "mô hình 020 và Đổi mới\n"
    md = tmp_path / "result.md"
    md.write_text(text, encoding="utf-8")
    report = count_report("doc", "0" * 64, md, snapshot, [1])
    source = _extraction(tmp_path, ["số hóa tài liệu đào tạo"])
    tiered = build_tiered_report(report, snapshot, text, source_dir=source)
    assert tiered["confusable_candidate_occurrences"] == 1 and tiered["retained_line_total"] == 1
    plain = build_tiered_report(report, snapshot, text)
    for key in ("tier1_literal_counts", "tier2_candidate_counts", "tier2_reviewed_counts", "tier1_total_literal"):
        assert tiered[key] == plain[key]
