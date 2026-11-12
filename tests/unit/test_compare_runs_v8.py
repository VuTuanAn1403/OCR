"""compare_source_dispositions / compare_run_invariants: paired GT-free run comparison (V8-080, V8-140)."""
import json

from scripts import compare_run_invariants, compare_source_dispositions


def _doc(root, name, dispositions, items, counts=None):
    folder = root / name
    (folder / "pages").mkdir(parents=True)
    (folder / "COMPLETED.json").write_text("{}", encoding="utf-8")
    evidence = [{"source_id": sid, "text_raw": sid, "bbox": [0, i * 10, 50, i * 10 + 8]}
                for i, sid in enumerate(sorted(dispositions))]
    page = {"page": 1, "text_evidence": {"items": evidence}, "items": items,
            "source_dispositions": {sid: {"status": s} for sid, s in dispositions.items()}}
    (folder / "extraction.json").write_text(json.dumps({"pages": [page]}), encoding="utf-8")
    (folder / "keyword_counts.json").write_text(json.dumps({"canonical_counts": counts or {"xanh": 1}}), encoding="utf-8")
    (folder / "result.md").write_text("x", encoding="utf-8")


def test_transitions_are_counted_and_an_unowned_source_is_listed(tmp_path):
    _doc(tmp_path / "a", "D", {"s1": "VISIBLE_OR_FURNITURE", "s2": "KEPT_FOR_REVIEW"},
         [{"kind": "b", "source_id": "s1"}, {"kind": "b", "source_id": "s2"}])
    _doc(tmp_path / "b", "D", {"s1": "VISIBLE_OR_FURNITURE", "s2": "REPLACED_BY_TABLE"},
         [{"kind": "b", "source_id": "s1"}, {"kind": "t", "derived_from_source_ids": ["s2"]}])
    report = compare_source_dispositions.compare(tmp_path / "a", tmp_path / "b")
    assert report["changed"] == {"KEPT_FOR_REVIEW->REPLACED_BY_TABLE": 1} and report["unchanged"] == 1
    assert report["sources_neither_visible_nor_owned"] == [] and report["phase_a_differs"] == []
    _doc(tmp_path / "c", "D", {"s1": "VISIBLE_OR_FURNITURE", "s2": "REPLACED_BY_TABLE"},
         [{"kind": "b", "source_id": "s1"}])
    lost = compare_source_dispositions.compare(tmp_path / "a", tmp_path / "c")
    assert [row["source_id"] for row in lost["sources_neither_visible_nor_owned"]] == ["s2"]


def test_keyword_changes_are_reported_per_keyword(tmp_path):
    _doc(tmp_path / "a", "D", {"s1": "VISIBLE_OR_FURNITURE"}, [], {"xanh": 1, "ESG": 2})
    _doc(tmp_path / "b", "D", {"s1": "VISIBLE_OR_FURNITURE"}, [], {"xanh": 1, "ESG": 3})
    report = compare_run_invariants.compare(tmp_path / "a", tmp_path / "b")
    document, = report["documents"]
    assert document["keyword_changes"] == {"ESG": {"baseline": 2, "candidate": 3}}
    assert report["keyword_keys_changed"] == 1 and document["result_md_identical"] is True
