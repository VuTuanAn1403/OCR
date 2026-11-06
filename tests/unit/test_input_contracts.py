"""Explicit CPU intake contracts for the TC_IN cases missing dedicated evidence."""
import hashlib
from pathlib import Path
from unittest.mock import Mock

import openpyxl
import pymupdf
import pytest

import ocr_pipeline.batch as batch
import ocr_pipeline.analysis_run as analysis
from ocr_keywords.contract import dictionary_snapshot
from ocr_reporting.workbooks import verify_matrix
from test_v63_pipeline import KEYWORDS, pdf, processor_factory


def test_nfc_document_names_collide_before_second_file_is_hashed(tmp_path, monkeypatch):
    source = tmp_path / "inputs"
    source.mkdir()
    for name in ("bao_cáo.pdf", "bao_ca\u0301o.pdf"):
        pdf(source / name)
    assert len(list(source.iterdir())) == 2
    digest = Mock(wraps=batch.sha256)
    monkeypatch.setattr(batch, "sha256", digest)
    with pytest.raises(ValueError, match="Colliding normalized document ID"):
        batch.input_snapshot(source)
    assert digest.call_count == 1


def test_casefold_collision_is_rejected_on_case_insensitive_hosts(tmp_path, monkeypatch):
    source = tmp_path / "inputs"
    source.mkdir()
    left, right = tmp_path / "left", tmp_path / "right"
    left.mkdir()
    right.mkdir()
    pdf(left / "BAOCAO.pdf")
    pdf(right / "baocao.pdf")
    real_iterdir = Path.iterdir
    # Virtual directory enumeration supplies both names on Windows NTFS.
    monkeypatch.setattr(Path, "iterdir", lambda path: iter([left / "BAOCAO.pdf", right / "baocao.pdf"])
                        if path == source else real_iterdir(path))
    with pytest.raises(ValueError, match="Colliding normalized document ID"):
        batch.input_snapshot(source)


def test_encrypted_and_corrupt_pdfs_keep_failed_blank_rows_without_processing(tmp_path):
    source = tmp_path / "inputs"
    source.mkdir()
    pdf(source / "good.pdf")
    (source / "broken.pdf").write_bytes(b"not a PDF\x00\xff")
    with pymupdf.open() as document:
        document.new_page().insert_text((20, 30), "Private test document")
        document.save(source / "locked.pdf", encryption=pymupdf.PDF_ENCRYPT_AES_256,
                      owner_pw="fixture-owner", user_pw="fixture-password")
    records = {row["id"]: row for row in batch.input_snapshot(source)}
    assert records["locked"]["source_error"] == "Encrypted PDF requires authentication"
    for name in ("locked", "broken"):
        assert records[name]["total_pages"] is None and records[name]["counts"] is None
        assert records[name]["pdf_sha256"] == hashlib.sha256((source / f"{name}.pdf").read_bytes()).hexdigest()
    calls = []
    output = tmp_path / "batch"
    result = batch.process_batch(source, output, {}, KEYWORDS, processor_factory(calls))
    assert calls == ["good"] and result["published_revision"] == 3
    failed = [row for row in result["documents"] if row["id"] != "good"]
    assert all(row["outcome"] == "FAILED_DOCUMENT" and row["counts"] is None for row in failed)
    verify_matrix(result["matrix"], result["batch_id"], 3, result["documents"], dictionary_snapshot(KEYWORDS))
    book = openpyxl.load_workbook(result["matrix"], read_only=True, data_only=True)
    try:
        matrix_rows = list(book["Ma trận từ khóa"].iter_rows(values_only=True))
        assert all(value is None for row in (matrix_rows[1], matrix_rows[3]) for value in row[1:])
    finally:
        book.close()


def test_nested_pdfs_are_excluded_and_recorded_in_frozen_input_manifest(tmp_path):
    source = tmp_path / "inputs"
    (source / "subdir").mkdir(parents=True)
    pdf(source / "TOP.PDF")
    pdf(source / "subdir" / "inner.pdf")
    (source / "notes.txt").write_text("Unrelated input", encoding="utf-8")
    assert [row["id"] for row in batch.input_snapshot(source)] == ["TOP"]
    calls = []
    output = tmp_path / "batch"
    batch.process_batch(source, output, {}, KEYWORDS, processor_factory(calls))
    manifest = analysis.read(output / "batch_input_manifest.json")
    assert calls == ["TOP"]
    assert manifest["excluded_subdirectory_pdfs"] == [str(source / "subdir" / "inner.pdf")]


def test_image_renamed_pdf_is_rejected_without_processing_and_keeps_a_blank_row(tmp_path):
    source = tmp_path / "inputs"
    source.mkdir()
    with pymupdf.open() as document:
        document.new_page().insert_text((20, 30), "Image content")
        (source / "image.pdf").write_bytes(document[0].get_pixmap().tobytes("png"))
    record, = batch.input_snapshot(source)
    assert record["source_error"] == "Input is not a PDF document" and record["total_pages"] is None
    processor = Mock(side_effect=AssertionError("Non-PDF must not reach the processor"))
    result = batch.process_batch(source, tmp_path / "batch", {}, KEYWORDS, processor)
    row, = result["documents"]
    assert row["outcome"] == "FAILED_DOCUMENT" and row["counts"] is None
    processor.assert_not_called()
    verify_matrix(result["matrix"], result["batch_id"], 1, result["documents"], dictionary_snapshot(KEYWORDS))


def test_over_capacity_snapshot_refuses_before_hashing_any_pdf(tmp_path, monkeypatch):
    pdf(tmp_path / "one.pdf")
    # Model the declared file count without allocating a million fixture files.
    monkeypatch.setattr(batch, "len", lambda values: 1_048_575, raising=False)
    digest = Mock(wraps=batch.sha256)
    monkeypatch.setattr(batch, "sha256", digest)
    with pytest.raises(ValueError, match="XLSX row capacity"):
        batch.input_snapshot(tmp_path)
    digest.assert_not_called()


def test_exact_capacity_count_is_allowed(tmp_path, monkeypatch):
    pdf(tmp_path / "one.pdf")
    monkeypatch.setattr(batch, "len", lambda values: 1_048_574, raising=False)
    records = batch.input_snapshot(tmp_path)
    assert [row["id"] for row in records] == ["one"] and records[0]["source_error"] is None


def test_over_capacity_analysis_refuses_before_reading_document_bytes(tmp_path, monkeypatch):
    class OversizedExpectedDocuments(list):
        def __len__(self):
            return 1_048_575
    monkeypatch.setattr(analysis, "_expected_documents", lambda path: OversizedExpectedDocuments([
        ("one", tmp_path / "one", {})]))
    with pytest.raises(ValueError, match="XLSX row capacity"):
        analysis.discover_sources([tmp_path])
