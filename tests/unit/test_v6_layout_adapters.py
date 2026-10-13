"""C3.2 geometry counterexamples, without requiring layout weights."""
from types import SimpleNamespace
from unittest.mock import Mock
import sys

import numpy as np
import pymupdf
import pytest

from src.ocr.application.process_page import ProcessPageUseCase
from src.ocr.domain.models.text_block import TextBlock
from src.ocr.infrastructure.layout.dla_engine import DLAEngine
from src.ocr.infrastructure.layout.model_adapters import (
    RTDetrLayoutAdapter, YoloLayoutAdapter, build_adapter, image_box_to_pdf,
)


def test_yolo_undoes_asymmetric_letterbox_and_keeps_distinct_classes():
    adapter = YoloLayoutAdapter(2, input_size=800)
    tensor, geometry = adapter.prepare(np.zeros((400, 200, 3), dtype=np.uint8))
    assert tensor.shape == (1, 3, 800, 800)
    # Original box [20,40,100,200] -> letterbox [240,80,400,400].
    predictions = np.array([[[320, 240, 160, 320, .9, .1],
                             [320, 240, 160, 320, .8, .1],
                             [320, 240, 160, 320, .1, .95]]], dtype=np.float32)
    detections = adapter.decode({"output": predictions}, geometry)
    assert len(detections) == 2  # suppress same class only
    assert {d.class_id for d in detections} == {0, 1}
    assert detections[0].bbox == pytest.approx([20, 40, 100, 200])
    assert adapter.decode({"output": predictions.transpose(0, 2, 1)}, geometry) == detections


def test_rtdetr_stretches_rgb_without_letterbox_or_nms():
    image = np.zeros((400, 200, 3), dtype=np.uint8)
    image[:, :, 2] = 255
    adapter = RTDetrLayoutAdapter(1)
    tensor, geometry = adapter.prepare(image)
    assert tensor.shape == (1, 3, 640, 640)
    assert tensor[0, 0].min() == 1 and tensor[0, 2].max() == 0
    boxes = np.array([[[.3, .3, .4, .4], [.3, .3, .4, .4]]])
    detections = adapter.decode({"logits": np.array([[[5.], [4.]]]), "pred_boxes": boxes}, geometry)
    assert len(detections) == 2  # RT-DETR does not use YOLO NMS
    assert detections[0].bbox == pytest.approx([20, 40, 100, 200])


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_rendered_coordinates_return_to_native_crop_relative_pdf(rotation):
    with pymupdf.open() as doc:
        page = doc.new_page(width=600, height=900)
        page.set_cropbox(pymupdf.Rect(50, 70, 550, 870))
        page.set_rotation(rotation)
        expected = pymupdf.Rect(20, 40, 100, 200)
        rotated = expected * page.rotation_matrix
        image_shape = (round(page.rect.height * 2), round(page.rect.width * 2), 3)
        box = [v * 2 for v in rotated]
        assert image_box_to_pdf(box, image_shape, page) == pytest.approx(list(expected), abs=.01)


def test_dla_returns_pdf_points_instead_of_original_image_pixels():
    engine = DLAEngine(use_onnx=False, device="cpu")
    engine._session = Mock()
    engine._session.get_inputs.return_value = [SimpleNamespace(name="images")]
    engine._session.get_outputs.return_value = [SimpleNamespace(name="output")]
    scores = [.01] * 11
    scores[6] = .9
    engine._session.run.return_value = [np.array([[[320, 240, 160, 320, *scores]]])]
    with pymupdf.open() as doc:
        page = doc.new_page(width=100, height=200)
        region = engine._run_onnx_dla(np.zeros((400, 200, 3), dtype=np.uint8), page, 1)[0]
    assert region.bbox.to_list() == pytest.approx([10, 20, 50, 100])
    assert region.label == "table" and region.quality_score is None


def test_invalid_export_contract_is_explicit():
    with pytest.raises(ValueError, match="Unknown layout adapter"):
        build_adapter("paddlex", 23, {})
    adapter = RTDetrLayoutAdapter(2)
    with pytest.raises(ValueError, match="RT-DETR expects"):
        adapter.decode({"logits": np.zeros((1, 3, 1)), "pred_boxes": np.zeros((1, 3, 4))}, (100, 100))
    with pytest.raises(ValueError, match="class_names"):
        DLAEngine(use_onnx=False, model_config={"adapter": "rtdetr"}, device="cpu")


def test_failed_model_keeps_original_text_and_geometric_regions():
    proc = ProcessPageUseCase.__new__(ProcessPageUseCase)
    engine = Mock(model_path="layout.onnx", adapter_kind="rtdetr", device="cpu", _session=Mock())
    engine._run_onnx_dla.side_effect = ValueError("invalid tensors")
    proc.content_analyzer = SimpleNamespace(dla_engine=engine)
    proc.config = {}
    block = TextBlock(text="Original", page=1, bbox=[10, 10, 40, 40])
    regions, meta = [], {}
    proc._apply_layout_model(None, 1, [block], regions, meta, np.zeros((100, 100, 3), dtype=np.uint8))
    assert block.text == "Original" and not regions
    assert meta["layout_model"]["status"] == "FAILED_FALLBACK"
    assert "invalid tensors" in meta["layout_model"]["error"]


def test_legacy_rotated_ocr_is_not_mixed_with_original_pdf_boxes():
    proc = ProcessPageUseCase.__new__(ProcessPageUseCase)
    engine = Mock(model_path="layout.onnx", adapter_kind="rtdetr", device="cpu", _session=Mock())
    proc.content_analyzer = SimpleNamespace(dla_engine=engine)
    proc.config = {}
    meta = {"is_1up_landscape": True}
    proc._apply_layout_model(None, 1, [], [], meta, np.zeros((100, 100, 3), dtype=np.uint8))
    engine._run_onnx_dla.assert_not_called()
    assert meta["layout_model"]["status"] == "SKIPPED_COORDINATE_TRANSFORM_REQUIRED"


def test_cuda_provider_fallback_is_reported_instead_of_claiming_gpu(tmp_path, monkeypatch):
    from src.ocr.infrastructure.layout import dla_engine
    model = tmp_path / "model.onnx"
    model.write_bytes(b"mock")
    session = Mock()
    session.get_providers.return_value = ["CPUExecutionProvider"]
    ort = SimpleNamespace(SessionOptions=Mock(), InferenceSession=Mock(return_value=session),
                          get_available_providers=lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"])
    monkeypatch.setitem(sys.modules, "onnxruntime", ort)
    monkeypatch.setattr(dla_engine, "resolve_device", lambda _: "cuda")
    engine = DLAEngine(model_path=str(model), device="cuda")
    assert engine._session is None
    assert "fell back to CPU" in engine.last_error
