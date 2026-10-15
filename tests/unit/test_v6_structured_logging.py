"""JSON logging with run/document/page/stage/worker context (proposal V6
ENV-11, review item R-04)."""
import io
import json
import logging

import pymupdf
import pytest

from src.ocr.application.convert_document import ConvertDocumentUseCase
from src.ocr.runtime import structured_logging as sl


@pytest.fixture
def json_logs(monkeypatch):
    stream = io.StringIO()
    monkeypatch.setenv("OCR_LOG_FORMAT", "text")  # restored at teardown
    sl.configure_logging("json", stream=stream)
    yield stream
    sl.configure_logging("text")


def _records(stream):
    return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]


def test_text_mode_prints_progress_unchanged(monkeypatch, capsys):
    monkeypatch.setenv("OCR_LOG_FORMAT", "text")
    sl.progress("[1/2] completed time=0.10s", stage="complete", seconds=0.1)
    assert capsys.readouterr().out == "[1/2] completed time=0.10s\n"


def test_json_records_carry_bound_and_explicit_context(json_logs, capsys):
    with sl.log_context(run_id="run-1", doc_id="doc"):
        with sl.log_context(page=3):
            sl.progress("\n[3/9] primary=12 lines", stage="ocr", lines=12)
            logging.getLogger("ocr.test").warning("Docling failed")
        sl.progress("[FILE 001/002] other.pdf", stage="batch", doc_id="other", status="CACHED")
    assert capsys.readouterr().out == ""  # nothing mixed into stdout
    first, warning, batch = _records(json_logs)
    assert (first["run_id"], first["doc_id"], first["page"], first["stage"]) == ("run-1", "doc", 3, "ocr")
    assert first["message"] == "[3/9] primary=12 lines" and first["data"] == {"lines": 12}
    assert first["worker"] == "main"
    assert warning["level"] == "WARNING" and warning["page"] == 3 and warning["stage"] is None
    assert batch["doc_id"] == "other" and batch["page"] is None and batch["data"] == {"status": "CACHED"}


def test_context_is_restored_after_the_block():
    with sl.log_context(page=1):
        token = sl.bind_context(stage="tables")
        assert sl.current_context() == {"page": 1, "stage": "tables"}
        sl.reset_context(token)
    assert sl.current_context() == {}


def test_invalid_format_is_rejected():
    with pytest.raises(ValueError):
        sl.configure_logging("xml")


def test_pipeline_progress_is_structured_end_to_end(json_logs, tmp_path):
    pdf = tmp_path / "LOG_doc.pdf"
    with pymupdf.open() as document:
        document.new_page().insert_text((72, 100), "Doanh thu tang truong manh trong nam", fontsize=14)
        document.save(pdf)
    with sl.log_context(run_id="run-7"):
        ConvertDocumentUseCase().execute(str(pdf), "fast", output_dir=str(tmp_path / "out"),
                                         cache_dir=str(tmp_path / "cache"), assets_mode="none")
    records = [r for r in _records(json_logs) if r["logger"] == "ocr.progress"]
    assert records and all(r["run_id"] == "run-7" and r["doc_id"] == "LOG_doc" and r["page"] == 1
                           for r in records)
    assert {"route", "complete"} <= {r["stage"] for r in records}
