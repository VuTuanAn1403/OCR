"""V8-065: the product detector is PP-OCRv6 medium, fed the way it was trained.

The registry entry must carry the thresholds of the model's own inference.yml, and
`channel_order` decides whether the BGR page is converted before normalization.
"""
import json
from pathlib import Path

import numpy as np
import pytest
import yaml

from ocr_recognition.text_detector import ONNXTextDetector

ROOT = Path(__file__).resolve().parents[3]
REGISTRY = json.loads((ROOT / "models/v62/runtime-models.json").read_text(encoding="utf-8"))


def bare_detector(channel_order):
    detector = object.__new__(ONNXTextDetector)  # no ONNX session: prepare() only
    detector.limit, detector.channel_order = 64, channel_order
    detector.mean = np.zeros(3, dtype=np.float32)
    detector.std = np.ones(3, dtype=np.float32)
    return detector


def test_channel_order_controls_the_tensor_channels():
    image = np.zeros((32, 32, 3), dtype=np.uint8)
    image[:, :, 0] = 255  # blue in a BGR page
    bgr, _ = bare_detector("BGR").prepare(image)
    rgb, _ = bare_detector("RGB").prepare(image)
    assert bgr[0, 0].mean() == pytest.approx(1.0) and bgr[0, 2].mean() == pytest.approx(0.0)
    assert rgb[0, 2].mean() == pytest.approx(1.0) and rgb[0, 0].mean() == pytest.approx(0.0)


def test_registry_selects_pinned_pp_ocrv6_medium_with_its_own_postprocess():
    detector = REGISTRY["text_detector"]
    assert detector["model_path"] == "models/v62/PP-OCRv6_medium_det/inference.onnx"
    assert REGISTRY["files"][detector["model_path"]] == detector["sha256"]
    assert detector["source"]["repo"] == "PaddlePaddle/PP-OCRv6_medium_det_onnx"
    assert len(detector["source"]["revision"]) == 40 and detector["source"]["license"] == "apache-2.0"
    assert detector["channel_order"] == "BGR"
    config = yaml.safe_load((ROOT / detector["source"]["config"]).read_text(encoding="utf-8"))
    post = config["PostProcess"]
    assert config["Global"]["model_name"] == "PP-OCRv6_medium_det"
    assert (detector["threshold"], detector["box_threshold"], detector["rectangle_expansion"]) == \
        (post["thresh"], post["box_thresh"], post["unclip_ratio"])
    decode = next(step["DecodeImage"] for step in config["PreProcess"]["transform_ops"] if "DecodeImage" in step)
    assert decode["img_mode"] == detector["channel_order"]
