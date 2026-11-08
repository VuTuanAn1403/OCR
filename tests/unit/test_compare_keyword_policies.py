"""scripts/compare_keyword_policies.py: CPU diff of literal_v1 and literal_v2 (V8-032)."""
import json

from scripts import compare_keyword_policies as compare


def test_compare_text_attributes_each_difference_to_boundary_or_overlap():
    text = "Phát triển bền vững; AIoT và AI"
    result = compare.compare_text(text, ["phát triển", "phát triển bền vững", "AI"])
    rows = {row["keyword"]: row for row in result["changes"]}
    assert rows["AI"]["literal_v1"] == 2 and rows["AI"]["literal_v2"] == 1 and rows["AI"]["boundary_rejected"] == 1
    assert rows["phát triển"]["overlap_suppressed"] == 1 and rows["phát triển"]["difference"] == -1
    assert "phát triển bền vững" not in rows
    assert (result["literal_v1_total"], result["literal_v2_total"]) == (4, 2)


def test_cli_writes_a_new_report_and_refuses_overwrite(tmp_path):
    document = tmp_path / "doc" / "result.md"
    document.parent.mkdir()
    document.write_text("chuyển đổi số và chuyển đổi số hóa", encoding="utf-8")
    keywords = tmp_path / "keywords.txt"
    keywords.write_text("chuyển đổi số\nsố hóa\n", encoding="utf-8")
    report = tmp_path / "diff.json"
    assert compare.main([str(tmp_path), "--keywords-file", str(keywords), "--report", str(report)]) == 0
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["product_policy"] == "literal_v1" and data["quality_acceptance"] == "NOT_EVALUATED"
    assert data["totals"] == {"documents": 1, "literal_v1": 3, "literal_v2": 2}
    assert compare.main([str(document), "--keywords-file", str(keywords), "--report", str(report)]) == 2


def test_cli_reports_missing_inputs(tmp_path):
    keywords = tmp_path / "keywords.txt"
    keywords.write_text("a\n", encoding="utf-8")
    assert compare.main([str(tmp_path / "missing"), "--keywords-file", str(keywords),
                         "--report", str(tmp_path / "r.json")]) == 2
