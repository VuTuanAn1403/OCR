"""Counterexamples for KP-01..04: unknown scores and incomplete contracts."""
import copy
import json

import pytest

from src.ocr.domain.models.evidence_block import EvidenceBlock
from src.ocr.domain.models.region import Region, BoundingBox
from src.ocr.domain.models.table import TableCell, TableStructure
from src.ocr.domain.models.text_block import TextBlock
from src.ocr.infrastructure.export.artifact_validator import validate_document_artifacts
from src.ocr.infrastructure.export.completion import mark_completed
from src.ocr.infrastructure.export.contract_schema import validate_extraction
from tests.unit.test_v6_honest_outputs import _doc, _page_with_regions
from src.ocr.application.export_document import ExportDocumentUseCase


@pytest.mark.parametrize("factory", [
    lambda **kw: TextBlock(text="Body", page=1, **kw),
    lambda **kw: EvidenceBlock(page=1, **kw),
    lambda **kw: Region(region_id="r", bbox=BoundingBox(x0=0, y0=0, x1=1, y1=1), **kw),
    lambda **kw: TableCell(row_idx=0, col_idx=0, **kw),
    lambda **kw: TableStructure(table_id="t", page=1, **kw),
])
def test_unmeasured_defaults_and_real_zero(factory):
    unknown = factory()
    assert unknown.confidence is None
    assert unknown.model_dump()["confidence_source"] == "unavailable"
    known = factory(confidence=0.0, confidence_source="recognizer")
    assert known.confidence == 0.0 and known.model_dump()["confidence_source"] == "recognizer"
    # Historical cache serialized an explicit null source with known scores.
    assert factory(confidence=.8, confidence_source=None).confidence_source == "unspecified"
    known.confidence = None
    assert known.model_dump()["confidence_source"] == "unavailable"
    if hasattr(unknown, "quality_score"):
        assert unknown.quality_score is None


def export_fixture(tmp_path):
    block = TextBlock(text="Nguồn số liệu -1.234 triệu đồng", page=1, bbox=[10, 30, 300, 50],
                      confidence=.9, confidence_source="native_text_score", quality_score=.9)
    return ExportDocumentUseCase.execute(_doc([_page_with_regions(blocks=[block])]), tmp_path, assets_mode="none")


@pytest.mark.parametrize("name", ["extraction.json", "structure.json", "document.json", "document.md"])
def test_each_required_artifact_is_enforced(tmp_path, name):
    out = export_fixture(tmp_path)
    (out / name).unlink()
    report = validate_document_artifacts(out)
    assert report["status"] == "FAIL"
    assert any(name in error and "missing" in error for error in report["errors"])
    with pytest.raises(ValueError, match="invalid artifacts"):
        mark_completed(out, "PASS")


def test_removing_all_new_artifacts_is_not_misclassified_as_legacy(tmp_path):
    out = export_fixture(tmp_path)
    for name in ("extraction.json", "structure.json", "document.json", "document.md"):
        (out / name).unlink()
    assert validate_document_artifacts(out)["status"] == "FAIL"


def test_markdown_content_removal_and_broken_structure_are_errors(tmp_path):
    out = export_fixture(tmp_path)
    (out / "document.md").write_text("", encoding="utf-8")
    report = validate_document_artifacts(out)
    assert any("Markdown contract" in error for error in report["errors"])
    assert any("missing content" in error for error in report["errors"])
    (out / "structure.json").write_text("{}", encoding="utf-8")
    assert any("structure.json" in error for error in validate_document_artifacts(out)["errors"])


def test_extraction_only_checks_duplicate_ids_and_ownership(tmp_path):
    out = export_fixture(tmp_path)
    payload = json.loads((out / "extraction.json").read_text(encoding="utf-8"))
    payload["pages"][0]["items"].append(copy.deepcopy(payload["pages"][0]["items"][0]))
    assert any("duplicate element" in error for error in validate_extraction(payload))
    payload["pages"][0]["items"][0]["id"] = "other:p0001:b0001"
    assert any("document/page/kind" in error for error in validate_extraction(payload))


def test_malformed_legacy_manifest_returns_failure(tmp_path):
    (tmp_path / "manifest.json").write_text("[]", encoding="utf-8")
    assert validate_document_artifacts(tmp_path)["status"] == "FAIL"
