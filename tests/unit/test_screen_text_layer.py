"""Text-layer screening sheets (GROUND_TRUTH_PROTOCOL 7.4): units, visibility, seal and re-check."""
import hashlib
import json
from pathlib import Path

import pymupdf
import pytest

from benchmark.ground_truth_tools import text_layer_reference as tlr
from scripts import screen_text_layer as screen

FONTS = [Path(p) for p in ("C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]
FONT = next((p for p in FONTS if p.is_file()), None)
needs_font = pytest.mark.skipif(FONT is None, reason="no TrueType font with Vietnamese glyphs")


def _pdf(path: Path, *, hidden=False) -> bytes:
    with pymupdf.open() as document:
        page = document.new_page(width=300, height=200)
        page.insert_font(fontname="vn", fontfile=str(FONT))
        page.insert_text((20, 40), "Hội đồng quản trị", fontname="vn", fontsize=14)
        page.insert_text((20, 80), "Báo cáo năm", fontname="vn", fontsize=14)
        if hidden:
            page.insert_text((20, 120), "Tiếng", fontname="vn", fontsize=14, render_mode=3)
            page.insert_text((20, 150), "Việt", fontname="vn", fontsize=14, color=(1, 1, 1))
            page.insert_text((150, 150), "Nam", fontname="vn", fontsize=14)
            page.draw_rect(pymupdf.Rect(145, 130, 200, 160), color=(0, 0, 0), fill=(0.2, 0.4, 0.8), overlay=True)
        document.save(path)
    return path.read_bytes()


def _lock(root: Path, pdf: Path, minimum: int) -> Path:
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    lock = {"parameters": {"seed": "TEST-SEED"},
            "documents": [{"pdf": pdf.name, "sha256": sha, "eligibility": "SCREENING_REQUIRED", "producer": "test",
                           "screening": {"minimum_slots": minimum, "worklist": [{"page": 1, "slots": 0}], "order": [1]}}]}
    path = root / "lock.json"
    path.write_text(json.dumps(lock), encoding="utf-8")
    return path


def _record(sheet, unit, decision, cause=None, stamp="2026-11-10T09:00:00+07:00"):
    return {"schema_version": screen.RECORD_SCHEMA, "decision_id": unit["unit_id"] + "#r1", "sheet_id": sheet["sheet_id"],
            "unit_id": unit["unit_id"], "pdf_sha256": sheet["pdf_sha256"], "page": unit["page"], "bbox": unit["bbox"],
            "char_start": unit["char_start"], "char_end": unit["char_end"], "text_layer": unit["text_layer"],
            "slots": unit["slots"], "crop_sha256": unit["crop_sha256"], "ab_order": None, "decision": decision,
            "cause": cause, "bulk": None, "reviewer": "reviewer", "decided_at": stamp, "tool_commit": None}


def _write(path: Path, records):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    return path


@needs_font
def test_units_carry_offsets_into_the_canonical_page_text(tmp_path):
    data = _pdf(tmp_path / "doc.pdf")
    with pymupdf.open(stream=data) as document:
        lines, canonical = tlr.extract_lines(document[0])
    words = [word for line in lines for word in line.words]
    assert [w.text for w in words] == ["Hội", "đồng", "quản", "trị", "Báo", "cáo", "năm"]
    for word in words:
        assert canonical[word.char_start:word.char_end] == word.text
    assert [w.slots for w in words] == [2, 3, 1, 1, 1, 1, 1]  # ộ shape+tone; đồng: stroke, shape, tone


@needs_font
def test_hidden_white_and_covered_text_leave_the_reference(tmp_path):
    units = tlr.page_units(_pdf(tmp_path / "doc.pdf", hidden=True), 1)
    verdicts = {word.text: word.visibility for line in units["lines"] for word in line.words}
    assert verdicts["Hội"] == verdicts["năm"] == "VISIBLE"
    assert verdicts["Tiếng"] == "INVISIBLE"  # render mode 3
    assert verdicts["Việt"] == "INVISIBLE"  # white on white
    assert verdicts["Nam"] == "INVISIBLE"  # drawn under an opaque rectangle
    assert units["visible_slots"] == units["slots"] - 4  # Tiếng 2, Việt 2; Nam has none


@needs_font
def test_seal_accepts_rejects_or_waits_for_more_slots(tmp_path):
    pdf = tmp_path / "doc.pdf"
    _pdf(pdf)
    sheet_dir = tmp_path / "sheet"
    sheet = screen.build_sheet(_lock(tmp_path, pdf, minimum=11), tmp_path, "doc.pdf", sheet_dir, "reviewer")
    assert sheet["totals"] == {"units": 7, "slots": 10, "excluded_units": 0, "excluded_slots": 0}
    html = (sheet_dir / "index.html").read_text(encoding="utf-8")
    assert sheet["sheet_id"] in html and "/*__SHEET__*/null" not in html
    units = sheet["units"]

    all_match = _write(tmp_path / "match.jsonl", [_record(sheet, u, "MATCH") for u in units])
    report = screen.seal(sheet_dir, [all_match], tmp_path / "seal-a")
    assert report["verdict"]["status"] == "INCOMPLETE"  # 10 MATCH slots < minimum 11
    assert (tmp_path / "seal-a" / report["sealed_file"]).is_file()

    one_bad = [_record(sheet, u, "MATCH") for u in units[1:]] + [_record(sheet, units[0], "MISMATCH", "MISSING_MARK")]
    report = screen.seal(sheet_dir, [_write(tmp_path / "bad.jsonl", one_bad)], tmp_path / "seal-b")
    assert report["verdict"]["status"] == "REJECTED"
    assert report["verdict"]["mismatch_causes"] == {"MISSING_MARK": 1}

    sheet_dir2 = tmp_path / "sheet2"
    sheet2 = screen.build_sheet(_lock(tmp_path, pdf, minimum=9), tmp_path, "doc.pdf", sheet_dir2, "reviewer")
    unresolved = [_record(sheet2, sheet2["units"][0], "UNRESOLVED")] + [_record(sheet2, u, "MATCH") for u in sheet2["units"][1:]]
    report = screen.seal(sheet_dir2, [_write(tmp_path / "ok.jsonl", unresolved)], tmp_path / "seal-c")
    assert report["verdict"]["status"] == "INCOMPLETE"  # UNRESOLVED slots do not count: 10 - 2 < 9
    accept = [_record(sheet2, u, "MATCH") for u in sheet2["units"]]
    report = screen.seal(sheet_dir2, [_write(tmp_path / "all.jsonl", accept)], tmp_path / "seal-d")
    assert report["verdict"]["status"] == "ACCEPTED"
    assert report["verdict"]["text_layer_error_upper_bound_95"] == pytest.approx(1 - 0.05 ** (1 / 10), abs=1e-6)
    with pytest.raises(FileExistsError):
        screen.seal(sheet_dir2, [tmp_path / "all.jsonl"], tmp_path / "seal-d")


@needs_font
def test_seal_refuses_records_that_do_not_match_the_sheet(tmp_path):
    pdf = tmp_path / "doc.pdf"
    _pdf(pdf)
    sheet = screen.build_sheet(_lock(tmp_path, pdf, minimum=1), tmp_path, "doc.pdf", tmp_path / "sheet", "reviewer")
    unit = sheet["units"][0]
    cases = {
        "crop_sha256 differs": dict(_record(sheet, unit, "MATCH"), crop_sha256="0" * 64),
        "needs a cause": _record(sheet, unit, "MISMATCH"),
        "not Asia/Bangkok": _record(sheet, unit, "MATCH", stamp="2026-11-10T02:00:00Z"),
        "is not on the sheet": dict(_record(sheet, unit, "MATCH"), unit_id="other"),
    }
    for index, (message, record) in enumerate(cases.items()):
        with pytest.raises(ValueError, match=message):
            screen.seal(tmp_path / "sheet", [_write(tmp_path / f"r{index}.jsonl", [record])], tmp_path / f"s{index}")
    twice = [_record(sheet, unit, "MATCH"), _record(sheet, unit, "UNRESOLVED")]
    with pytest.raises(ValueError, match="decided twice"):
        screen.seal(tmp_path / "sheet", [_write(tmp_path / "twice.jsonl", twice)], tmp_path / "s-twice")


@needs_font
def test_recheck_sheet_is_blind_and_seeded(tmp_path):
    pdf = tmp_path / "doc.pdf"
    _pdf(pdf)
    sheet = screen.build_sheet(_lock(tmp_path, pdf, minimum=1), tmp_path, "doc.pdf", tmp_path / "sheet", "reviewer")
    records = [_record(sheet, u, "MATCH") for u in sheet["units"]]
    report = screen.seal(tmp_path / "sheet", [_write(tmp_path / "d.jsonl", records)], tmp_path / "sealed")
    recheck = screen.build_recheck(tmp_path / "sheet", tmp_path / "sealed" / "seal.json", tmp_path / "recheck")
    assert recheck["mode"] == "recheck" and recheck["parent_sealed_sha256"] == report["sealed_sha256"]
    assert len(recheck["units"]) == 7  # fewer than the minimum of 50, so all of them
    html = (tmp_path / "recheck" / "index.html").read_text(encoding="utf-8")
    assert '"decision": "MATCH"' not in html and "#r1" not in html  # earlier decisions are not shown
    again = [dict(_record(recheck, u, "MATCH"), sheet_id=recheck["sheet_id"]) for u in recheck["units"]]
    again[0]["decision"] = "UNRESOLVED"
    agreement = screen.compare_recheck(tmp_path / "sealed" / "seal.json", tmp_path / "recheck",
                                       [_write(tmp_path / "again.jsonl", again)])
    assert agreement["needs_third_review"] == [recheck["units"][0]["unit_id"]]
    assert agreement["agreement"] == pytest.approx(6 / 7, abs=1e-6)


def test_recheck_sample_takes_ten_percent_with_a_floor_of_fifty():
    ids = [f"d{i}" for i in range(1000)]
    sample = screen.recheck_sample(ids, "SEED")
    assert len(sample) == 100 and sample == screen.recheck_sample(list(reversed(ids)), "SEED")
    assert len(screen.recheck_sample(ids[:120], "SEED")) == 50
    assert len(screen.recheck_sample(ids[:30], "SEED")) == 30
