"""measure_text_layer_diacritics: screened text layer vs OCR, matched by bbox (protocol 7.3, 7.4 C)."""
import hashlib
import json
import sqlite3
from pathlib import Path

import pymupdf
import pytest

from benchmark.ground_truth_tools import text_layer_reference as tlr
from scripts import lock_text_layer_measurement as lock_v3
from scripts import measure_text_layer_diacritics as measure
from scripts import screen_text_layer as screen

FONTS = [Path(p) for p in ("C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]
FONT = next((p for p in FONTS if p.is_file()), None)
pytestmark = pytest.mark.skipif(FONT is None, reason="no TrueType font with Vietnamese glyphs")


def _setup(tmp_path: Path, minimum: int = 1):
    pdf = tmp_path / "pdfs" / "DOC.pdf"
    pdf.parent.mkdir()
    with pymupdf.open() as document:
        page = document.new_page(width=300, height=200)
        page.insert_font(fontname="vn", fontfile=str(FONT))
        page.insert_text((20, 40), "Hội đồng quản trị", fontname="vn", fontsize=14)
        page.insert_text((20, 80), "Báo cáo năm", fontname="vn", fontsize=14)
        page.insert_text((20, 120), "Tiếng", fontname="vn", fontsize=14, render_mode=3)
        document.save(pdf)
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps({"documents": [{"pdf": "DOC.pdf", "sha256": sha, "page_records": [
        {"page": 1, "status": "CANDIDATE", "diacritic_slots": 12}]}]}), encoding="utf-8")
    lock = tmp_path / "lock.json"
    lock.write_text(json.dumps({
        "schema_version": "ocr-v8-text-layer-procedure-lock-v1", "procedure_version": 1, "status": "LOCKED_PROCEDURE",
        "inventory": {"path": str(inventory), "sha256": hashlib.sha256(inventory.read_bytes()).hexdigest()},
        "parameters": {"seed": "TEST", "confidence": 0.95, "maximum_error_rate": 1e-4, "metric": "DSER_strict"},
        "documents": [{"pdf": "DOC.pdf", "sha256": sha, "partition": "development", "eligibility": "SCREENING_REQUIRED",
                       "screening": {"minimum_slots": minimum, "worklist": [{"page": 1}], "order": [1]}}]}), encoding="utf-8")
    with pymupdf.open(pdf) as document:
        lines, _ = tlr.extract_lines(document[0])
    return pdf, sha, lock, {" ".join(line.text.split()): line.bbox for line in lines}  # PyMuPDF yields NBSP


def _seal(tmp_path: Path, pdf: Path, lock: Path, name: str) -> Path:
    sheet_dir = tmp_path / f"sheet-{name}"
    sheet = screen.build_sheet(lock, pdf.parent, pdf.name, sheet_dir, "reviewer")
    records = [{"schema_version": screen.RECORD_SCHEMA, "decision_id": u["unit_id"] + "#r1", "sheet_id": sheet["sheet_id"],
                "unit_id": u["unit_id"], "pdf_sha256": sheet["pdf_sha256"], "page": u["page"], "bbox": u["bbox"],
                "char_start": u["char_start"], "char_end": u["char_end"], "text_layer": u["text_layer"],
                "slots": u["slots"], "crop_sha256": u["crop_sha256"], "ab_order": None, "decision": "MATCH",
                "cause": None, "bulk": None, "reviewer": "reviewer", "decided_at": "2026-11-10T09:00:00+07:00",
                "tool_commit": None} for u in sheet["units"]]
    decisions = tmp_path / f"decisions-{name}.jsonl"
    decisions.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    screen.seal(sheet_dir, [decisions], tmp_path / f"sealed-{name}")
    return tmp_path / f"sealed-{name}" / "seal.json"


def _output(tmp_path: Path, sha: str, items, identity_status="MATCH", tables=(), evidence=None):
    output = tmp_path / "output"
    (output / "DOC").mkdir(parents=True)
    with sqlite3.connect(output / "batch_state.sqlite") as connection:
        connection.execute("create table documents (id text, ordinal integer, payload text)")
        connection.execute("insert into documents values ('DOC', 0, ?)", (json.dumps({"pdf_sha256": sha, "outcome": "SUCCEEDED"}),))
    (output / "DOC" / "COMPLETED.json").write_text("{}", encoding="utf-8")
    extraction = {"pages": [{"page": 1, "coordinate_space": "pdf_points_top_left", "transforms": [], "items": [
        {"kind": "b", "source_id": f"s{index}", "bbox": list(box), "text_corrected": text, "text_raw": text}
        for index, (text, box) in enumerate(items)] + [{"kind": "t", "bbox": list(box), "cells": []} for box in tables]}]}
    if evidence is not None:
        extraction["pages"][0]["text_evidence"] = {"items": [
            {"source_id": f"e{index}", "bbox": list(box), "text_corrected": text, "text_raw": text}
            for index, (text, box) in enumerate(evidence)]}
    (output / "DOC" / "extraction.json").write_text(json.dumps(extraction, ensure_ascii=False), encoding="utf-8")
    identity = tmp_path / "identity.json"
    identity.write_text(json.dumps({"status": identity_status, "output": str(output), "lock_id": "L",
                                    "documents": [{"id": "DOC", "receipt_valid": True, "full_pages": True}]}), encoding="utf-8")
    return output, identity


def measurement_lock(tmp_path: Path, lock: Path, *, draft: bool = False, stream: str = "text_corrected",
                     matching: str = measure.MATCHING_METHOD, sample=None, partial: bool = False) -> Path:
    decision = {} if draft else {"reviewer": "reviewer", "decided_on": "2026-11-10"}
    built = lock_v3.build_lock(str(lock), draft=draft, stream=stream, matching=matching, adjudication_sample=sample,
                               adjudication_partial=partial, **decision)
    suffix = (("" if matching == measure.MATCHING_METHOD else f"-{matching}") + (f"-sample{sample}" if sample else "")
              + ("-partial" if partial else ""))
    path = tmp_path / f"lock-v2-{'draft' if draft else stream}{suffix}.json"
    path.write_text(lock_v3.dump(built), encoding="utf-8")
    return path


def _build(tmp_path, lock, seal, identity, output, **options):
    return measure.build(lock, [seal], identity, output, tmp_path / "pdfs", "text_corrected",
                         measurement_lock=measurement_lock(tmp_path, lock, **options))


def test_measurement_refuses_without_a_locked_measurement_lock_for_the_same_stream(tmp_path):
    pdf, sha, lock, boxes = _setup(tmp_path)
    seal = _seal(tmp_path, pdf, lock, "v2")
    output, identity = _output(tmp_path, sha, [("Hội đồng quản trị", boxes["Hội đồng quản trị"])])
    with pytest.raises(lock_v3.LockError, match="DRAFT_NOT_LOCKED"):
        _build(tmp_path, lock, seal, identity, output, draft=True)
    with pytest.raises(lock_v3.LockError, match="locked stream is text_raw"):
        _build(tmp_path, lock, seal, identity, output, stream="text_raw")
    report = _build(tmp_path, lock, seal, identity, output)
    assert report["measurement_lock"]["status"] == "LOCKED_PROCEDURE"


@pytest.mark.parametrize("matching,deleted,table_slots,ref_slots", [
    ("bbox-connected-groups-v1", 3, 0, 10),            # lock v2: table text has no OCR line
    ("bbox-connected-groups-phase-a-v1", 0, 0, 10),    # phase-A lines cover the table text
    ("bbox-connected-groups-no-tables-v1", 0, 3, 7)])  # table text leaves the sample
def test_the_locked_matching_rule_decides_how_table_text_is_counted(tmp_path, matching, deleted, table_slots, ref_slots):
    pdf, sha, lock, boxes = _setup(tmp_path)
    seal = _seal(tmp_path, pdf, lock, "t")
    x0, y0, x1, y1 = boxes["Báo cáo năm"]
    output, identity = _output(tmp_path, sha, [("Hội đồng quản trị", boxes["Hội đồng quản trị"])],
                               tables=[(x0 - 5, y0 - 5, x1 + 5, y1 + 5)],
                               evidence=[("Hội đồng quản trị", boxes["Hội đồng quản trị"]), ("Báo cáo năm", boxes["Báo cáo năm"])])
    report = _build(tmp_path, lock, seal, identity, output, matching=matching)
    assert report["matching"]["method"] == report["measurement_lock"]["matching"] == matching
    assert report["dser_strict"]["deleted_slots"] == deleted and report["dser_strict"]["ref_slots"] == ref_slots
    assert report["documents"][0]["excluded"]["TABLE_REGION_SLOTS"] == table_slots


def test_measurement_refuses_a_text_layer_that_is_not_accepted(tmp_path):
    pdf, sha, lock, boxes = _setup(tmp_path, minimum=99)  # 10 MATCH slots < 99: INCOMPLETE
    seal = _seal(tmp_path, pdf, lock, "a")
    output, identity = _output(tmp_path, sha, [("Hội đồng quản trị", boxes["Hội đồng quản trị"])])
    with pytest.raises(ValueError, match="not ACCEPTED"):
        _build(tmp_path, lock, seal, identity, output)


def test_slot_errors_deleted_lines_hidden_text_and_stray_ocr_lines(tmp_path):
    pdf, sha, lock, boxes = _setup(tmp_path)
    seal = _seal(tmp_path, pdf, lock, "b")
    stray = (20.0, 170.0, 120.0, 185.0)
    output, identity = _output(tmp_path, sha, [("Hội đồng quản tri", boxes["Hội đồng quản trị"]), ("chữ trong ảnh", stray)])
    report = _build(tmp_path, lock, seal, identity, output)
    strict = report["dser_strict"]
    assert strict["ref_slots"] == 10  # Hội 2 + đồng 3 + quản 1 + trị 1 + Báo cáo năm 3; Tiếng is hidden
    assert strict["tone_errors"] == 1 and strict["deleted_slots"] == 3 and strict["dser_errors"] == 4
    document = report["documents"][0]
    assert document["excluded"]["NOT_VISIBLE_SLOTS"] == 2 and document["unmatched_ocr_lines"] == 1
    assert report["adjudication_units"] == 2 and report["adjudication_status"] == "PENDING_REVIEW"
    assert report["claim_status"] == "NOT_EVALUATED"
    assert report["gate_in_sample"]["status"] == "FAIL"  # 4/10 is far above 1e-4
    assert report["page_icc"]["status"] == "NOT_EVALUATED"  # one page cannot give rho


def test_split_and_reordered_ocr_lines_are_not_errors(tmp_path):
    pdf, sha, lock, boxes = _setup(tmp_path)
    seal = _seal(tmp_path, pdf, lock, "c")
    x0, y0, x1, y1 = boxes["Hội đồng quản trị"]
    middle = (x0 + x1) / 2
    items = [("Báo cáo năm", boxes["Báo cáo năm"]), ("quản trị", (middle, y0, x1, y1)), ("Hội đồng", (x0, y0, middle, y1))]
    output, identity = _output(tmp_path, sha, items)
    report = _build(tmp_path, lock, seal, identity, output)
    assert report["dser_strict"]["dser_errors"] == 0 and report["dser_strict"]["ref_slots"] == 10
    assert report["adjudication_status"] == "NOT_NEEDED"


def test_identity_must_match_the_measured_output(tmp_path):
    pdf, sha, lock, boxes = _setup(tmp_path)
    seal = _seal(tmp_path, pdf, lock, "d")
    output, identity = _output(tmp_path, sha, [("Hội đồng quản trị", boxes["Hội đồng quản trị"])], identity_status="DRIFT")
    with pytest.raises(ValueError, match="not MATCH"):
        _build(tmp_path, lock, seal, identity, output)
