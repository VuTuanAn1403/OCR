"""V8-050 candidate: recognition_line_upscale, off by default."""
from types import SimpleNamespace

import pytest
from PIL import Image

from ocr_recognition.vietnamese_seq2seq_engine import VietnameseSeq2SeqEngine
from ocr_workers.page_engines import ConfigError, validate_page_config


class _Recorder:
    def __init__(self):
        self.sizes = []

    def predict_batch(self, images, return_prob=False):
        self.sizes.extend(image.size for image in images)
        return ["x"] * len(images), [0.9] * len(images)


@pytest.mark.parametrize("factor,expected", [(1, (40, 10)), (2, (80, 20))])
def test_every_recognized_crop_is_upscaled_only_when_enabled(factor, expected):
    recorder = _Recorder()
    engine = SimpleNamespace(line_upscale=factor, batch_size=4, _recognizer=recorder)
    texts, probs = VietnameseSeq2SeqEngine._recognize_crops(engine, [Image.new("RGB", (40, 10), "white")] * 3)
    assert texts == ["x"] * 3 and recorder.sizes == [expected] * 3


@pytest.mark.parametrize("value", [0, 5, 1.5, "2", True])
def test_invalid_upscale_is_rejected_before_any_page(value):
    with pytest.raises(ConfigError, match="recognition_line_upscale"):
        validate_page_config({"recognition_line_upscale": value})


def test_absent_upscale_keeps_production_behaviour():
    validate_page_config({})
    validate_page_config({"recognition_line_upscale": 2})
