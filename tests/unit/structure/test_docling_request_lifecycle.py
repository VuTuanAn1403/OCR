"""Keep transient page PDFs bounded without deleting a live worker's input."""
import json
from pathlib import Path
import queue
from types import SimpleNamespace
from unittest.mock import Mock

import pymupdf
import pytest

from ocr_structure import docling_client


class NativeSaveError(Exception):
    """MuPDF native errors need not derive from RuntimeError or OSError."""


def client(tmp_path, monkeypatch, *, mode="success", reap_error=False):
    extractor = docling_client.DoclingStructureExtractor({"enabled": True, "formulas": False})
    extractor._job_dir = tmp_path / "job"
    extractor._job_dir.mkdir()
    log = extractor._job_dir / "worker.log"
    log.write_text("Retained worker diagnostics", encoding="utf-8")
    events, requests = [], []

    def write(payload):
        request = json.loads(payload)
        assert Path(request["pdf"]).is_file()
        requests.append(request)
        if mode == "transport":
            raise OSError("Broken pipe")

    def receive(**kwargs):
        request = requests[-1]
        with pymupdf.open(request["pdf"]) as pdf:
            assert len(pdf) == 1
            assert "020 evidence" in pdf[0].get_text()
        assert len(list(extractor._job_dir.glob("page-*.pdf"))) == 1
        events.append("response")
        if mode == "timeout":
            raise queue.Empty
        if mode == "interrupt":
            raise KeyboardInterrupt
        response = {"id": request["id"], "status": "success", "tables": [], "formulas": []}
        if mode == "wrong_id":
            response["id"] = "another request"
        elif mode == "invalid_mapping":
            response["tables"] = [{"cells": [None]}]
        return response

    def close():
        assert list(extractor._job_dir.glob("page-*.pdf"))
        events.append("closed")
        if reap_error:
            raise RuntimeError("Worker exit could not be verified")

    extractor._process = SimpleNamespace(stdin=SimpleNamespace(write=write, flush=lambda: None))
    extractor._responses = SimpleNamespace(get=receive)
    monkeypatch.setattr(extractor, "close", Mock(side_effect=close))
    original_unlink = Path.unlink

    def unlink(path, **kwargs):
        if path.parent == extractor._job_dir and path.suffix == ".pdf":
            assert "response" in events or "closed" in events
            events.append("removed")
        return original_unlink(path, **kwargs)

    monkeypatch.setattr(Path, "unlink", unlink)
    if mode == "native_save":
        def failed_save(pdf, path, *args, **kwargs):
            Path(path).write_bytes(b"partial page PDF")
            raise NativeSaveError("No space left on device")
        monkeypatch.setattr(pymupdf.Document, "save", failed_save)
    return extractor, events, log


def source():
    pdf = pymupdf.open()
    pdf.new_page().insert_text((20, 40), "020 evidence")
    return pdf


def test_successful_requests_remove_only_completed_page_pdf(tmp_path, monkeypatch):
    extractor, events, log = client(tmp_path, monkeypatch)
    with source() as pdf:
        for number in range(1, 5):
            result = extractor.extract_page(pdf[0], number)
            assert result["tables"] == result["formulas"] == []
            assert result["metadata"]["log_path"] == str(log)
            assert not list(log.parent.glob("page-*.pdf"))
    assert events == ["response", "removed"] * 4
    assert log.read_text(encoding="utf-8") == "Retained worker diagnostics"
    extractor.close.assert_not_called()


@pytest.mark.parametrize("mode,error", [
    ("timeout", docling_client.DoclingStructureError),
    ("transport", docling_client.DoclingStructureError),
    ("wrong_id", docling_client.DoclingStructureError),
    ("invalid_mapping", docling_client.DoclingStructureError),
    ("native_save", NativeSaveError),
    ("interrupt", KeyboardInterrupt),
])
def test_failed_requests_reap_before_removing_input(tmp_path, monkeypatch, mode, error):
    extractor, events, log = client(tmp_path, monkeypatch, mode=mode)
    with source() as pdf, pytest.raises(error):
        extractor.extract_page(pdf[0], 1)
    assert events[-2:] == ["closed", "removed"]
    assert not list(log.parent.glob("page-*.pdf"))
    assert log.is_file()
    extractor.close.assert_called_once()


def test_unverified_exit_keeps_worker_input(tmp_path, monkeypatch):
    extractor, events, log = client(tmp_path, monkeypatch, mode="timeout", reap_error=True)
    with source() as pdf, pytest.raises(RuntimeError, match="exit could not be verified"):
        extractor.extract_page(pdf[0], 1)
    assert events == ["response", "closed"]
    assert len(list(log.parent.glob("page-*.pdf"))) == 1


@pytest.mark.parametrize("mode", ["success", "native_save"])
def test_cleanup_failure_keeps_original_error_and_closes_worker(tmp_path, monkeypatch, caplog, mode):
    extractor, events, log = client(tmp_path, monkeypatch, mode=mode)

    def denied(path, **kwargs):
        raise PermissionError("File is locked")

    monkeypatch.setattr(Path, "unlink", denied)
    expected = PermissionError if mode == "success" else NativeSaveError
    with source() as pdf, pytest.raises(expected):
        extractor.extract_page(pdf[0], 1)
    extractor.close.assert_called_once()
    assert len(list(log.parent.glob("page-*.pdf"))) == 1
    if mode == "native_save":
        assert "Cannot remove transient Docling page PDF" in caplog.text


def test_caller_exception_does_not_hide_a_new_cleanup_failure(tmp_path, monkeypatch):
    extractor, events, log = client(tmp_path, monkeypatch)

    def denied(path, **kwargs):
        raise PermissionError("File is locked")

    monkeypatch.setattr(Path, "unlink", denied)
    try:
        raise ValueError("Previously handled by the caller")
    except ValueError:
        with source() as pdf, pytest.raises(PermissionError, match="File is locked"):
            extractor.extract_page(pdf[0], 1)
    extractor.close.assert_called_once()
