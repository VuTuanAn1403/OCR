"""Run one synthetic PDF through the real unified GPU pipeline.

This checks execution, placement and publication; it does not measure accuracy.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import src.ocr


def fixture(path):
    import pymupdf
    path.parent.mkdir(parents=True, exist_ok=True)
    font = ROOT / "assets/fonts/NotoSans-Regular.ttf"
    with pymupdf.open() as document:
        page = document.new_page(width=595, height=842)
        page.insert_font(fontname="fixture", fontfile=str(font))
        page.insert_text((50, 65), "BÁO CÁO THỬ NGHIỆM", fontname="fixture", fontsize=21)
        page.insert_text((50, 105), "Chuyển đổi số và trí tuệ nhân tạo năm 2026.", fontname="fixture", fontsize=14)
        xs, ys = [50, 350, 470, 545], [150, 190, 230, 270]
        for x in xs:
            page.draw_line((x, ys[0]), (x, ys[-1]))
        for y in ys:
            page.draw_line((xs[0], y), (xs[-1], y))
        for row, y in zip([("Chỉ tiêu", "2025", "2026"), ("Doanh thu", "1.234", "1.567"),
                           ("Lợi nhuận", "234", "345")], ys):
            for value, x in zip(row, xs):
                page.insert_text((x + 6, y + 26), value, fontname="fixture", fontsize=12)
        document.save(path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "output/unified_smoke")
    parser.add_argument("--env-root", type=Path, default=ROOT / ".venv-v62")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    source = args.output.parent / (args.output.name + "_source") / "runtime-smoke.pdf"
    if not source.exists():
        fixture(source)
    from ocr_pipeline.cli import main as run
    command = [str(source), "--output", str(args.output), "--env-root", str(args.env_root)]
    if args.resume:
        command.append("--resume")
    result = run(False, command)
    if result:
        return result
    from scripts.audit_batch_outputs import audit
    report = audit(args.output, validate=True)
    target = args.output.parent / (args.output.name + "_audit.json")
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Synthetic 1-page execution check; quality NOT_EVALUATED. Audit: {target}")
    accepted = report["documents"] and all(
        row["completion_valid"] and row.get("full_coverage") and row.get("gpu_source_gate") == "PASS"
        and row.get("validation", {}).get("errors") == 0 and not row.get("audit_error")
        for row in report["documents"])
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
