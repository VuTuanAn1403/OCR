"""Current-run timings and measured confidence survive every export."""
import json
import sys
from unittest.mock import Mock

import pymupdf
import pytest

from src.ocr.application import convert_document, process_page
from src.ocr.cli import run_ocr
from src.ocr.domain.models.document import ExtractedDocument
from src.ocr.domain.models.evidence_block import EvidenceBlock
from src.ocr.domain.models.page import ExtractedPage
from src.ocr.domain.models.quality import DocumentQualityReport, PageQualityReport
from src.ocr.domain.models.region import BoundingBox, ContentType, Region
from src.ocr.domain.models.text_block import TextBlock
from src.ocr.domain.routing.page_type import PageType
from src.ocr.infrastructure.export.completion import verify_completed


@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize("confidences,expected", [
    ([(0, None)], None),  # Native text has no OCR measurement.
    ([(1, None)], None),  # Recognized model output can also be unscored.
    ([(1, 0.0)], 0.0),  # A measured zero must remain zero.
    ([(1, None), (1, 0.0), (1, .876543)], .4383),
])
def test_timings_in_exported_json_agree_and_cache_timers_stay_historical(tmp_path, monkeypatch, cached,
                                                                       confidences, expected):
    pdf = tmp_path / "fixture.pdf"
    with pymupdf.open() as source:
        for _ in confidences:
            source.new_page(width=595, height=842)
        source.save(pdf)
    pages = []
    for number, (recognized_lines, confidence) in enumerate(confidences, 1):
        source_name = "primary_ocr" if recognized_lines else "native"
        page_type = PageType.SCANNED_IMAGE if recognized_lines else PageType.NATIVE_TEXT
        block = TextBlock(text="Body text", page=number, source=source_name, bbox=[30, 40, 130, 60],
                          confidence=confidence)
        region = Region(region_id=f"r{number}", bbox=BoundingBox(x0=30, y0=40, x1=130, y1=60),
                        content_type=ContentType.TEXT, status="EXTRACTED")
        pages.append(ExtractedPage(page_num=number, width=595, height=842, page_type=page_type,
                         blocks=[block], regions=[region],
                         evidence_blocks=[EvidenceBlock(block_id=f"b{number}", page=number,
                                                        region_id=region.region_id, bbox=block.bbox,
                                                        text=block.text, source="ocr" if recognized_lines else "native",
                                                        orientation=0)],
                         quality=PageQualityReport(page=number, page_type=page_type.value, from_cache=cached,
                                                   recognized_lines=recognized_lines, ocr_confidence=confidence,
                                                   time_taken_seconds=99.0 if cached else .05)))
    processor = Mock(cache_key="fixture-v6")
    processor.execute.side_effect = pages
    monkeypatch.setattr(convert_document, "ProcessPageUseCase", Mock(return_value=processor))
    result = convert_document.ConvertDocumentUseCase().execute(
        str(pdf), "fast", output_dir=str(tmp_path / "output"), cache_dir=str(tmp_path / "cache"),
        assets_mode="none", benchmark=True, resume=cached)
    out = tmp_path / "output/fixture"
    quality = json.loads((out / "quality.json").read_text())
    manifest = json.loads((out / "manifest.json").read_text())
    benchmark = json.loads((out / "benchmark.json").read_text())
    aggregate = json.loads((out / "result.json").read_text())
    elapsed = result.timing["document_latency_seconds"]
    assert elapsed >= result.timing["export_seconds"] > 0
    assert quality["total_time_seconds"] == manifest["summary"]["total_time_seconds"] == elapsed
    assert benchmark["wall_clock_seconds"] == aggregate["quality"]["total_time_seconds"] == elapsed
    assert manifest["timing"] == result.timing
    assert manifest["cache"]["pages_from_cache"] == (list(range(1, len(pages) + 1)) if cached else [])
    assert quality["page_reports"][0]["time_taken_seconds"] == (99 if cached else .05)
    assert result.quality.mean_ocr_confidence == result.quality.metrics.mean_confidence == expected
    assert quality["mean_ocr_confidence"] == quality["metrics"]["mean_confidence"] == expected
    assert benchmark["mean_confidence"] == aggregate["quality"]["mean_ocr_confidence"] == expected
    assert verify_completed(out)
    processor.close.assert_called_once()


@pytest.mark.parametrize("regional_confidence", ["native_only", None, 0.0, .8])
def test_page_confidence_is_unavailable_until_a_recognizer_measures_it(monkeypatch, regional_confidence):
    monkeypatch.setattr(process_page, "RapidOCREngine", Mock())
    with pymupdf.open() as source:
        source.new_page().insert_text((30, 40), "Native body text with no OCR measurement")
        processor = process_page.ProcessPageUseCase(source, {
            "profile": "fast", "primary_engine": "rapidocr", "docling": {"enabled": False}}, "fixture")
        image_blocks = [] if regional_confidence == "native_only" else [
            TextBlock(text="Recognized image text", page=1, source="image_ocr", bbox=[30, 90, 180, 110],
                      confidence=regional_confidence, quality_score=regional_confidence)]
        monkeypatch.setattr(processor, "_extract_image_regions", Mock(return_value=image_blocks))
        try:
            page = processor.execute(1, 1, Mock(execute=Mock(return_value=(PageType.NATIVE_TEXT, .99))))
        finally:
            processor.close()
    assert page.quality.recognized_lines == len(image_blocks)
    assert page.quality.ocr_confidence == (None if regional_confidence == "native_only" else regional_confidence)


@pytest.mark.parametrize("confidence,display", [(None, "N/A"), (0.0, "0.0000")])
def test_cli_benchmark_renders_unavailable_confidence_and_keeps_measured_zero(tmp_path, monkeypatch, capsys,
                                                                          confidence, display):
    pdf = tmp_path / "fixture.pdf"
    pdf.write_bytes(b"mocked input")
    document = ExtractedDocument(document_id="fixture", file_path=str(pdf), file_hash="fixture", total_pages=1,
                                 quality=DocumentQualityReport(document_id="fixture", total_pages=1,
                                                               mean_ocr_confidence=confidence))
    converter = Mock(config_path=tmp_path / "profiles.yaml")
    converter.resolve_profile.return_value = {"device": "cpu"}
    converter.execute.return_value = document
    monkeypatch.setattr(run_ocr, "ConvertDocumentUseCase", Mock(return_value=converter))
    monkeypatch.setattr(run_ocr, "RunRecorder", Mock(return_value=Mock(run_id="fixture")))
    monkeypatch.setattr(sys, "argv", ["run_ocr", str(pdf), "--benchmark"])
    run_ocr.main()
    row = next(line for line in capsys.readouterr().out.splitlines() if "Mean OCR Confidence" in line)
    assert display in row


def test_out_of_range_api_pages_do_not_fall_back_to_processing_every_page(tmp_path):
    pdf = tmp_path / "one.pdf"
    with pymupdf.open() as source:
        source.new_page()
        source.save(pdf)
    with pytest.raises(ValueError, match="outside the document"):
        convert_document.ConvertDocumentUseCase().execute(str(pdf), "fast", pages=[2])


def test_cpu_only_rapidocr_profile_cannot_claim_gpu_execution(monkeypatch):
    monkeypatch.setattr(convert_document, "resolve_device", lambda _: "cuda")
    with pytest.raises(ValueError, match="RapidOCR primary backend currently runs on CPU"):
        convert_document.ConvertDocumentUseCase().resolve_profile("fast", "cuda")


def test_model_initialization_failure_closes_source_pdf(tmp_path, monkeypatch):
    pdf = tmp_path / "one.pdf"
    with pymupdf.open() as source:
        source.new_page()
        source.save(pdf)
    opened = pymupdf.open(pdf)
    monkeypatch.setattr(convert_document.pymupdf, "open", lambda _: opened)
    monkeypatch.setattr(convert_document, "ProcessPageUseCase", Mock(side_effect=RuntimeError("model unavailable")))
    with pytest.raises(RuntimeError, match="model unavailable"):
        convert_document.ConvertDocumentUseCase().execute(str(pdf), "fast", cache_dir=str(tmp_path / "cache"))
    assert opened.is_closed
