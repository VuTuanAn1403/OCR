"""scripts/compare_detector_snapshots.py: paired detector snapshots, agreement is not accuracy."""
import hashlib
import json
import sqlite3
from pathlib import Path

import pymupdf
import pytest

from scripts import compare_detector_snapshots as compare

WIDTH, HEIGHT = 100.0, 200.0
SHAPE = [400, 200, 3]  # 2 px per point
FONTS = [Path(p) for p in ("C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]
FONT = next((p for p in FONTS if p.is_file()), None)


def _snapshot(boxes, sha="a" * 64):
    detections = []
    for index, (x0, y0, x1, y1) in enumerate(boxes):
        detections.append({"id": f"d{index:06d}", "bbox": [x0, y0, x1, y1], "score": 0.9,
                           "polygon": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]})
    return {"schema_version": "primary-text-detections-v1", "status": "CAPTURED", "method": "onnx-db-map-v1",
            "input_image": {"shape": SHAPE, "dtype": "uint8", "color_space": "BGR", "sha256": sha},
            "page_size": [WIDTH, HEIGHT], "pixel_to_page": [[0.5, 0.0, 0.0], [0.0, 0.5, 0.0], [0.0, 0.0, 1.0]],
            "detections": detections}


def _page(boxes, sha="a" * 64):
    identity = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    return {"page_num": 1, "width": WIDTH, "height": HEIGHT, "rendered_dpi": 180,
            "metadata": {"coordinate_space": {"name": "pdf_display_points",
                                              "native_to_output": {"steps": [{"matrix": identity}]}},
                         "primary_text_detection": _snapshot(boxes, sha)}}


def _run(root: Path, name: str, boxes, *, pdf_sha="f" * 64, sha="a" * 64, completed=True, outcome="SUCCEEDED"):
    run = root / name
    doc = run / "DOC"
    (doc / "pages").mkdir(parents=True)
    with sqlite3.connect(run / "batch_state.sqlite") as connection:
        connection.execute("create table documents (id text, ordinal integer, payload text)")
        payload = {"outcome": outcome, "pdf_sha256": pdf_sha, "total_pages": 1}
        connection.execute("insert into documents values ('DOC', 0, ?)", (json.dumps(payload),))
    if completed:
        (doc / "COMPLETED.json").write_text("{}", encoding="utf-8")
    extraction = {"pages": [{"page": 1, "width": WIDTH, "height": HEIGHT,
                             "coordinate_space": "pdf_points_top_left", "transforms": []}]}
    (doc / "extraction.json").write_text(json.dumps(extraction), encoding="utf-8")
    (doc / "pages" / "page-0001.json").write_text(json.dumps(_page(boxes, sha)), encoding="utf-8")
    return run


def _lock(root: Path, name: str):
    lock = {"lock_id": name, "git": {"head": "0" * 40, "full_diff_sha256": "1" * 64},
            "code": {"code_fingerprints": {"extraction": "a" * 16, "analysis": "b" * 16, "publication": "c" * 16}},
            "config": {"sha256": "2" * 64}, "models": {"registry": "missing/registry.json", "sha256": {}},
            "gpu": {"gpus": [{"name": "GPU", "driver": "1", "memory_total": "4096 MiB"}], "driver_cuda_version": "13"}}
    path = root / f"{name}.json"
    path.write_text(json.dumps(lock), encoding="utf-8")
    return path


def _build(tmp_path, base, cand, **options):
    return compare.build(base, cand, pdf_root=options.get("pdf_root"), inventory=options.get("inventory"),
                         base_exit=0, cand_exit=None, baseline_lock=_lock(tmp_path, "L2"),
                         candidate_lock=_lock(tmp_path, "L3"), experiment_id="EXP-V8-DET-20261109-001")


def test_agreement_counts_matched_candidate_only_and_baseline_only_boxes(tmp_path):
    # pixel boxes; the second baseline box has no candidate, the candidate adds one elsewhere
    base = _run(tmp_path, "v4", [(20, 20, 180, 60), (20, 100, 180, 140)])
    cand = _run(tmp_path, "v6", [(22, 22, 178, 58), (20, 300, 100, 340)])
    report = _build(tmp_path, base, cand)
    agreement = report["overall_paired_scope"]["agreement"]
    assert (agreement["matched"], agreement["candidate_only"], agreement["baseline_only"]) == (1, 1, 1)
    assert agreement["candidate_boxes_matched_share"] == 0.5 and agreement["baseline_boxes_matched_share"] == 0.5
    assert 0.8 < agreement["mean_iou"] < 1
    assert report["quality_acceptance"] == "NOT_EVALUATED"
    assert report["decision_options"] == ["INCONCLUSIVE"]  # no locked protocol, no independent GT
    assert report["pair_validation"]["status"] == "INCONCLUSIVE"


def test_pages_on_different_pixels_and_missing_documents_are_not_paired(tmp_path):
    base = _run(tmp_path, "v4", [(20, 20, 180, 60)])
    cand = _run(tmp_path, "v6", [(20, 20, 180, 60)], sha="b" * 64)
    report = _build(tmp_path, base, cand)
    assert report["coverage"]["paired_pages"] == 0
    assert report["overall_paired_scope"]["unpaired"] == ["INPUT_PIXELS_DIFFER"]
    missing = _run(tmp_path, "v6b", [(20, 20, 180, 60)], completed=False, outcome="FAILED_DOCUMENT")
    report = _build(tmp_path, base, missing)
    assert report["coverage"]["missing_documents"] == [
        {"document": "DOC", "baseline_outcome": "SUCCEEDED", "candidate_outcome": "FAILED_DOCUMENT"}]
    assert report["coverage"]["declared_pages"] == 1 and report["coverage"]["paired_pages"] == 0


def test_different_pdf_bytes_are_refused(tmp_path):
    base = _run(tmp_path, "v4", [(20, 20, 180, 60)])
    cand = _run(tmp_path, "v6", [(20, 20, 180, 60)], pdf_sha="e" * 64)
    with pytest.raises(ValueError, match="different PDF bytes"):
        _build(tmp_path, base, cand)


def test_clip_drops_zero_area_reference_boxes():
    regions, dropped = compare.clip_regions([[-5, 10, 50, 20], [10, 10, 10, 30], [90, 190, 120, 230]], 100, 200, "b")
    assert dropped == 1
    assert regions[0]["bbox"] == [0.0, 10, 50, 20] and regions[1]["bbox"] == [90, 190, 100, 200]


@pytest.mark.skipif(FONT is None, reason="no TrueType font with Vietnamese glyphs")
def test_text_layer_lines_score_both_runs_as_a_diagnostic(tmp_path):
    pdf_root = tmp_path / "pdfs"
    pdf_root.mkdir()
    pdf = pdf_root / "DOC.pdf"
    with pymupdf.open() as document:
        page = document.new_page(width=WIDTH, height=HEIGHT)
        page.insert_font(fontname="vn", fontfile=str(FONT))
        page.insert_text((10, 30), "Hội đồng", fontname="vn", fontsize=10)
        document.save(pdf)
    pdf_sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    with pymupdf.open(pdf) as document:
        line = compare.text_layer_lines(document[0])[0]
    pixels = [value * 2 for value in line]
    base = _run(tmp_path, "v4", [pixels], pdf_sha=pdf_sha)
    cand = _run(tmp_path, "v6", [pixels, (20, 300, 100, 340)], pdf_sha=pdf_sha)
    inventory = {"documents": [{"pdf": "DOC.pdf", "sha256": pdf_sha, "page_records": [
        {"page": 1, "status": "CANDIDATE", "max_image_cover": 0.0}]}]}
    report = _build(tmp_path, base, cand, pdf_root=pdf_root, inventory=inventory)
    layer = report["overall_paired_scope"]["text_layer"]
    assert layer["baseline"]["observed_counts"] == {"tp": 1, "fp": 0, "fn": 0}
    assert layer["candidate"]["observed_counts"] == {"tp": 1, "fp": 1, "fn": 0}
    assert layer["paired_pages"] == {"pages": 1, "candidate_higher": 0, "candidate_lower": 1, "tied": 0}
    assert report["coverage"]["text_layer_states"] == {"SCORED": 1}
