"""Local Vietnamese OCR retains quality settings while bounding inference work."""
from unittest.mock import Mock

import numpy as np
import pytest

from src.ocr.application.convert_document import ConvertDocumentUseCase
from src.ocr.application.process_page import ProcessPageUseCase
from src.ocr.infrastructure.ocr.vietnamese_seq2seq_engine import VietnameseSeq2SeqEngine


def test_local_uses_vietocr_and_preserves_balanced_review_settings_without_docling(monkeypatch):
    from src.ocr.runtime import device
    monkeypatch.setattr(device, "cuda_available", lambda: False)
    converter = ConvertDocumentUseCase()
    local = converter.resolve_profile("local")
    balanced = converter.resolve_profile("balanced", "cpu")
    assert local["primary_engine"] == "vietocr" and local["device"] == "cpu"
    assert (local["num_threads"], local["batch_size"]) == (2, 4)
    assert not local["docling"]["enabled"]
    for key in ("native_first", "render_dpi", "layout", "fallback_only_on_review",
                "max_fallback_regions_per_page", "max_fallback_region_ratio", "fallback_upscale_dpi",
                "min_confidence", "numeric_retry_threshold", "native_quality", "orientation_fallback_enabled"):
        assert local[key] == balanced[key], key
    assert balanced["docling"]["enabled"] and balanced["docling"]["formulas"] and balanced["docling"]["tables"]
    tuned = ConvertDocumentUseCase(thread_budget=3, batch_size=2).resolve_profile("local")
    assert (tuned["num_threads"], tuned["batch_size"]) == (3, 2)
    assert not tuned["docling"]["enabled"]


@pytest.mark.parametrize("cuda_available, override, expected", [
    (False, None, "cpu"), (True, None, "cuda"), (True, "cpu", "cpu"), (True, "cuda", "cuda"),
])
def test_local_auto_uses_cuda_when_available_and_respects_explicit_cpu(monkeypatch, cuda_available, override, expected):
    from src.ocr.runtime import device
    monkeypatch.setattr(device, "cuda_available", lambda: cuda_available)
    converter = ConvertDocumentUseCase()
    assert converter.profiles["local"]["device"] == "auto"
    config = converter.resolve_profile("local", override)
    assert config["device"] == expected
    assert config["backend_devices"]["ocr_recognition"] == expected
    assert config["backend_devices"]["ocr_detection"] == "cpu"
    assert config["backend_devices"]["docling"] is None
    assert config["num_threads"] == 2 and config["batch_size"] == 4


def test_local_explicit_cuda_fails_if_not_available(monkeypatch):
    from src.ocr.runtime import device
    monkeypatch.setattr(device, "cuda_available", lambda: False)
    with pytest.raises(RuntimeError, match="no CUDA device"):
        ConvertDocumentUseCase().resolve_profile("local", "cuda")


@pytest.mark.parametrize("batch_size", [0, -1, True, 1.5])
def test_vietocr_rejects_invalid_batch_size_before_loading_models(batch_size):
    with pytest.raises(ValueError, match="batch_size"):
        VietnameseSeq2SeqEngine(batch_size=batch_size)


def _fake_engine():
    engine = object.__new__(VietnameseSeq2SeqEngine)
    engine.batch_size = 2
    boxes = [[[5, 5 + i * 25], [90, 5 + i * 25], [90, 25 + i * 25], [5, 25 + i * 25]] for i in range(5)]
    engine._detector = Mock(return_value=(boxes, None))
    engine._recognizer = Mock()
    return engine


@pytest.mark.parametrize("failure", [None, "exception", "short_texts", "short_probs"])
def test_vietocr_chunks_preserve_all_boxes_text_and_confidence_when_one_batch_fails(failure):
    engine = _fake_engine()
    text = ["Công ty cổ phần", "Doanh thu thuần", "Lợi nhuận sau thuế", "1.234.567", "Năm 2025"]
    probabilities = [.91, .82, .93, .84, .95]
    sizes = []

    def predict_batch(crops, return_prob):
        sizes.append(len(crops))
        if len(sizes) == 1:
            return text[:2], probabilities[:2]
        if len(sizes) == 2:
            if failure == "exception":
                raise RuntimeError("batch memory limit")
            if failure == "short_texts":
                return text[2:3], probabilities[2:4]
            if failure == "short_probs":
                return text[2:4], probabilities[2:3]
            return text[2:4], probabilities[2:4]
        return text[4:], probabilities[4:]

    engine._recognizer.predict_batch.side_effect = predict_batch
    engine._recognizer.predict.side_effect = list(zip(text[2:4], probabilities[2:4]))
    result = engine.predict_image(np.zeros((150, 100, 3), dtype=np.uint8))
    assert sizes == [2, 2, 1]
    assert [line["text_raw"] for line in result] == text
    assert [line["confidence"] for line in result] == probabilities
    assert [line["bbox"][1] for line in result] == [5.0, 30.0, 55.0, 80.0, 105.0]
    assert engine._recognizer.predict.call_count == (2 if failure else 0)


def test_primary_ocr_calls_reuse_inference_thread_and_close_releases_it():
    import threading
    processor = object.__new__(ProcessPageUseCase)
    processor.ocr_engine = Mock()
    processor.ocr_engine.predict_image.side_effect = lambda image: [threading.current_thread()]
    processor.structure_extractor = Mock()
    try:
        first = processor._predict_image_counted(None, timeout_seconds=1)
        second = processor._predict_image_counted(None, timeout_seconds=1)
        assert first[0] is second[0] and first[0] is not threading.current_thread()
        assert processor._current_page_ocr_calls == 2
    finally:
        processor.close()
    assert not first[0].is_alive() and processor._ocr_executor is None


def test_width_grouping_restores_detection_order_for_text_probability_and_boxes():
    engine = _fake_engine()
    widths = [85, 20, 70, 35, 55]
    boxes = [[[5, 5 + i * 25], [width, 5 + i * 25], [width, 25 + i * 25], [5, 25 + i * 25]]
             for i, width in enumerate(widths)]
    engine._detector.return_value = boxes, None
    recognized_order = []

    def predict_batch(crops, return_prob):
        values = [crop.getpixel((3, 3))[0] for crop in crops]
        recognized_order.extend(values)
        return [f"Dòng {value}" for value in values], [value / 10 for value in values]

    image = np.zeros((150, 100, 3), dtype=np.uint8)
    for i in range(5):
        image[5 + i * 25:25 + i * 25, 5:widths[i]] = i + 1
    engine._recognizer.predict_batch.side_effect = predict_batch
    result = engine.predict_image(image)
    assert recognized_order == [2, 4, 5, 3, 1]
    assert [item["text"] for item in result] == [f"Dòng {i}" for i in range(1, 6)]
    assert [item["confidence"] for item in result] == [.1, .2, .3, .4, .5]
    assert [item["bbox"][2] for item in result] == widths


def test_timeout_drains_shared_model_before_returning_and_retains_failure():
    import threading
    import time
    finished = threading.Event()
    processor = object.__new__(ProcessPageUseCase)
    processor.structure_extractor = Mock()

    def inference(image):
        time.sleep(.03)
        finished.set()
        return [{"text": "Chậm"}]

    processor.ocr_engine = Mock(predict_image=inference)
    try:
        assert processor._predict_image_counted(None, timeout_seconds=.001) == []
        assert finished.is_set() and processor._page_errors == 1
        assert "timed out" in processor._ocr_failures[0]
        assert processor._predict_image_counted(None, timeout_seconds=1) == [{"text": "Chậm"}]
    finally:
        processor.close()


@pytest.mark.parametrize("options, expected_profile", [([], "local"), (["--profile", "fast"], "fast"),
                                                      (["--profile", "balanced"], "balanced")])
def test_monitor_runner_defaults_to_local_and_forwards_overrides(tmp_path, monkeypatch, options, expected_profile):
    from scripts import run_batch_test_with_monitoring as script
    (tmp_path / "sample.pdf").write_bytes(b"not-opened-by-stub")
    converter = ConvertDocumentUseCase()
    runner = Mock(profile_config=converter.resolve_profile(expected_profile, "cpu"))
    factory = Mock(return_value=runner)
    monkeypatch.setattr(script, "BatchOCRRunner", factory)
    monkeypatch.setattr(script, "SystemMonitor", Mock())
    monkeypatch.setattr(script, "build_workbook", Mock())
    monkeypatch.setattr(script, "generate_test_markdown_report", Mock())
    output = tmp_path / "out"
    script.main(["--inputs", str(tmp_path), "--output", str(output), "--limit", "1",
                 "--threads-per-worker", "3", "--batch-size", "2", *options])
    assert factory.call_args.kwargs["profile"] == expected_profile
    assert factory.call_args.kwargs["threads_per_worker"] == 3
    assert factory.call_args.kwargs["batch_size"] == 2
    assert factory.call_args.kwargs["excel_path"] == str(output / "OCR_BENCHMARK_RESULTS.xlsx")
    runner.execute_batch.assert_called_once_with(limit=1)


def test_invalid_monitor_profile_does_not_start_background_monitor(tmp_path, monkeypatch):
    from scripts import run_batch_test_with_monitoring as script
    (tmp_path / "sample.pdf").write_bytes(b"not-opened")
    monitor = Mock()
    monkeypatch.setattr(script, "SystemMonitor", monitor)
    with pytest.raises(SystemExit):
        script.main(["--inputs", str(tmp_path), "--output", str(tmp_path / "out"), "--profile", "missing"])
    monitor.assert_not_called()
