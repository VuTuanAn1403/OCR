from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from ocr_contracts.text_block import TextBlock
from ocr_recognition.diacritic_retry import diacritic_retry_settings, retry_diacritic_blocks
from ocr_text.vietnamese_diacritics import DIACRITIC_REVIEW_CODE


def test_diacritic_retry_settings_extra_phrases():
    # Default is empty tuple
    settings = diacritic_retry_settings({})
    assert settings["extra_phrases"] == ()

    # Valid list of strings converts to tuple
    settings = diacritic_retry_settings({"diacritic_retry": {"extra_phrases": ["thương mại điện tử", "chuyển đổi số"]}})
    assert settings["extra_phrases"] == ("thương mại điện tử", "chuyển đổi số")

    # Valid tuple of strings
    settings = diacritic_retry_settings({"diacritic_retry": {"extra_phrases": ("an toàn thông tin",)}})
    assert settings["extra_phrases"] == ("an toàn thông tin",)

    # Invalid types
    with pytest.raises(ValueError, match="extra_phrases"):
        diacritic_retry_settings({"diacritic_retry": {"extra_phrases": "not a list"}})
    with pytest.raises(ValueError, match="extra_phrases"):
        diacritic_retry_settings({"diacritic_retry": {"extra_phrases": [123]}})


def test_retry_diacritic_blocks_with_extra_phrases_detects_and_recovers():
    # "thuong mai dien tu" has missing diacritics for extra_phrase "thương mại điện tử"
    wrong_text = "Nền tảng thuong mai dien tu đa kênh"
    right_text = "Nền tảng thương mại điện tử đa kênh"
    block = TextBlock(text=wrong_text, text_raw=wrong_text, page=1, bbox=[10, 20, 200, 35],
                      source_id="src-1", quality_score=0.90)

    # Without extra_phrases, "thuong mai dien tu" is not in DEFAULT_PHRASES
    owner_no_extra = SimpleNamespace(config={"diacritic_retry": {"enabled": False}},
                                     renderer=Mock(), fallback_engine=Mock())
    candidates, suspicious = [], []
    record = retry_diacritic_blocks(owner_no_extra, 1, [block], candidates, suspicious)
    assert record["suspect_lines"] == 0
    assert DIACRITIC_REVIEW_CODE not in block.review_reason_codes

    # With extra_phrases, it flags the suspect line
    owner = SimpleNamespace(
        config={
            "diacritic_retry": {
                "enabled": True,
                "extra_phrases": ["thương mại điện tử"],
            }
        },
        renderer=Mock(),
        fallback_engine=Mock(),
    )
    owner.renderer.render_region_crop.return_value = (np.zeros((30, 200, 3), dtype=np.uint8), [10, 20, 200, 35])
    owner.fallback_engine.reocr_crop.return_value = {
        "text": right_text,
        "confidence": 0.98,
        "improved": True,
        "needs_review": False,
        "review_reason": None,
    }
    candidates, suspicious = [], []
    record = retry_diacritic_blocks(owner, 1, [block], candidates, suspicious)
    assert record["suspect_lines"] == 1
    assert record["attempted"] == 1
    assert record["improved"] == 1
    assert record["extra_phrases_count"] == 1
    assert block.text == right_text
    assert DIACRITIC_REVIEW_CODE not in block.review_reason_codes


def test_retry_diacritic_blocks_fallback_to_owner_keyword_phrases():
    # If not set in diacritic_retry, falls back to owner.keyword_phrases or owner.config["keyword_phrases"]
    wrong_text = "Hệ thống an toan thong tin doanh nghiệp"
    right_text = "Hệ thống an toàn thông tin doanh nghiệp"
    block = TextBlock(text=wrong_text, text_raw=wrong_text, page=1, bbox=[10, 20, 200, 35],
                      source_id="src-2", quality_score=0.88)
    owner = SimpleNamespace(
        config={"diacritic_retry": {"enabled": True}},
        keyword_phrases=("an toàn thông tin",),
        renderer=Mock(),
        fallback_engine=Mock(),
    )
    owner.renderer.render_region_crop.return_value = (np.zeros((30, 200, 3), dtype=np.uint8), [10, 20, 200, 35])
    owner.fallback_engine.reocr_crop.return_value = {
        "text": right_text,
        "confidence": 0.97,
        "improved": True,
        "needs_review": False,
        "review_reason": None,
    }
    candidates, suspicious = [], []
    record = retry_diacritic_blocks(owner, 1, [block], candidates, suspicious)
    assert record["suspect_lines"] == 1
    assert record["attempted"] == 1
    assert record["improved"] == 1
    assert block.text == right_text

