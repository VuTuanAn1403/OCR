import copy
import json

import pymupdf
import pytest

from src.ocr.collect.catalog import V1_FIELDS, collect_sources, lock_company_splits, prepare_gt_drafts, read_sources


def inventory(tmp_path):
    root = tmp_path / "pdf"
    root.mkdir()
    metadata = {}
    for company in ("A", "B", "C"):
        path = root / f"{company}.pdf"
        with pymupdf.open() as doc:
            for number in range(3):
                page = doc.new_page()
                page.insert_text((40, 40), f"Company {company} financial annual report page {number}")
            doc.save(path)
        metadata[path.name] = {"company_id": company, "year": 2025}
    csv = tmp_path / "sources.csv"
    collect_sources(root, csv, metadata)
    return root, csv


def test_company_splits_prevent_leakage_and_cannot_be_rewritten(tmp_path):
    _, sources = inventory(tmp_path)
    assignments = {"train": ["A"], "dev": ["B"], "test": ["C"]}
    output = tmp_path / "splits.json"
    original = lock_company_splits(sources, assignments, output)
    assert lock_company_splits(sources, assignments, output) == original
    changed = {"train": ["B"], "dev": ["A"], "test": ["C"]}
    with pytest.raises(ValueError, match="immutable"):
        lock_company_splits(sources, changed, output)
    with pytest.raises(ValueError, match="leakage"):
        lock_company_splits(sources, {"train": ["A"], "dev": ["A"], "test": ["C"]}, tmp_path / "bad.json")


def test_unknown_metadata_never_becomes_verified_company_or_gt(tmp_path):
    root, _ = inventory(tmp_path)
    csv = tmp_path / "unknown.csv"
    rows = collect_sources(root, csv)
    assert all(row["company_id"] == "unknown" for row in rows)
    with pytest.raises(ValueError, match="verified company_id"):
        lock_company_splits(csv, {"train": ["A"], "dev": ["B"], "test": ["C"]}, tmp_path / "split.json")


def test_duplicate_content_and_editions_are_reported_not_hidden(tmp_path):
    root, _ = inventory(tmp_path)
    (root / "A_copy.pdf").write_bytes((root / "A.pdf").read_bytes())
    with pymupdf.open() as doc:
        doc.new_page().insert_text((40, 40), "Company A amended annual report")
        doc.save(root / "A_amended.pdf")
    metadata = {name: {"company_id": name[0], "year": 2025} for name in ("A.pdf", "B.pdf", "C.pdf",
                                                                           "A_copy.pdf", "A_amended.pdf")}
    csv = tmp_path / "dup.csv"
    rows = {row["document_id"]: row for row in collect_sources(root, csv, metadata)}
    assert rows["A_copy"]["status"] == "DUPLICATE" and "A" in rows["A_copy"]["error"]
    catalog = json.loads(csv.with_suffix(".catalog.json").read_text(encoding="utf-8"))
    assert catalog["schema_version"] == "sources-v2" and catalog["duplicate_documents"] == ["A_copy"]
    assert catalog["revision_candidates"] == {"a|2025": ["A", "A_amended"]}
    splits = tmp_path / "splits.json"
    lock_company_splits(csv, {"train": ["A"], "dev": ["B"], "test": ["C"]}, splits)
    drafts = prepare_gt_drafts(csv, splits, tmp_path / "drafts", pages=20)
    assert "A_copy" not in {record["document_id"] for record in drafts["records"]}


def test_c20_fields_are_supplied_and_v1_inventories_still_read(tmp_path):
    root, _ = inventory(tmp_path)
    csv = tmp_path / "v2.csv"
    metadata = {"A.pdf": {"company_id": "A", "company_name": "Công ty A", "exchange": "HOSE", "language": "vi"}}
    row = collect_sources(root, csv, metadata)[0]
    assert (row["company_name"], row["exchange"], row["language"]) == ("Công ty A", "HOSE", "vi")
    assert collect_sources(root, tmp_path / "plain.csv")[0]["language"] == "unknown"  # never guessed

    legacy = tmp_path / "v1.csv"
    lines = csv.read_text(encoding="utf-8").splitlines()
    header = lines[0].split(",")
    keep = [header.index(field) for field in V1_FIELDS]
    legacy.write_text("\n".join(",".join(line.split(",")[i] for i in keep) for line in lines) + "\n",
                      encoding="utf-8")
    assert all(row["company_name"] in ("unknown",) for row in read_sources(legacy))


def test_annotation_drafts_are_pending_stratified_and_exclude_test(tmp_path):
    root, sources = inventory(tmp_path)
    splits = tmp_path / "splits.json"
    lock_company_splits(sources, {"train": ["A"], "dev": ["B"], "test": ["C"]}, splits)
    output = tmp_path / "drafts"
    result = prepare_gt_drafts(sources, splits, output, pages=4)
    assert result["annotation_status"] == "UNANNOTATED"
    assert {r["company_id"] for r in result["records"]} == {"a", "b"}
    assert all(r["split"] != "test" for r in result["records"])
    assert not list(output.rglob("*.txt")) and len(list(output.rglob("*.txt.pending"))) == 4
    assert not result["eligible_for_acceptance"]
    with pytest.raises(ValueError, match="overwrite manual annotation"):
        prepare_gt_drafts(sources, splits, output, pages=4)
    with (root / "A.pdf").open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(ValueError, match="Source PDF changed"):
        prepare_gt_drafts(sources, splits, tmp_path / "changed", pages=4)
