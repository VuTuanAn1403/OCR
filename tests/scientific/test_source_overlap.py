"""Source overlap evidence must distinguish observed matches from split decisions."""
import hashlib
import json

import pymupdf
import pytest

from benchmark.scientific_evaluation import source_overlap
from src.ocr.collect.catalog import collect_sources, file_sha256


LINES = [
    "Annual balance report for the consolidated company cash and total revenue",
    "Independent audit covers payable provisions and short term assets on file",
    "The report explains amounts recognized across two separate accounting periods",
]


@pytest.fixture
def corpus(tmp_path):
    root = tmp_path / "pdf"
    root.mkdir()
    for name, offset in [("alpha", 0), ("beta", 1), ("gamma", 0)]:
        with pymupdf.open() as doc:
            doc.new_page()
            page = doc.new_page()
            for i, line in enumerate(LINES):
                page.insert_text((35 + offset, 40 + i * 15), line)
            doc.set_metadata({"title": name})
            doc.save(root / f"{name}.pdf")
    (root / "delta.pdf").write_bytes((root / "alpha.pdf").read_bytes())
    sources = tmp_path / "sources.csv"
    rows = collect_sources(root, sources, {"alpha.pdf": {"company_name": "Công ty A"},
                                          "beta.pdf": {"company_name": "công TY A"}})
    return root, sources, rows


def test_pdf_worklist_covers_all_pairs_preserves_duplicate_and_excludes_blank_pages(corpus):
    root, sources, _ = corpus
    report = source_overlap.review_worklist(sources, root, [])
    pairs = {tuple(row["documents"]): row for row in report["pairs"]}
    assert report["status"] == "DRAFT_FOR_CURATOR" and report["split_acceptance"] == "NOT_EVALUATED"
    assert report["sources_sha256"] == file_sha256(sources) and len(pairs) == 6
    assert all(row["pages"] == 2 and row["visual_pages"] == row["text_pages"] == 1 for row in report["documents"])
    assert all(row["template_relation"] is None and row["near_duplicate_relation"] is None for row in pairs.values())
    assert pairs["alpha", "delta"]["identical_pdf_bytes"]
    assert pairs["alpha", "gamma"]["identical_pdf_bytes"] is False
    matches = pairs["alpha", "gamma"]["exact_thumbnail_matches"]
    assert [match["pages"] for match in matches] == [[2, 2]]
    assert pairs["alpha", "beta"]["same_issuer_name"] is True
    assert pairs["alpha", "gamma"]["same_issuer_name"] is None
    assert pairs["alpha", "beta"]["text_candidates"][0]["jaccard"] == 1
    assert pairs["alpha", "beta"]["layout_candidates"][0]["pages"] == [2, 2]


def test_changed_source_bytes_are_rejected(corpus):
    root, sources, _ = corpus
    (root / "beta.pdf").write_bytes((root / "gamma.pdf").read_bytes())
    with pytest.raises(ValueError, match="Source PDF path or hash differs for beta"):
        source_overlap.review_worklist(sources, root, [])


def test_render_warning_excludes_visual_match_but_retains_recorded_text(corpus, monkeypatch):
    root, _, _ = corpus
    monkeypatch.setattr(pymupdf.TOOLS, "mupdf_warnings", lambda: "invalid content stream")
    with pymupdf.open(root / "alpha.pdf") as document:
        recorded = source_overlap._signature(document[1], LINES)
        native = source_overlap._signature(document[1], None)
    assert recorded.render_warnings == 1 and recorded.layout is recorded.raster_sha256 is None
    assert len(recorded.shingles) >= source_overlap.MIN_TEXT_SHINGLES
    assert not native.shingles and native.native_text_warnings == 1


def test_recorded_text_checks_receipt_and_all_physical_pages(tmp_path, corpus):
    _, _, rows = corpus
    row = next(row for row in rows if row["document_id"] == "alpha")
    extraction = tmp_path / "extraction.json"
    extraction.write_text(json.dumps({"doc_id": "alpha", "doc_sha16": row["sha256"][:16], "pages": [
        {"page": 1}, {"page": 2, "text_evidence": {"items": [{"text_raw": LINES[0]}]}},
    ]}), encoding="utf-8")
    receipt = tmp_path / "ocr_receipt.json"
    receipt.write_text(json.dumps({"files": {"extraction.json": file_sha256(extraction)}}), encoding="utf-8")
    publication = {"pdf_sha256": row["sha256"], "total_pages": 2, "source_dir": str(tmp_path),
                   "ocr_receipt_sha256": file_sha256(receipt)}
    lines, checksum = source_overlap._recorded_lines(publication, row)
    assert lines == {1: [], 2: [LINES[0]]} and checksum == hashlib.sha256(extraction.read_bytes()).hexdigest()
    extraction.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="Canonical extraction changed"):
        source_overlap._recorded_lines(publication, row)
