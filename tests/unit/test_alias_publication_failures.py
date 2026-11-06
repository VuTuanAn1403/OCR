"""Invalid review identity must never publish numeric rows or alter extraction."""
import pytest

from test_analysis_run import extraction, no_ocr, alias_input, tree_hashes
from ocr_keywords.alias_map import save_alias_decisions
from ocr_pipeline.analysis_run import run_analysis


@pytest.mark.parametrize("field", ["pdf_sha256", "dictionary_snapshot_hash", "result_md_sha256"])
def test_wrong_review_identity_publishes_a_blank_failure_row(extraction, tmp_path, no_ocr, field):
    source, _ = extraction
    before = tree_hashes(source)
    keys, item = alias_input(source, tmp_path)
    bad = item.model_copy(update={field: "f" * 64})
    bundle = tmp_path / "bad-identity.json"
    save_alias_decisions(bundle, [bad])
    output = tmp_path / "analysis"
    result = run_analysis([source], output, keys, keyword_set_version="custom-alias", alias_decisions=bundle)
    failed = next(row for row in result["documents"] if row["id"] == "a")
    assert failed["outcome"] == "FAILED_DOCUMENT"
    assert failed["counts"] is None
    assert "identity mismatch" in failed["error"]
    assert not (output / "a/COMPLETED.json").exists()
    import openpyxl
    book = openpyxl.load_workbook(result["matrix"], read_only=True, data_only=True)
    try:
        assert book["Ma trận từ khóa"].cell(row=2, column=2).value is None
    finally:
        book.close()
    assert tree_hashes(source) == before
