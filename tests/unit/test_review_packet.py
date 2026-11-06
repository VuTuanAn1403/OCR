"""Operator packets retain literal evidence, source geometry and pending status."""
import copy
import hashlib
import json

import pymupdf
import pytest

from ocr_pipeline.cli import main
from ocr_pipeline.review_packet import _crop, page_candidates, run_review


def page():
    return {"page": 1, "width": 300, "height": 400, "coordinate_space": "pdf_points_top_left",
            "transforms": [], "items": [], "text_evidence": {"items": []}}


def item(text, *, source="pdf:p0001:b000001", review=False):
    return {"id": source + "-export", "source_id": source, "kind": "b", "bbox": [20, 30, 200, 50],
            "text_raw": text, "text_corrected": text, "needs_review": review}


@pytest.mark.parametrize("text", ["Mô hình O2O", "Mã số 020", "Mã o2o"])
def test_lookalike_review_keeps_exact_numeric_and_lexical_source(text):
    data = page()
    data["items"] = [item(text)]
    original = copy.deepcopy(data)
    row, = page_candidates("doc", "a" * 64, data, ["O2O"])
    assert row["text_raw"] == row["text_corrected"] == text and row["proposal"] is None
    assert row["review_status"] == "UNREVIEWED" and row["priority"] == 0
    assert row["lookalike_tokens"] and data == original
    assert len(row["keyword_matches"]) == (0 if "020" in text else 1)


@pytest.mark.parametrize("text", ["59.670.020.000", "(149.020.821.436)", "2 020", "2\u00a0020", "2020", "12020",
                                 "Mã số VPĐD: 1600169024-020"])
def test_larger_numeric_fragments_are_not_misidentified_as_standalone_lookalikes(text):
    data = page()
    data["items"] = [item(text)]
    assert list(page_candidates("doc", "a" * 64, data, ["O2O"])) == []


def test_review_distinguishes_protected_and_ambiguous_occurrences_by_literal_offsets():
    data = page()
    raw = "Hội ồng: 1600169024-020; mô hình 020, O2O"
    corrected = raw.replace("Hội ồng", "Hội đồng")
    data["items"] = [{**item(raw), "text_corrected": corrected}]
    row, = page_candidates("doc", "a" * 64, data, ["O2O"])
    assert row["lookalike_tokens"] == ["020", "O2O"] and row["priority"] == 0
    assert len(row["keyword_matches"]) == 1
    for field, text in (("text_raw", raw), ("text_corrected", corrected)):
        protected, ambiguous, literal = row["lookalike_spans"][field]
        assert [text[span["start"]:span["end"]] for span in (protected, ambiguous, literal)] == ["020", "020", "O2O"]
        start, end = protected["larger_numeric_span"]
        assert text[start:end] == "1600169024-020"
        assert ambiguous["larger_numeric_span"] is None and literal["larger_numeric_span"] is None
    assert row["lookalike_spans"]["text_raw"][1]["start"] != row["lookalike_spans"]["text_corrected"][1]["start"]


def test_legacy_missing_raw_text_does_not_hide_corrected_lookalike():
    data = page()
    data["items"] = [{**item("Mô hình 020"), "text_raw": None}]
    row, = page_candidates("doc", "a" * 64, data, ["O2O"])
    assert row["text_raw"] is None and row["lookalike_spans"]["text_raw"] == []
    assert row["lookalike_tokens"] == ["020"]


def test_duplicate_pdf_bytes_still_have_separate_document_review_ids():
    data = page()
    data["items"] = [item("Mô hình 020")]
    a, = page_candidates("copy_a", "a" * 64, data, ["O2O"])
    b, = page_candidates("copy_b", "a" * 64, data, ["O2O"])
    assert a["review_id"] != b["review_id"] and a["source_id"] == b["source_id"]


@pytest.mark.parametrize("identity", ["source_id", "id"])
def test_layout_review_reasons_follow_the_source_or_legacy_export_identity(identity):
    data = page()
    target, other = item("Revenue"), item("Other", source="pdf:p0001:b000002")
    data["items"] = [target, other]
    data["layout_review"] = [{"code": "PULL_QUOTE_SEPARATED", "item_ids": [target[identity]]}]
    original = copy.deepcopy(data)
    row, = page_candidates("doc", "a" * 64, data, [])
    assert row["source_id"] == target["source_id"]
    assert row["locator"] == {"item_id": target["id"]}
    assert row["reasons"] == ["PULL_QUOTE_SEPARATED"] and data == original


def test_layout_review_keeps_an_unexported_frozen_source_pending():
    data = page()
    target = item("Revenue")
    data["text_evidence"]["items"] = [target]
    data["layout_review"] = [{"code": "UNRESOLVED_SOURCE", "item_ids": [target["source_id"]]}]
    row, = page_candidates("doc", "a" * 64, data, [])
    assert row["locator"] == {"frozen_source_id": target["source_id"]}
    assert row["reasons"] == ["UNRESOLVED_SOURCE"]


def test_frozen_repetition_and_table_cells_keep_distinct_source_locators():
    data = page()
    raw = item("thu thu thu", review=True)
    raw["fallback_reason"] = "repetition_noise_unverified"
    raw["recognition_provenance"] = {"repetition": {"candidate_text": "thu"}}
    data["text_evidence"]["items"] = [raw]
    table = item("020 | 020", source="pdf:p0001:t000001", review=True)
    table["kind"] = "t"
    table["cells"] = [{"row": 0, "col": col, "text_raw": "020", "text_corrected": "020",
                       "bbox": [], "needs_review": True, "bbox_source": "table_fallback"} for col in (0, 1)]
    data["items"] = [table]
    rows = list(page_candidates("doc", "a" * 64, data, ["thu"]))
    assert len({row["review_id"] for row in rows}) == len(rows) == 4
    frozen = next(row for row in rows if "frozen_source_id" in row["locator"])
    assert frozen["text_raw"] == "thu thu thu" and frozen["proposal"] == "thu"
    assert frozen["source_id"] == raw["source_id"]
    assert len([row for row in rows if "col" in row["locator"]]) == 2


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_crop_uses_display_space_and_preserves_cropbox_and_page_rotation(tmp_path, rotation):
    with pymupdf.open() as pdf:
        source = pdf.new_page(width=400, height=500)
        source.set_cropbox(pymupdf.Rect(50, 50, 350, 450))
        source.draw_rect(pymupdf.Rect(20, 30, 120, 70), color=(1, 0, 0), fill=(1, 0, 0))
        source.set_rotation(rotation)
        data = page()
        data.update(width=source.rect.width, height=source.rect.height)
        box = pymupdf.Rect(20, 30, 120, 70) * source.rotation_matrix
        data["items"] = [{**item("O2O"), "bbox": list(box)}]
        row, = page_candidates("doc", "a" * 64, data, ["O2O"])
        result = _crop(pdf, row, tmp_path)
        assert result["status"] == "AVAILABLE" and pdf[0].rotation == rotation
        image = pymupdf.Pixmap(str(tmp_path / result["assets"]["target"]["path"]))
        assert image.pixel(image.width // 2, image.height // 2) == (255, 0, 0)


def test_unplaced_and_unknown_transforms_remain_pending_without_misplaced_crop(tmp_path):
    with pymupdf.open() as pdf:
        pdf.new_page(width=300, height=400)
        data = page()
        data["items"] = [{**item("020"), "bbox": []}]
        row, = page_candidates("doc", "a" * 64, data, [])
        assert _crop(pdf, row, tmp_path) == {"status": "UNAVAILABLE", "reason": "unplaced_source"}
        row["bbox"] = [20, 30, 100, 50]
        row["transforms"] = [{"op": "unknown"}]
        assert _crop(pdf, row, tmp_path)["reason"] == "unsupported_page_transform"


@pytest.mark.parametrize("base_rotation,extra_rotation", [(0, 90), (90, 90), (180, 270)])
def test_recorded_orientation_fallback_maps_to_rotated_display_and_restores_page(tmp_path, base_rotation, extra_rotation):
    with pymupdf.open() as pdf:
        source = pdf.new_page(width=300, height=400)
        source.draw_rect(pymupdf.Rect(20, 30, 120, 70), fill=(1, 0, 0))
        source.set_rotation((base_rotation + extra_rotation) % 360)
        data = page()
        data.update(width=source.rect.width, height=source.rect.height,
                    coordinate_space="pdf_points_top_left_rotated", transforms=[{"op": "rotate", "degrees": extra_rotation}])
        box = pymupdf.Rect(20, 30, 120, 70) * source.rotation_matrix
        data["items"] = [{**item("020"), "bbox": list(box)}]
        source.set_rotation(base_rotation)
        row, = page_candidates("doc", "a" * 64, data, [])
        result = _crop(pdf, row, tmp_path)
        assert result["status"] == "AVAILABLE" and pdf[0].rotation == base_rotation
        image = pymupdf.Pixmap(str(tmp_path / result["assets"]["target"]["path"]))
        assert image.pixel(image.width // 2, image.height // 2) == (255, 0, 0)


def test_cli_review_reads_verified_legacy_source_without_ocr_or_source_changes(tmp_path, monkeypatch):
    from test_v63_pipeline import KEYWORDS, processor_factory, setup_inputs
    from test_analysis_run import tree_hashes
    from ocr_pipeline.batch import process_batch
    import ocr_pipeline.backend as backend
    source, batch = setup_inputs(tmp_path, 2)
    process_batch(source, batch, {}, KEYWORDS, processor_factory([]))
    before = tree_hashes(batch)
    monkeypatch.setattr(backend.GPUProcessor, "__call__", lambda *args, **kwargs: pytest.fail("review reached OCR"))
    output = tmp_path / "review"
    assert main(argv=["--review-from", str(batch), "--output", str(output), "--review-limit", "2"]) == 0
    report = json.loads((output / "packet.json").read_bytes())
    assert report["quality_acceptance"] == "NOT_EVALUATED" and report["contains_predictions"]
    assert report["selected_items"] > 0 and tree_hashes(batch) == before
    rows = json.loads((output / "review.json").read_bytes())["items"]
    assert len({row["review_id"] for row in rows}) == len(rows)
    annotations = json.loads((output / "annotations.template.json").read_bytes())
    assert all(row["text_after_review"] is None and row["seconds"] is None for row in annotations["items"])
    assert all(hashlib.sha256((output / name).read_bytes()).hexdigest() == checksum
               for name, checksum in report["files"].items())
    with pytest.raises(ValueError, match="new output"):
        run_review([batch], output, KEYWORDS)


def test_custom_keywords_trigger_dynamic_diacritic_guard():
    data = page()
    data["items"] = [item("Công ty đẩy mạnh chuyển đổi xánh nông nghiệp.")]
    # With custom keyword "chuyển đổi xanh", the anomaly "chuyển đổi xánh" is flagged
    rows = list(page_candidates("doc", "a" * 64, data, ["chuyển đổi xanh"]))
    assert len(rows) == 1
    reasons = rows[0]["reasons"]
    assert any("chuyển đổi xánh" in r and "chuyển đổi xanh" in r for r in reasons)

