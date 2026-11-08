"""scripts/inventory_diacritic_slots.py: slot counts and the exact sample-size plan (V8-012)."""
import json

from scripts import inventory_diacritic_slots as inventory


def test_slots_follow_the_three_slot_model_after_nfc():
    counts = inventory.count_slots("Độc lập" + " " + "Vie\u0302\u0323t")
    # Đ(stroke) ộ(shape+tone) ậ(shape+tone) ệ(shape+tone, decomposed input)
    assert (counts["stroke"], counts["shape"], counts["tone"], counts["total"]) == (1, 3, 3, 7)
    assert counts["uncomposed_marks"] == 0


def test_plan_reports_the_shortfall_and_applies_the_design_effect():
    plan = inventory.sample_plan(1788, max_errors=1, confidences=(.95,), deff=2.0)
    assert plan[0]["required_slots"] == 2 * 29956 and plan[0]["shortfall"] == 2 * 29956 - 1788
    assert plan[1]["allowed_errors"] == 1 and plan[1]["required_slots"] == 2 * 47437


def test_cli_writes_once_and_marks_custody_unknown(tmp_path):
    gt = tmp_path / "gt"
    gt.mkdir()
    (gt / "page.txt").write_text("đồng", encoding="utf-8")
    report = tmp_path / "inventory.json"
    assert inventory.main([str(gt), "--report", str(report)]) == 0
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["totals"]["total"] == 3 and data["gt_custody"] == "NOT_EVALUATED"
    assert inventory.main([str(gt), "--report", str(report)]) == 2
    assert inventory.main([str(gt), "--report", str(tmp_path / "x.json"), "--icc", ".1"]) == 2
