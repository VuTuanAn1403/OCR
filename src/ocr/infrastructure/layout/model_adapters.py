"""Explicit ONNX layout contracts, independent of model loading (C3.1/2).

Adapters return boxes in original image pixels. The caller then maps them to
PDF points; a YOLO letterbox must never be applied to RT-DETR outputs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import cv2
import numpy as np
import pymupdf
from src.ocr.infrastructure.pdf.coordinate_transform import render_coordinate_chain


@dataclass(frozen=True)
class Detection:
    bbox: tuple[float, float, float, float]
    score: float
    class_id: int


def _image(image: np.ndarray) -> np.ndarray:
    if image.ndim != 3 or image.shape[2] != 3 or min(image.shape[:2]) <= 0:
        raise ValueError("Layout input must be a nonempty BGR image with 3 channels")
    return image


def _clipped(box, width, height):
    box = np.asarray(box, dtype=float)
    if not np.isfinite(box).all():
        return None
    box[[0, 2]] = np.clip(box[[0, 2]], 0, width)
    box[[1, 3]] = np.clip(box[[1, 3]], 0, height)
    return tuple(box) if box[2] > box[0] and box[3] > box[1] else None


def image_box_to_pdf(box, image_shape, page: pymupdf.Page) -> list[float]:
    """Undo render scale and PDF rotation, using PyMuPDF crop-relative points.

PyMuPDF text boxes are relative to the unrotated crop box, rather than the
media box. This matches native text and does not add the crop offset twice.
"""
    height, width = image_shape[:2]
    if min(width, height) <= 0:
        raise ValueError("Image dimensions must be positive")
    return [round(v, 4) for v in render_coordinate_chain(page, image_shape).inverse().bbox(box)]


class YoloLayoutAdapter:
    """Raw YOLO export: [1,N,4+C] or [1,4+C,N], cxcywh and class scores.

Exports containing objectness or integrated NMS need their own adapter and
are rejected instead of being silently interpreted as this contract.
"""
    def __init__(self, class_count: int, input_size: int = 800,
                 threshold: float = .35, iou_threshold: float = .45,
                 channel_order: str = "rgb"):
        self.class_count = class_count
        self.input_size = int(input_size)
        self.threshold = threshold
        self.iou_threshold = iou_threshold
        self.channel_order = channel_order
        if self.input_size <= 0 or class_count <= 0 or channel_order not in {"rgb", "bgr"}:
            raise ValueError("Invalid YOLO layout configuration")
        if not 0 <= threshold <= 1 or not 0 <= iou_threshold <= 1:
            raise ValueError("Layout thresholds must be between 0 and 1")

    def prepare(self, image):
        image = _image(image)
        h, w = image.shape[:2]
        scale = min(self.input_size / h, self.input_size / w)
        nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
        resized = cv2.resize(image, (nw, nh), interpolation=cv2.INTER_LINEAR)
        left, top = (self.input_size - nw) // 2, (self.input_size - nh) // 2
        canvas = np.full((self.input_size, self.input_size, 3), 114, dtype=np.uint8)
        canvas[top:top + nh, left:left + nw] = resized
        if self.channel_order == "rgb":
            canvas = canvas[:, :, ::-1]
        tensor = np.ascontiguousarray(canvas.transpose(2, 0, 1)[None], dtype=np.float32) / 255
        return tensor, (w, h, nw / w, nh / h, left, top)

    def decode(self, outputs: Mapping[str, np.ndarray], geometry) -> list[Detection]:
        if len(outputs) != 1:
            raise ValueError("Raw YOLO adapter expects exactly one output tensor")
        preds = np.asarray(next(iter(outputs.values())))
        if preds.ndim == 3 and preds.shape[0] == 1:
            preds = preds[0]
        channels = 4 + self.class_count
        if preds.ndim != 2:
            raise ValueError("YOLO output must be [1,N,4+C] or [1,4+C,N]")
        if preds.shape[1] != channels and preds.shape[0] == channels:
            preds = preds.T
        if preds.shape[1] != channels:
            raise ValueError("YOLO class count does not match the configured label map")
        w, h, sx, sy, left, top = geometry
        candidates = []
        for row in preds:
            if not np.isfinite(row).all():
                continue
            cid = int(np.argmax(row[4:]))
            score = float(row[4 + cid])
            if not self.threshold <= score <= 1:
                continue
            cx, cy, bw, bh = row[:4]
            box = _clipped(((cx - bw / 2 - left) / sx, (cy - bh / 2 - top) / sy,
                            (cx + bw / 2 - left) / sx, (cy + bh / 2 - top) / sy), w, h)
            if box:
                candidates.append(Detection(box, score, cid))
        kept = []
        # NMS is class-specific: overlapping title/text/table are different labels.
        for cid in sorted({d.class_id for d in candidates}):
            group = [d for d in candidates if d.class_id == cid]
            boxes = [[d.bbox[0], d.bbox[1], d.bbox[2] - d.bbox[0], d.bbox[3] - d.bbox[1]] for d in group]
            indices = cv2.dnn.NMSBoxes(boxes, [d.score for d in group], self.threshold, self.iou_threshold)
            kept.extend(group[int(i)] for i in np.asarray(indices).reshape(-1))
        return sorted(kept, key=lambda d: (d.bbox[1], d.bbox[0], d.class_id, -d.score))


class RTDetrLayoutAdapter:
    """HF RT-DETR(v2) raw logits + normalized cxcywh pred_boxes; no NMS.

Defaults match Heron's published processor: stretch to 640x640, RGB /255,
no normalization. Export-specific mean/std and tensor names are configurable.
"""
    def __init__(self, class_count: int, input_size: int = 640, threshold: float = .35,
                 mean: Sequence[float] | None = None, std: Sequence[float] | None = None,
                 logits_name: str = "logits", boxes_name: str = "pred_boxes"):
        self.class_count = class_count
        self.input_size = int(input_size)
        self.threshold = threshold
        self.mean = None if mean is None else np.asarray(mean, dtype=np.float32)
        self.std = None if std is None else np.asarray(std, dtype=np.float32)
        self.logits_name, self.boxes_name = logits_name, boxes_name
        if self.input_size <= 0 or class_count <= 0:
            raise ValueError("Invalid RT-DETR layout configuration")
        if not 0 <= threshold <= 1:
            raise ValueError("Layout threshold must be between 0 and 1")
        if (mean is None) != (std is None) or (mean is not None and
                (self.mean.shape != (3,) or self.std.shape != (3,) or np.any(self.std <= 0)
                 or not np.isfinite(self.mean).all() or not np.isfinite(self.std).all())):
            raise ValueError("RT-DETR normalization requires three mean/std values and positive std")

    def prepare(self, image):
        image = _image(image)
        h, w = image.shape[:2]
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        value = cv2.resize(rgb, (self.input_size, self.input_size), interpolation=cv2.INTER_LINEAR).astype(np.float32) / 255
        if self.mean is not None:
            value = (value - self.mean) / self.std
        return np.ascontiguousarray(value.transpose(2, 0, 1)[None]), (w, h)

    def decode(self, outputs: Mapping[str, np.ndarray], geometry) -> list[Detection]:
        logits = np.asarray(outputs[self.logits_name])
        boxes = np.asarray(outputs[self.boxes_name])
        if (logits.ndim != 3 or logits.shape[0] != 1 or logits.shape[2] != self.class_count
                or boxes.shape != (1, logits.shape[1], 4)):
            raise ValueError("RT-DETR expects logits [1,N,C] and pred_boxes [1,N,4]")
        if not np.isfinite(logits).all() or not np.isfinite(boxes).all():
            raise ValueError("RT-DETR produced non-finite outputs")
        w, h = geometry
        scores = 1 / (1 + np.exp(-np.clip(logits[0], -80, 80)))
        # Same top-N query/class selection as HF's focal-loss postprocessor.
        indices = np.argsort(-scores.reshape(-1), kind="stable")[:logits.shape[1]]
        detections = []
        for index in indices:
            query, cid = divmod(int(index), self.class_count)
            score = float(scores[query, cid])
            if score <= self.threshold:
                continue
            cx, cy, bw, bh = boxes[0, query]
            box = _clipped(((cx - bw / 2) * w, (cy - bh / 2) * h,
                            (cx + bw / 2) * w, (cy + bh / 2) * h), w, h)
            if box:
                detections.append(Detection(box, score, cid))
        return sorted(detections, key=lambda d: (d.bbox[1], d.bbox[0], d.class_id, -d.score))


def build_adapter(kind: str, class_count: int, options: Mapping):
    if kind == "yolo":
        return YoloLayoutAdapter(class_count, options.get("input_size", 800),
                                 options.get("threshold", .35), options.get("iou_threshold", .45),
                                 options.get("channel_order", "rgb"))
    if kind == "rtdetr":
        return RTDetrLayoutAdapter(class_count, options.get("input_size", 640),
                                   options.get("threshold", .35), options.get("mean"), options.get("std"),
                                   options.get("logits_name", "logits"), options.get("boxes_name", "pred_boxes"))
    raise ValueError(f"Unknown layout adapter {kind!r}; supported: yolo, rtdetr")
