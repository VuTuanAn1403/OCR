"""Image orientation must not erase source geometry or competing readings."""
from unittest.mock import Mock

import numpy as np
import pytest

from ocr_contracts.text_block import TextBlock
from ocr_recognition.vietnamese_seq2seq_engine import VietnameseSeq2SeqEngine


def engine_for(box):
    engine = object.__new__(VietnameseSeq2SeqEngine)
    engine.batch_size = 2
    engine._detector = Mock(return_value=([box], None))
    engine._recognizer = Mock()
    return engine


@pytest.mark.parametrize('winner', [90, 270])
def test_vertical_candidates_preserve_pixels_bbox_raw_readings_and_review(winner):
    image = np.zeros((90, 40, 3), dtype=np.uint8)
    image[8:18, 8:18] = 255  # Marker at top-left of the padded source crop.
    box = [[10, 10], [20, 10], [20, 70], [10, 70]]
    engine = engine_for(box)
    batches = []

    def recognize(crops, **_):
        batches.append(len(crops))
        texts, probabilities = [], []
        for crop in crops:
            if crop.height > crop.width:
                angle, text = 0, 'N'
            elif crop.getpixel((crop.width-1, 0))[0] == 255:
                angle, text = 90, '(120)'
            else:
                angle, text = 270, '120'
            texts.append(text)
            probabilities.append(.98 if angle == winner else .2)
        return texts, probabilities

    engine._recognizer.predict_batch.side_effect = recognize
    result, = engine.predict_image(image)
    assert max(batches) <= 2
    assert result['bbox'] == [10, 10, 20, 70]
    assert result['text_raw'] == ('(120)' if winner == 90 else '120')
    assert result['text'] == result['text_raw']
    assert result['needs_review']
    assert 'orientation_unverified' in result['review_reason']
    provenance = result['recognition_provenance']
    assert provenance['rotation_clockwise_degrees'] == winner
    assert {c['text_raw'] for c in provenance['candidates']} == {'N', '(120)', '120'}
    # The audit payload survives the public block serialization contract.
    block = TextBlock(text=result['text'], page=1, recognition_provenance=provenance)
    assert TextBlock.model_validate(block.to_dict()).recognition_provenance == provenance


def test_tied_or_nan_orientation_scores_retain_original_reading():
    engine = engine_for([[10, 10], [20, 10], [20, 70], [10, 70]])
    engine._recognizer.predict_batch.side_effect = lambda crops, **_: (
        ['120'] * len(crops), [float('nan')] * len(crops))
    result, = engine.predict_image(np.zeros((90, 40, 3), dtype=np.uint8))
    assert result['recognition_provenance']['rotation_clockwise_degrees'] == 0
    assert result['confidence'] == 0
    assert result['needs_review']


def test_horizontal_line_keeps_one_original_crop_and_no_orientation_review():
    engine = engine_for([[10, 10], [70, 10], [70, 20], [10, 20]])
    engine._recognizer.predict_batch.return_value = (['Doanh thu 120'], [.98])
    result, = engine.predict_image(np.zeros((40, 90, 3), dtype=np.uint8))
    assert len(engine._recognizer.predict_batch.call_args.args[0]) == 1
    assert result['bbox'] == [10, 10, 70, 20]
    assert result['recognition_provenance'] == {}
    assert not result['needs_review']


def test_unusable_high_probability_candidate_does_not_discard_valid_rotated_reading():
    engine = engine_for([[10, 10], [20, 10], [20, 70], [10, 70]])

    def recognize(crops, **_):
        return ([('A A A' if crop.height > crop.width else 'Doanh thu') for crop in crops],
                [(.99 if crop.height > crop.width else .95) for crop in crops])

    engine._recognizer.predict_batch.side_effect = recognize
    result, = engine.predict_image(np.zeros((90, 40, 3), dtype=np.uint8))
    assert result['text_raw'] == 'Doanh thu'
    assert result['recognition_provenance']['rotation_clockwise_degrees'] == 90
    assert any(c['text_raw'] == 'A A A' for c in result['recognition_provenance']['candidates'])


def test_uncertain_horizontal_line_compares_180_without_moving_detector_bbox():
    engine = engine_for([[10, 10], [70, 10], [70, 20], [10, 20]])
    engine.horizontal_180_retry_threshold = .90
    engine._recognizer.predict_batch.side_effect = [(['chieu 021'], [.3]), (['Doanh thu 120'], [.98])]
    result, = engine.predict_image(np.zeros((40, 90, 3), dtype=np.uint8))
    assert result['text_raw'] == 'Doanh thu 120' and result['bbox'] == [10, 10, 70, 20]
    assert result['needs_review'] and result['recognition_provenance']['method'] == 'line-orientation-v2'
    assert result['recognition_provenance']['rotation_clockwise_degrees'] == 180
    assert [row['text_raw'] for row in result['recognition_provenance']['candidates']] == ['chieu 021', 'Doanh thu 120']


def test_confident_horizontal_control_does_not_run_a_second_pass():
    engine = engine_for([[10, 10], [70, 10], [70, 20], [10, 20]])
    engine.horizontal_180_retry_threshold = .90
    engine._recognizer.predict_batch.return_value = (['Doanh thu 120'], [.98])
    result, = engine.predict_image(np.zeros((40, 90, 3), dtype=np.uint8))
    assert engine._recognizer.predict_batch.call_count == 1 and result['recognition_provenance'] == {}


def test_180_tie_keeps_original_and_records_competing_reading():
    engine = engine_for([[10, 10], [70, 10], [70, 20], [10, 20]])
    engine.horizontal_180_retry_threshold = .90
    engine._recognizer.predict_batch.side_effect = [(['120'], [.8]), (['021'], [.8])]
    result, = engine.predict_image(np.zeros((40, 90, 3), dtype=np.uint8))
    assert result['text_raw'] == '120' and result['recognition_provenance']['rotation_clockwise_degrees'] == 0
    assert result['needs_review']
