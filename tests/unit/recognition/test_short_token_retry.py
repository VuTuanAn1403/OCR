from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from ocr_contracts.text_block import TextBlock
from ocr_recognition.short_token_retry import retry_short_token_blocks, short_token_retry_settings
from ocr_text.numeric_guard import SHORT_TOKEN_REVIEW_CODE


def test_image_disagreement_keeps_original_numbers_bbox_and_source_id():
    text = "mô hình (020) năm 2020"
    block = TextBlock(text=text, text_raw=text, page=1, bbox=[10, 20, 130, 35],
                      source_id="source-1", quality_score=.99)
    owner = SimpleNamespace(config={"short_token_retry": {"enabled": True}},
                            renderer=Mock(), ocr_engine=Mock())
    owner.renderer.render_region_crop.return_value = (np.zeros((60, 400, 3), dtype=np.uint8), [8, 18, 132, 37])
    owner.ocr_engine.predict_image.return_value = [{"text": "mô hình (O2O) năm 2020", "confidence": .99}]
    candidates, suspicious = [], []
    record = retry_short_token_blocks(owner, 1, [block], candidates, suspicious)
    assert record["attempted"] == 1 and record["applied"] == 0
    assert block.text == block.text_raw == text and block.source_id == "source-1"
    assert block.bbox == [10, 20, 130, 35] and not block.reviewed
    assert SHORT_TOKEN_REVIEW_CODE in block.review_reason_codes
    line = record["lines"][0]
    assert line["candidate_text"] == "mô hình (O2O) năm 2020"
    assert not line["numeric_evidence_preserved"] and not line["applied"]
    assert len(line["crop_bgr_sha256"]) == 64 and candidates == [block]
    assert TextBlock.model_validate(block.to_dict()).recognition_provenance["short_token_retry"] == line


def test_disabled_and_budgeted_proposals_still_request_review():
    blocks = [TextBlock(text="trực tuyến 020", page=1, bbox=[1, 1, 10, 10]) for _ in range(3)]
    owner = SimpleNamespace(config={}, renderer=Mock(), ocr_engine=Mock())
    assert retry_short_token_blocks(owner, 1, blocks, [], [])["attempted"] == 0
    owner.ocr_engine.predict_image.assert_not_called()
    owner.config = {"short_token_retry": {"enabled": True, "max_regions_per_page": 1}}
    owner.renderer.render_region_crop.return_value = (np.zeros((20, 20, 3), dtype=np.uint8), [1, 1, 10, 10])
    owner.ocr_engine.predict_image.return_value = []
    record = retry_short_token_blocks(owner, 1, blocks, [], [])
    assert record["suspect_lines"] == 3 and record["attempted"] == 1
    assert all(SHORT_TOKEN_REVIEW_CODE in block.review_reason_codes for block in blocks)


@pytest.mark.parametrize("options", [None, {"enabled": 1}, {"upscale_dpi": 299},
                                    {"upscale_dpi": 401}, {"max_regions_per_page": True}, {"unknown": 0}])
def test_settings_fail_closed(options):
    with pytest.raises(ValueError, match="short_token_retry"):
        short_token_retry_settings({"short_token_retry": options})
