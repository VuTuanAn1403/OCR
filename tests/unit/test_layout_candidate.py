"""V8-070 layout candidate: class map and GT/agreement scoring."""
import json

from benchmark.scientific_evaluation.coco_layout import GT_CLASSES
from scripts import compare_layout_candidate as compare
from scripts.run_layout_candidate import CLASS_MAP, LABELS


def test_every_candidate_label_maps_to_a_gt_class_or_is_left_unscored():
    assert set(CLASS_MAP) == set(LABELS)
    assert {value for value in CLASS_MAP.values() if value} <= set(GT_CLASSES)


def _output(tmp_path):
    items = [{"id": "b1", "kind": "b", "block_type": "paragraph", "bbox": [10, 10, 100, 30]},
             {"id": "t1", "kind": "t", "bbox": [10, 50, 100, 90]}]
    folder = tmp_path / "out" / "DOC"
    folder.mkdir(parents=True)
    (folder / "extraction.json").write_text(json.dumps({"pages": [{"page": 1, "items": items}]}), encoding="utf-8")
    return tmp_path / "out"


def _row(rid, cls, box):
    return {"status": "PREDICTED", "document_id": "DOC", "physical_page": 1, "region_id": rid,
            "region_class": cls, "bbox": box, "confidence": .9}


def test_gt_pages_are_scored_for_both_systems_and_paired(tmp_path):
    output = _output(tmp_path)
    gt = {"document_id": "DOC", "pages": [{"page": 1, "layout": [
        {"id": "g1", "category": "Text", "bbox": [10, 10, 100, 30]},
        {"id": "g2", "category": "Picture", "bbox": [10, 100, 100, 150]}]}]}
    gt_path = tmp_path / "DOC.structure.json"
    gt_path.write_text(json.dumps(gt), encoding="utf-8")
    rows = [_row("c1", "Text", [10, 10, 100, 30]), _row("c2", "Picture", [10, 100, 100, 150])]
    report = compare.compare(rows, output, [gt_path])
    assert report["gt"]["candidate"]["tp"] == 2 and report["gt"]["production"]["tp"] == 1
    assert report["gt_paired_page_effects"] == {"fixed": 1, "harmed": 0, "same": 0}


def test_without_gt_only_agreement_is_reported(tmp_path):
    report = compare.compare([_row("c1", "Table", [10, 50, 100, 90])], _output(tmp_path))
    assert report["decision_options"] == ["INCONCLUSIVE"] and "gt" not in report
    assert report["agreement_with_production"]["tp"] == 1
