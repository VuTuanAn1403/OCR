"""Wire validation for primary full-page detector evidence; no model imports."""
import math
import re


SCHEMA = "primary-text-detections-v1"


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate_snapshot(data):
    """Reject malformed evidence, including a frame or image identity mismatch."""
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA:
        raise ValueError("Unknown primary text detection snapshot schema")
    if data.get("status") == "UNAVAILABLE":
        if not isinstance(data.get("reason"), str) or not data["reason"].strip():
            raise ValueError("Unavailable detector evidence requires a reason")
        if data.keys() != {"schema_version", "status", "reason"}:
            raise ValueError("Unavailable detector evidence cannot contain fabricated detections")
        return
    if data.get("status") != "CAPTURED" or data.keys() != {
        "schema_version", "status", "method", "input_image", "page_size", "pixel_to_page", "detections"
    }:
        raise ValueError("Invalid primary detector evidence fields or status")
    if not isinstance(data["method"], str) or not data["method"].strip():
        raise ValueError("A captured detector needs its actual adapter method")
    image = data["input_image"]
    if not isinstance(image, dict) or image.keys() != {"shape", "dtype", "color_space", "sha256"}:
        raise ValueError("Detector input image identity is incomplete")
    shape = image["shape"]
    if (not isinstance(shape, list) or len(shape) != 3 or shape[2] != 3
            or any(type(n) is not int or n < 1 for n in shape)
            or image["dtype"] != "uint8" or image["color_space"] != "BGR"
            or not isinstance(image["sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", image["sha256"]) is None):
        raise ValueError("Detector input must identify HWC BGR uint8 pixel values in C order")
    size = data["page_size"]
    if not isinstance(size, list) or len(size) != 2 or any(not _number(n) or n <= 0 for n in size):
        raise ValueError("Detector page size must have two finite positive dimensions")
    height, width, _ = shape
    expected = [[size[0] / width, 0., 0.], [0., size[1] / height, 0.], [0., 0., 1.]]
    matrix = data["pixel_to_page"]
    if (not isinstance(matrix, list) or len(matrix) != 3
            or any(not isinstance(row, list) or len(row) != 3 for row in matrix)
            or any(not _number(value) or not math.isclose(value, expected[i][j], rel_tol=1e-12, abs_tol=1e-12)
                   for i, row in enumerate(matrix) for j, value in enumerate(row))):
        raise ValueError("Detector pixel-to-page transform differs from the captured frame")
    rows = data["detections"]
    if not isinstance(rows, list):
        raise ValueError("Captured detections must be an array, including an explicit empty array")
    for index, row in enumerate(rows):
        if (not isinstance(row, dict) or row.keys() != {"id", "bbox", "polygon", "score"}
                or row["id"] != f"d{index:06d}"):
            raise ValueError("Detector records must retain unique IDs in the original detector order")
        polygon, box, score = row["polygon"], row["bbox"], row["score"]
        if (not isinstance(polygon, list) or len(polygon) < 3 or any(
                not isinstance(point, list) or len(point) != 2
                or any(not _number(n) for n in point) or not 0 <= point[0] <= width
                or not 0 <= point[1] <= height for point in polygon)):
            raise ValueError("Detector polygons require finite points inside the source image")
        if not isinstance(box, list) or len(box) != 4 or any(not _number(n) for n in box):
            raise ValueError("Detector bbox must preserve finite xyxy coordinates")
        hull = [min(p[0] for p in polygon), min(p[1] for p in polygon),
                max(p[0] for p in polygon), max(p[1] for p in polygon)]
        if any(not math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-6) for a, b in zip(box, hull)):
            raise ValueError("Detector bbox differs from its polygon hull")
        # Degenerate detections remain in the evidence. A scorer counts them
        # as false positives rather than silently discarding model output.
        if score is not None and (not _number(score) or not 0 <= score <= 1):
            raise ValueError("Detector score must be observed in [0, 1] or unavailable")
