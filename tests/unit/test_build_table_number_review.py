"""build_table_number_review: a look-at-the-page worklist for untraceable table numbers (V8-080)."""
import hashlib
import json
from pathlib import Path

import pymupdf
import pytest

from scripts import build_table_number_review as review


def _output(tmp_path: Path):
    pdf = tmp_path / "pdfs" / "DOC.pdf"
    pdf.parent.mkdir()
    with pymupdf.open() as document:
        page = document.new_page(width=300, height=200)
        page.insert_text((20, 40), "Doanh thu 1.234")
        page.insert_text((20, 80), "2016")
        document.save(pdf)
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    evidence = [{"source_id": "s1", "text_raw": "Doanh thu 1.234", "bbox": [20, 28, 110, 42]},
                {"source_id": "s2", "text_raw": "2016", "bbox": [20, 68, 50, 82]}]
    table = {"kind": "t", "table_id": "t1", "source": "heuristic", "cells": [
        {"row": 0, "col": 0, "text_raw": "Doanh thu", "bbox": [15, 25, 120, 45]},   # its line's 1.234 is in no cell
        {"row": 1, "col": 0, "text_raw": "2016", "bbox": [15, 65, 60, 85]},         # traced
        {"row": 1, "col": 1, "text_raw": "2017", "bbox": [15, 65, 60, 85]},         # repeated box: counted, not listed
        {"row": 2, "col": 0, "text_raw": "999", "bbox": [150, 150, 200, 170]}]}     # no source line
    doc = tmp_path / "output" / "DOC"
    (doc / "pages").mkdir(parents=True)
    (doc / "extraction.json").write_text(json.dumps({"doc_sha16": sha[:16], "pages": [
        {"page": 1, "coordinate_space": "pdf_points_top_left", "transforms": [], "items": [table],
         "text_evidence": {"items": evidence}}]}), encoding="utf-8")
    (doc / "pages" / "page-0001.json").write_text(json.dumps({"page_num": 1, "tables": []}), encoding="utf-8")
    return tmp_path / "output", pdf.parent


def _decisions(tmp_path, manifest, choices, name="d"):
    records = [{"schema_version": review.RECORD_SCHEMA, "decision_id": item["item_id"] + "#r1",
                "sheet_id": manifest["sheet_id"], "item_id": item["item_id"], "kind": item["kind"],
                "number": item["number"], "image_sha256": item["image_sha256"], "choice": choices[item["kind"]],
                "reviewer": "reviewer", "decided_at": "2026-11-10T10:00:00+07:00", "tool_commit": None}
               for item in manifest["items"]]
    path = tmp_path / f"{name}.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path, records


def test_sheet_lists_lost_and_untraced_numbers_and_counts_repeated_boxes_apart(tmp_path):
    output, pdf_root = _output(tmp_path)
    manifest = review.build_sheet(output, pdf_root, tmp_path / "sheet", "reviewer")
    assert [(i["kind"], i["number"], i["row"], i["col"]) for i in manifest["items"]] == [
        ("MISSING_FROM_TABLE", "1.234", 0, 0), ("UNTRACED", "999", 2, 0)]
    assert manifest["skipped"] == {"untraced_cells_with_a_repeated_box": 1}
    lost = manifest["items"][0]
    assert lost["lines"] == ["Doanh thu 1.234"] and lost["cell_px"] == [45.0, 75.0, 360.0, 135.0]
    assert (tmp_path / "sheet" / manifest["pages"][lost["image"]]["image"]).is_file()
    html = (tmp_path / "sheet" / "index.html").read_text(encoding="utf-8")
    assert manifest["sheet_id"] in html and "/*__SHEET__*/null" not in html
    with pytest.raises(FileExistsError):
        review.build_sheet(output, pdf_root, tmp_path / "sheet", "reviewer")


def test_seal_needs_every_item_keeps_the_latest_revision_and_names_the_outcome(tmp_path):
    output, pdf_root = _output(tmp_path)
    manifest = review.build_sheet(output, pdf_root, tmp_path / "sheet", "reviewer")
    first, records = _decisions(tmp_path, manifest, {"MISSING_FROM_TABLE": "NOT_IN_IMAGE", "UNTRACED": "NOT_IN_IMAGE"})
    with pytest.raises(ValueError, match="1 items have no decision"):
        review.seal(tmp_path / "sheet", [_decisions(tmp_path, {**manifest, "items": manifest["items"][:1]},
                                                    {"MISSING_FROM_TABLE": "IN_IMAGE"}, "part")[0]], tmp_path / "x")
    revised = dict(records[0], decision_id=records[0]["item_id"] + "#r2", choice="IN_IMAGE")
    second = tmp_path / "second.jsonl"
    second.write_text(json.dumps(revised) + "\n", encoding="utf-8")
    report = review.seal(tmp_path / "sheet", [first, second], tmp_path / "sealed")
    assert report["outcomes"] == {"TABLE_LOST_A_PRINTED_NUMBER": 1, "TABLE_NUMBER_NOT_PRINTED": 1}
    assert report["quality_acceptance"] == "NOT_EVALUATED" and report["skipped"] == manifest["skipped"]
    sealed = (tmp_path / "sealed" / report["sealed_file"]).read_bytes()
    assert hashlib.sha256(sealed).hexdigest() == report["sealed_sha256"]
    with pytest.raises(FileExistsError):
        review.seal(tmp_path / "sheet", [first, second], tmp_path / "sealed")


def test_seal_refuses_records_that_do_not_match_the_sheet(tmp_path):
    output, pdf_root = _output(tmp_path)
    manifest = review.build_sheet(output, pdf_root, tmp_path / "sheet", "reviewer")
    path, records = _decisions(tmp_path, manifest, {"MISSING_FROM_TABLE": "MAYBE", "UNTRACED": "IN_IMAGE"})
    records[1]["decided_at"] = "2026-11-10T03:00:00Z"
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    with pytest.raises(ValueError) as error:
        review.seal(tmp_path / "sheet", [path], tmp_path / "sealed")
    assert "choice 'MAYBE'" in str(error.value) and "not Asia/Bangkok" in str(error.value)
