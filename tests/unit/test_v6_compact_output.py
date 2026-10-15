"""Compact export preserves complete pages/contracts and rejects broken indexes."""
import json

import pymupdf
import pytest

from src.ocr.application.convert_document import ConvertDocumentUseCase
from src.ocr.cli.batch_runner import BatchOCRRunner
from src.ocr.infrastructure.export.artifact_validator import validate_document_artifacts
from src.ocr.infrastructure.export.completion import verify_completed
from src.ocr.infrastructure.export.output_contract import V6_ARTIFACTS
from src.ocr.infrastructure.export.result_reader import load_document_json
from src.ocr.runtime.document_pool import load_exported_document


@pytest.fixture
def outputs(tmp_path):
    pdf = tmp_path / "COMPACT_report.pdf"
    with pymupdf.open() as doc:
        for number in range(2):
            page = doc.new_page()
            page.insert_text((40, 60), f"Annual report page {number + 1}", fontsize=18)
            for row in range(20):
                page.insert_text((40, 100 + row * 20), "Revenue 1.234.567 VND; profit (25.000); growth 12,5%.")
        doc.save(pdf)
    converter = ConvertDocumentUseCase()
    for mode in ("legacy", "compact"):
        converter.execute(str(pdf), "fast", output_dir=str(tmp_path / mode),
                          cache_dir=str(tmp_path / "cache"), resume=mode == "compact",
                          benchmark=True, assets_mode="none", output_mode=mode)
    return pdf, tmp_path / "legacy" / pdf.stem, tmp_path / "compact" / pdf.stem


def test_compact_has_smaller_index_and_identical_source_contracts(outputs):
    _, legacy, compact = outputs
    index = json.loads((compact / "result.json").read_text())
    assert index["schema_version"] == "result-index-v1" and "pages" not in index
    assert index["page_refs"] == [{"page_num": n, "path": f"pages/page-{n:04d}.json"} for n in (1, 2)]
    assert (compact / "result.json").stat().st_size < (legacy / "result.json").stat().st_size / 2
    for name in (*V6_ARTIFACTS, "result.md"):
        assert (compact / name).read_bytes() == (legacy / name).read_bytes()
    expanded = load_document_json(compact)
    assert len(expanded["pages"]) == 2
    assert expanded["pages"][0]["blocks"] == load_document_json(legacy)["pages"][0]["blocks"]
    assert verify_completed(compact) and validate_document_artifacts(compact)["status"] != "FAIL"
    loaded = load_exported_document(compact)
    assert loaded.selected_pages == [1, 2] and loaded.pages[0].blocks
    assert "1.234.567" in loaded.pages[0].blocks[1].text


def test_batch_resume_requires_the_same_output_mode(outputs, tmp_path):
    pdf, _, compact = outputs
    runner = BatchOCRRunner(input_dir=str(tmp_path), output_dir=str(compact.parent), profile="fast",
                            assets_mode="none", output_mode="compact", excel_path=None)
    assert runner.is_cached(pdf.stem, 2, pdf)
    runner.output_mode = "legacy"
    assert runner.is_cached(pdf.stem, 2, pdf) is None


@pytest.mark.parametrize("damage", ["missing_page", "wrong_page", "traversal", "duplicate", "unknown_schema",
                                   "missing_index", "wrong_mode", "wrong_document"])
def test_bad_compact_index_is_a_validation_failure(outputs, damage):
    _, _, directory = outputs
    path = directory / "result.json"
    index = json.loads(path.read_text())
    if damage == "missing_page":
        (directory / "pages/page-0001.json").unlink()
    elif damage == "wrong_page":
        page_path = directory / "pages/page-0001.json"
        page = json.loads(page_path.read_text())
        page["page_num"] = 2
        page_path.write_text(json.dumps(page))
    elif damage == "traversal":
        index["page_refs"][0]["path"] = "../../other.json"
    elif damage == "duplicate":
        index["page_refs"][1] = index["page_refs"][0]
    elif damage == "unknown_schema":
        index["schema_version"] = "result-index-v99"
    elif damage == "missing_index":
        path.unlink()
    elif damage == "wrong_mode":
        manifest_path = directory / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["output_mode"] = "legacy"
        manifest_path.write_text(json.dumps(manifest))
    else:
        index["document_id"] = "another_document"
    if path.exists():
        path.write_text(json.dumps(index))
    validation = validate_document_artifacts(directory)
    assert validation["status"] == "FAIL" and validation["errors"]
    assert not verify_completed(directory)


def test_unsupported_output_mode_fails_before_opening_the_pdf(tmp_path):
    with pytest.raises(ValueError, match="output_mode"):
        ConvertDocumentUseCase().execute("missing.pdf", output_mode="unknown")
