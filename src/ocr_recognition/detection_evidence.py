"""Capture the primary detector before regional retries replace its telemetry."""
import hashlib
from numbers import Real

from ocr_contracts.text_detection import SCHEMA, validate_snapshot


def input_image_identity(image):
    """Hash the original input buffer without materializing another page image."""
    view = memoryview(image)
    if (view.ndim != 3 or view.shape[2] != 3 or view.format != "B" or view.itemsize != 1 or min(view.shape) < 1):
        raise ValueError("Primary detector input must be HWC BGR uint8")
    digest = hashlib.sha256()
    if view.c_contiguous:
        digest.update(view)
    else:
        # Hash a strided image in logical C order with at most one row copy.
        # This is the same pixel identity as a contiguous view, without an
        # additional full-page allocation beside the live OCR image.
        for row in image:
            digest.update(memoryview(row).tobytes())
    return {"shape": list(view.shape), "dtype": "uint8", "color_space": "BGR",
            "sha256": digest.hexdigest()}


def capture_primary_detections(detector, image_identity, page_size):
    """Copy every raw detection, including lines later rejected by recognition."""
    try:
        def number(value):
            if isinstance(value, bool) or not isinstance(value, Real):
                raise ValueError("Detector coordinates and scores must be numeric observations")
            return float(value)

        if (detector is None or list(detector.last_input_shape) != image_identity["shape"]
                or not isinstance(detector.last_detections, list)):
            raise ValueError("Primary full-page detector telemetry is unavailable or belongs to another image shape")
        height, width, _ = image_identity["shape"]
        page_width, page_height = page_size
        snapshot = {"schema_version": SCHEMA, "status": "CAPTURED", "method": getattr(detector, "METHOD", None),
                    "input_image": {**image_identity, "shape": list(image_identity["shape"])},
                    "page_size": list(page_size),
                    "pixel_to_page": [[page_width / width, 0., 0.], [0., page_height / height, 0.], [0., 0., 1.]],
                    "detections": [{"id": f"d{index:06d}",
                                    "polygon": [[number(n) for n in point] for point in row["polygon"]],
                                    "bbox": [number(n) for n in row["bbox"]],
                                    "score": number(row["score"]) if row.get("score") is not None else None}
                                   for index, row in enumerate(detector.last_detections)]}
        validate_snapshot(snapshot)
        return snapshot
    except (AttributeError, KeyError, TypeError, ValueError, ZeroDivisionError, OverflowError) as exc:
        # Missing telemetry is not an empty detection result. Preserve that
        # distinction for historical/custom adapters and benchmark consumers.
        return {"schema_version": SCHEMA, "status": "UNAVAILABLE", "reason": f"{type(exc).__name__}: {exc}"}
