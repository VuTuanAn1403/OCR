"""Raw primary detections survive filtering, regional retries and serialization."""
import copy
import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pytest

from ocr_contracts.text_detection import validate_snapshot
from ocr_recognition.detection_evidence import capture_primary_detections, input_image_identity


def detector():
    return SimpleNamespace(METHOD="fixture-db", last_input_shape=[100, 200, 3], last_detections=[
        {"polygon": [[2., 4.], [12., 4.], [12., 14.], [2., 14.]], "bbox": [2., 4., 12., 14.], "score": np.float32(.8)}])


def test_snapshot_is_a_copy_of_all_raw_geometry_with_actual_input_pixel_identity():
    image = np.arange(100 * 200 * 3, dtype=np.uint8).reshape(100, 200, 3)
    identity = input_image_identity(image)
    assert identity["sha256"] == hashlib.sha256(image.tobytes()).hexdigest()
    engine = detector()
    evidence = capture_primary_detections(engine, identity, [600., 800.])
    assert evidence["status"] == "CAPTURED"
    assert evidence["pixel_to_page"] == [[3., 0., 0.], [0., 8., 0.], [0., 0., 1.]]
    engine.last_detections[0]["polygon"][0][0] = 100
    engine.last_detections.clear()
    identity["shape"][0] = 1
    assert evidence["detections"][0]["polygon"][0] == [2., 4.]
    assert evidence["input_image"]["shape"] == [100, 200, 3]
    validate_snapshot(json.loads(json.dumps(evidence, allow_nan=False)))


def test_blank_capture_is_different_from_missing_or_invalid_detector_evidence():
    identity = input_image_identity(np.zeros((100, 200, 3), np.uint8))
    engine = detector()
    engine.last_detections = []
    blank = capture_primary_detections(engine, identity, [600, 800])
    assert blank["status"] == "CAPTURED" and blank["detections"] == []
    for missing in (None, SimpleNamespace(last_input_shape=[10, 20, 3], last_detections=[])):
        snapshot = capture_primary_detections(missing, identity, [600, 800])
        validate_snapshot(snapshot)
        assert snapshot["status"] == "UNAVAILABLE" and "detections" not in snapshot
    engine = detector()
    engine.last_detections[0]["score"] = True
    assert capture_primary_detections(engine, identity, [600, 800])["status"] == "UNAVAILABLE"


def test_contract_rejects_corrupted_frames_shapes_boxes_and_scores():
    base = capture_primary_detections(detector(), input_image_identity(np.zeros((100, 200, 3), np.uint8)), [600, 800])
    altered = []
    for update in ({"pixel_to_page": [[1., 0., 0.], [0., 1., 0.], [0., 0., 1.]]}, {"page_size": [False, 800]}):
        altered.append({**base, **update})
    for field, value in (("bbox", [2, 4, 50, 14]), ("score", float("nan")), ("id", "d0")):
        bad = copy.deepcopy(base)
        bad["detections"][0][field] = value
        altered.append(bad)
    for bad in altered:
        with pytest.raises(ValueError):
            validate_snapshot(bad)


def test_strided_image_hash_matches_the_same_logical_pixels():
    pixels = np.arange(10 * 20 * 3, dtype=np.uint8).reshape(10, 20, 3)
    for image in (pixels[:, ::2], pixels[::-1], pixels[:, :, ::-1]):
        assert not image.flags.c_contiguous
        assert input_image_identity(image)["sha256"] == hashlib.sha256(image.tobytes()).hexdigest()


def test_input_hash_does_not_reinterpret_float_or_empty_images():
    for image in (np.zeros((10, 20, 3), np.float32), np.zeros((0, 20, 3), np.uint8), np.zeros((10, 20), np.uint8)):
        with pytest.raises(ValueError):
            input_image_identity(image)
