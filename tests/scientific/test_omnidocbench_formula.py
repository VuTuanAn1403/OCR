"""Source-bound formula preparation and scoring controls, not OCR accuracy tests."""
import json

import pymupdf
import pytest

from benchmark.scientific_evaluation import omnidocbench_corpus as corpus
from benchmark.scientific_evaluation import omnidocbench_formula as formula
from ocr_artifacts.hashing import sha256_file


def write(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")
    return sha256_file(path)


@pytest.fixture
def prepared(tmp_path):
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 100, 80), False)
    pix.clear_with(255)
    pix.save(dataset / "page.png")
    block = {"category_type": "equation_isolated", "anno_id": "original-id", "ignore": False,
             "poly": [10, 10, 40, 10, 40, 30, 10, 30], "latex": "$$x_{020}$$"}
    gt = [{"page_info": {"image_path": "page.png", "width": 100, "height": 80}, "layout_dets": [block]}]
    gt_path = dataset / "gt.json"
    gt_hash = write(gt_path, gt)
    inputs = tmp_path / "prepared-inputs"
    corpus.prepare_corpus(gt_path, gt_hash, dataset, ".", "CONTROL_NOT_GT", "a" * 40, inputs, dpi=216)
    plan = inputs / "export-plan.json"
    output = tmp_path / "labels"
    formula.prepare(plan, sha256_file(plan), dataset, inputs / "inputs", output)
    return dataset, inputs, output


def test_preparation_preserves_raw_latex_and_source_geometry(prepared):
    _, inputs, output = prepared
    labels = json.loads((output / "annotations.json").read_text())
    page = labels["documents"][0]["pages"][0]
    row = page["formulas"][0]
    with pymupdf.open(next((inputs / "inputs").glob("*.pdf"))) as pdf:
        rect = pdf[0].rect
        assert (rect.width, rect.height) != (page["width"], page["height"])
        assert (page["width"], page["height"]) == (round(rect.width, 2), round(rect.height, 2))
    assert row["bbox"] == pytest.approx([page["width"] * .1, page["height"] * .125,
                                         page["width"] * .4, page["height"] * .375])
    assert row["content_raw"] == "$$x_{020}$$" and row["format"] == "LATEX"
    assert row["source_anno_id"] == "original-id" and row["equation_label"] is None
    report = json.loads((output / "prepared.json").read_text())
    assert report["formula_references"] == {"display": 1}
    assert report["quality_acceptance"] == "NOT_EVALUATED"


@pytest.mark.parametrize("change", ["plan", "image", "pdf", "membership", "alias"])
def test_preparation_rejects_source_changes(prepared, tmp_path, change):
    dataset, inputs, _ = prepared
    plan = inputs / "export-plan.json"
    expected = sha256_file(plan)
    if change == "plan":
        expected = "0" * 64
    elif change == "image":
        (dataset / "page.png").write_bytes(b"changed")
    elif change == "pdf":
        next((inputs / "inputs").glob("*.pdf")).write_bytes(b"changed")
    elif change == "membership":
        (inputs / "inputs" / "extra.pdf").write_bytes(b"extra")
    else:
        data = json.loads(plan.read_text())
        data["sources"].append(data["sources"][0])
        expected = write(plan, data)
    output = tmp_path / "invalid"
    with pytest.raises(ValueError):
        formula.prepare(plan, expected, dataset, inputs / "inputs", output)
    assert not output.exists()


def test_inline_ignored_and_invalid_geometry_are_explicit():
    item = {"category_type": "equation_inline", "poly": [1, 2, 9, 2, 9, 4, 1, 4], "latex": "$x$"}
    gt = {"page_info": {"width": 10, "height": 10}, "layout_dets": [
        {"category_type": "text_block", "line_with_spans": [item, {**item, "ignore": True}]}]}
    page, _ = formula._page_labels(gt, 20, 20)
    assert len(page["formulas"]) == len(page["ignore_regions"]) == 1
    assert page["formulas"][0]["placement"] == "inline"
    item["poly"][0] = -1
    with pytest.raises(ValueError, match="outside"):
        formula._page_labels(gt, 20, 20)


def publication(prepared, tmp_path, monkeypatch, *, missing=False):
    _, _, labels = prepared
    document = json.loads((labels / "annotations.json").read_text())["documents"][0]
    page = document["pages"][0]
    reference = page["formulas"][0]
    directory = tmp_path / "prediction"
    directory.mkdir()
    item = {"id": "prediction-formula", "kind": "f", "bbox": reference["bbox"],
            "text_raw": reference["content_raw"], "latex": reference["content_raw"], "source": "CONTROL"}
    extraction = {"doc_id": document["document_id"], "doc_sha16": document["pdf_sha256"][:16], "total_pages": 1,
                  "pages": [{k: v for k, v in page.items() if k not in ("formulas", "ignore_regions")}
                            | {"items": [] if missing else [item]}]}
    extraction_hash = write(directory / "extraction.json", extraction)
    receipt = {"files": {"extraction.json": extraction_hash}}
    receipt_hash = write(directory / "ocr_receipt.json", receipt)
    completion_hash = write(directory / "COMPLETED.json", receipt)
    inventory = {"batches": [], "documents": [{"id": document["document_id"], "source_dir": str(directory),
        "pdf_sha256": document["pdf_sha256"], "total_pages": 1, "ocr_receipt_sha256": receipt_hash,
        "completion_sha256": completion_hash}]}
    monkeypatch.setattr(formula, "collect_predictions", lambda roots: inventory)
    return directory, inventory


@pytest.mark.parametrize("missing", [False, True])
def test_full_scorecard_path_keeps_missing_and_unmeasured_distinct(prepared, tmp_path, monkeypatch, missing):
    directory, _ = publication(prepared, tmp_path, monkeypatch, missing=missing)
    labels = prepared[2]
    output = tmp_path / "scored"
    result = formula.score(labels, sha256_file(labels / "prepared.json"), [directory], output, iou_threshold=.5)
    alignment = json.loads((output / "alignment/alignment.json").read_text())
    assert alignment["annotated_page_counts"] == {"tp": int(not missing), "fp": 0, "fn": int(missing)}
    scorecard = json.loads((output / "scorecard.json").read_text())
    assert scorecard["eligible_for_quality_acceptance"] is False
    assert result["official_evaluation"] == "NOT_RUN"
    assert scorecard["comparisons"]["formula_text_cer:overall"]["candidate"]["status"] == "NOT_EVALUATED"
    assert scorecard["comparisons"]["formula_cdm_mean:overall"]["candidate"]["status"] == "NOT_EVALUATED"


def test_score_rejects_partial_publication_and_changed_labels(prepared, tmp_path, monkeypatch):
    directory, inventory = publication(prepared, tmp_path, monkeypatch)
    labels = prepared[2]
    expected = sha256_file(labels / "prepared.json")
    inventory["documents"] = []
    with pytest.raises(ValueError, match="entire frozen"):
        formula.score(labels, expected, [directory], tmp_path / "partial", iou_threshold=.5)
    (labels / "annotations.json").write_text("{}")
    with pytest.raises(ValueError, match="changed"):
        formula.score(labels, expected, [directory], tmp_path / "changed", iou_threshold=.5)
