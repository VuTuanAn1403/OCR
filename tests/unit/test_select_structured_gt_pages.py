"""select_structured_gt_pages: deterministic hypothesis strata for GT labelling."""
import json

from scripts import select_structured_gt_pages as select


def _output(tmp_path):
    pages = [{"page": n, "coordinate_space": "pdf_points_top_left", "transforms": [], "items": []} for n in range(1, 8)]
    pages[1]["items"] = [{"kind": "t", "source": "heuristic"}]
    pages[2]["items"] = [{"kind": "t", "source": "docling_tableformer"}]
    pages[3]["coordinate_space"] = "pdf_points_top_left_rotated"
    folder = tmp_path / "out" / "DOC"
    folder.mkdir(parents=True)
    (folder / "extraction.json").write_text(json.dumps({"pages": pages}), encoding="utf-8")
    return tmp_path / "out"


def test_each_stratum_takes_a_distinct_exportable_page(tmp_path):
    ro = {"documents": [{"document": "DOC", "pages": [{"page": 1, "agreement_with_product": .5},
                                                      {"page": 4, "agreement_with_product": .1},
                                                      {"page": 5, "agreement_with_product": .95}]}]}
    det = {"documents": [{"document": "DOC", "pages_detail": [
        {"page": 1, "status": "PAIRED", "agreement": {"counts": {"fp": 9, "fn": 0}}},
        {"page": 5, "status": "PAIRED", "agreement": {"counts": {"fp": 2, "fn": 1}}}]}]}
    report = select.select(_output(tmp_path), ro, det, "seed", rotations={"DOC": {6: 90}})
    document, = report["documents"]
    by_stratum = {row["stratum"]: row["page"] for row in document["pages"]}
    # page 4 has the lowest agreement but a rotated frame; page 6 is a rotated PDF page
    assert by_stratum["reading_order"] == 1 and by_stratum["detection"] == 5
    assert by_stratum["table_heuristic"] == 2 and by_stratum["table_model"] == 3
    assert by_stratum["random"] == 7  # the only exportable page left
    assert document["not_exportable"] == 2 and len({row["page"] for row in document["pages"]}) == len(document["pages"])
    assert report == select.select(_output(tmp_path / "again"), ro, det, "seed", rotations={"DOC": {6: 90}}) | {
        "output": report["output"]}
