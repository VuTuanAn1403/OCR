"""
V5.0 Document Layout Analysis (DLA) Engine.

Provides deep vision-based and geometric layout decomposition into 9 scientific categories:
- TITLE
- SECTION_HEADER
- HEADER (Running page header)
- FOOTER (Running page footer)
- PAGE_NUMBER
- TABLE
- FIGURE
- CAPTION
- TEXT / PARAGRAPH
- LIST
- FORMULA

Supports ONNX Runtime deep learning inference (DocLayout-YOLO / PP-Structure Layout)
with a fast, robust geometric fallback when offline or for ultra-high-speed CPU passes.
"""

from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import re
import numpy as np
import cv2
import pymupdf

from src.ocr.domain.models.region import Region, BoundingBox, ContentType
from src.ocr.domain.models.text_block import TextBlock


# Standard 9-class schema for academic DLA benchmarks (COCO compatible)
DLA_CLASSES = [
    "title",           # 0
    "section_header",  # 1
    "text",            # 2
    "header",          # 3
    "footer",          # 4
    "page_number",     # 5
    "table",           # 6
    "figure",          # 7
    "caption",         # 8
    "list",            # 9
    "formula",         # 10
]

CLASS_TO_CONTENT_TYPE = {
    "title": ContentType.TITLE,
    "section_header": ContentType.SECTION_HEADER,
    "text": ContentType.TEXT,
    "header": ContentType.HEADER,
    "footer": ContentType.FOOTER,
    "page_number": ContentType.PAGE_NUMBER,
    "table": ContentType.TABLE,
    "figure": ContentType.FIGURE,
    "caption": ContentType.CAPTION,
    "list": ContentType.LIST,
    "formula": ContentType.FORMULA,
}


class HeuristicLayoutClassifier:
    """
    Heuristic and Geometric Document Layout Classifier.
    Executes geometric visual decomposition and element classification
    (renamed per Proposal R4; formerly named DLAEngine).
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        conf_threshold: float = 0.35,
        iou_threshold: float = 0.45,
        use_onnx: bool = True,
    ):
        self.model_path = Path(model_path) if model_path else None
        self.conf_threshold = conf_threshold
        self.iou_threshold = iou_threshold
        self.use_onnx = use_onnx
        self._session = None

        if self.use_onnx and self.model_path and self.model_path.exists():
            self._init_onnx_session()

    def _init_onnx_session(self) -> None:
        """Initializes ONNX Runtime session with CPU / CUDA ExecutionProvider."""
        try:
            import onnxruntime as ort
            providers = ["CPUExecutionProvider"]
            if "CUDAExecutionProvider" in ort.get_available_providers():
                providers.insert(0, "CUDAExecutionProvider")
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 4
            self._session = ort.InferenceSession(str(self.model_path), opts, providers=providers)
            print(f"[DLAEngine] Loaded ONNX model from {self.model_path} using {self._session.get_providers()[0]}")
        except Exception as e:
            print(f"[DLAEngine] Warning: Could not initialize ONNX session: {e}. Falling back to geometric DLA.")
            self._session = None

    def analyze_page(
        self,
        page: pymupdf.Page,
        page_num: int,
        page_image: Optional[np.ndarray] = None,
        total_pages: int = 1,
    ) -> List[Region]:
        """
        Decomposes a PDF page into typed semantic Regions.
        Combines deep visual features and structural geometry.
        """
        if self._session is not None and page_image is not None:
            try:
                return self._run_onnx_dla(page_image, page, page_num)
            except Exception as e:
                print(f"[DLAEngine] ONNX inference error: {e}. Using geometric fallback.")

        return self._run_geometric_dla(page, page_num, total_pages)

    def _run_onnx_dla(
        self,
        image: np.ndarray,
        page: pymupdf.Page,
        page_num: int,
    ) -> List[Region]:
        """Runs deep visual object detection on the page image."""
        h_orig, w_orig = image.shape[:2]
        target_size = 800  # Standard input resolution for fast DLA

        # Preprocessing: Letterbox resize
        scale = min(target_size / h_orig, target_size / w_orig)
        nw, nh = int(w_orig * scale), int(h_orig * scale)
        resized = cv2.resize(image, (nw, nh), interpolation=cv2.INTER_LINEAR)

        canvas = np.full((target_size, target_size, 3), 114, dtype=np.uint8)
        top = (target_size - nh) // 2
        left = (target_size - nw) // 2
        canvas[top : top + nh, left : left + nw] = resized

        blob = canvas.astype(np.float32) / 255.0
        blob = np.transpose(blob, (2, 0, 1))
        blob = np.expand_dims(blob, axis=0)

        input_name = self._session.get_inputs()[0].name
        outputs = self._session.run(None, {input_name: blob})
        preds = outputs[0]  # Shape: [1, num_boxes, 4 + num_classes] or [1, 4 + num_classes, num_boxes]

        # Postprocessing NMS
        boxes, scores, class_ids = self._parse_detections(preds, scale, left, top, w_orig, h_orig)

        regions: List[Region] = []
        for idx, (b, score, cid) in enumerate(zip(boxes, scores, class_ids)):
            cls_name = DLA_CLASSES[cid] if 0 <= cid < len(DLA_CLASSES) else "text"
            c_type = CLASS_TO_CONTENT_TYPE.get(cls_name, ContentType.TEXT)
            bb = BoundingBox(x0=round(b[0], 2), y0=round(b[1], 2), x1=round(b[2], 2), y1=round(b[3], 2))

            regions.append(Region(
                region_id=f"p{page_num}_dla_{idx+1}",
                bbox=bb,
                content_type=c_type,
                label=cls_name,
                category_id=cid,
                dla_score=round(float(score), 4),
                confidence=round(float(score), 4),
                source="ocr",
                reading_order=idx + 1,
            ))
        return regions

    def _parse_detections(
        self,
        preds: np.ndarray,
        scale: float,
        pad_x: int,
        pad_y: int,
        w_orig: int,
        h_orig: int,
    ) -> Tuple[List[List[float]], List[float], List[int]]:
        """Parses model output tensor with NMS into bounding boxes."""
        preds = np.squeeze(preds)
        if preds.shape[0] < preds.shape[1] and preds.shape[0] < 20:
            preds = preds.T

        boxes, scores, class_ids = [], [], []
        for row in preds:
            cx, cy, w, h = row[:4]
            cls_scores = row[4:]
            cid = int(np.argmax(cls_scores))
            score = float(cls_scores[cid])

            if score < self.conf_threshold:
                continue

            # Convert to original image coordinates
            x0 = (cx - w / 2 - pad_x) / scale
            y0 = (cy - h / 2 - pad_y) / scale
            x1 = (cx + w / 2 - pad_x) / scale
            y1 = (cy + h / 2 - pad_y) / scale

            x0 = max(0.0, min(float(w_orig), x0))
            y0 = max(0.0, min(float(h_orig), y0))
            x1 = max(0.0, min(float(w_orig), x1))
            y1 = max(0.0, min(float(h_orig), y1))

            if x1 > x0 and y1 > y0:
                boxes.append([x0, y0, x1, y1])
                scores.append(score)
                class_ids.append(cid)

        if not boxes:
            return [], [], []

        # OpenCV NMS
        cv_boxes = [[int(b[0]), int(b[1]), int(b[2] - b[0]), int(b[3] - b[1])] for b in boxes]
        indices = cv2.dnn.NMSBoxes(cv_boxes, scores, self.conf_threshold, self.iou_threshold)
        final_boxes, final_scores, final_cids = [], [], []
        for i in indices:
            idx = i if isinstance(i, int) else i[0]
            final_boxes.append(boxes[idx])
            final_scores.append(scores[idx])
            final_cids.append(class_ids[idx])

        return final_boxes, final_scores, final_cids

    def _run_geometric_dla(
        self,
        page: pymupdf.Page,
        page_num: int,
        total_pages: int = 1,
    ) -> List[Region]:
        """
        Fast, robust geometric & semantic layout classifier.
        Doesn't use fixed hardcoded strings. Dynamically detects:
        - Running headers and footers based on geometric position, font hierarchy, and margin bounds.
        - Page numbers based on standalone digits at header/footer bands.
        - Captions based on linguistic indicators (Hình, Bảng, Figure, Table).
        - Section headings and titles based on font sizes and numbering patterns.
        - Tables and figures based on vector drawings and embedded image rects.
        """
        page_w = page.rect.width
        page_h = page.rect.height
        regions: List[Region] = []
        region_counter = 0

        # Margin boundaries calculated dynamically based on page dimensions
        header_band_y = page_h * 0.10
        footer_band_y = page_h * 0.90

        # 1. Identify vector tables and figures
        table_rects = []
        try:
            tabs = page.find_tables()
            for t in tabs:
                tb = t.bbox
                bb = BoundingBox(x0=round(tb[0], 2), y0=round(tb[1], 2), x1=round(tb[2], 2), y1=round(tb[3], 2))
                if bb.area > 500:
                    region_counter += 1
                    table_rects.append(bb)
                    regions.append(Region(
                        region_id=f"p{page_num}_dla_{region_counter}",
                        bbox=bb,
                        content_type=ContentType.TABLE,
                        label="table",
                        category_id=6,
                        dla_score=0.95,
                        confidence=0.95,
                        source="vector",
                        reading_order=region_counter,
                    ))
        except Exception:
            pass

        # 2. Identify embedded images (FIGURE)
        for img_info in page.get_images():
            try:
                for img_rect in page.get_image_rects(img_info[0]):
                    bb = BoundingBox(x0=round(img_rect.x0, 2), y0=round(img_rect.y0, 2), x1=round(img_rect.x1, 2), y1=round(img_rect.y2, 2))
                    # Avoid noise icons (min 50x50pt) and avoid full-page background scans
                    if bb.area >= 2500 and (bb.area / (page_w * page_h)) < 0.85:
                        # Avoid duplicates overlapping with tables
                        if not any(bb.overlap_ratio(tr) > 0.6 for tr in table_rects):
                            region_counter += 1
                            regions.append(Region(
                                region_id=f"p{page_num}_dla_{region_counter}",
                                bbox=bb,
                                content_type=ContentType.FIGURE,
                                label="figure",
                                category_id=7,
                                dla_score=0.90,
                                confidence=0.90,
                                source="image",
                                reading_order=region_counter,
                            ))
            except Exception:
                pass

        # 3. Analyze text blocks (Titles, Headers, Footers, Captions, Section Headers, Body Text)
        raw_blocks = page.get_text("blocks")
        # Collect font stats to establish dynamic hierarchy
        font_sizes: List[float] = []
        try:
            dict_data = page.get_text("dict")
            for block in dict_data.get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        if span.get("text", "").strip():
                            font_sizes.append(span.get("size", 10.0))
        except Exception:
            pass

        base_font_size = float(np.median(font_sizes)) if font_sizes else 11.0

        for b in raw_blocks:
            if b[6] != 0:  # non-text
                continue
            text = b[4].strip()
            if not text:
                continue

            bb = BoundingBox(x0=round(b[0], 2), y0=round(b[1], 2), x1=round(b[2], 2), y1=round(b[3], 2))

            # Skip if inside table area
            if any(bb.overlap_ratio(tr) > 0.7 for tr in table_rects):
                continue

            # Classify semantic category
            c_type, label, cid = self._classify_text_block(
                text=text,
                bbox=bb,
                page_h=page_h,
                page_w=page_w,
                page_num=page_num,
                base_font_size=base_font_size,
                header_band_y=header_band_y,
                footer_band_y=footer_band_y,
            )

            region_counter += 1
            regions.append(Region(
                region_id=f"p{page_num}_dla_{region_counter}",
                bbox=bb,
                content_type=c_type,
                label=label,
                category_id=cid,
                dla_score=0.88,
                confidence=0.90,
                source="native",
                reading_order=region_counter,
            ))

        return regions

    def _classify_text_block(
        self,
        text: str,
        bbox: BoundingBox,
        page_h: float,
        page_w: float,
        page_num: int,
        base_font_size: float,
        header_band_y: float,
        footer_band_y: float,
    ) -> Tuple[ContentType, str, int]:
        """
        Classifies an individual text block into one of the 9 scientific categories.
        """
        clean_text = " ".join(text.split())
        line_count = len(text.splitlines())

        # 1. Page Number
        if re.match(r"^(\d+|[ivxlcdm]+|\btrang\s+\d+(\s*\/\s*\d+)?\b)$", clean_text, re.IGNORECASE):
            if bbox.y1 <= header_band_y or bbox.y0 >= footer_band_y:
                return ContentType.PAGE_NUMBER, "page_number", 5

        # 2. Running Header (Top margin, single line, page > 1)
        if bbox.y1 <= header_band_y and line_count <= 2 and page_num > 1:
            # If not a major section title
            if not re.match(r"^\s*(\d+(\.\d+)*\s*[\.\-]|[IVXLCDM]+\s*[\.\-])", clean_text):
                return ContentType.HEADER, "header", 3

        # 3. Running Footer (Bottom margin, 1-2 lines)
        if bbox.y0 >= footer_band_y and line_count <= 2:
            return ContentType.FOOTER, "footer", 4

        # 4. Caption (Begins with Figure/Table/Hình/Bảng/Biểu đồ)
        if re.match(r"^(hình|bảng|ảnh|sơ đồ|biểu đồ|figure|table|fig\.)\s+\d+[:\.\-]", clean_text, re.IGNORECASE):
            return ContentType.CAPTION, "caption", 8

        # 5. Formula / Equation
        if re.search(r"(=|\+|-|\*|/|sum|int)\s*\(\d+\)$", clean_text) or re.match(r"^\s*\$\$.*\$\$\s*$", clean_text):
            return ContentType.FORMULA, "formula", 10

        # 6. Title / Major Header (e.g. Page 1 big title, or all-caps bold short header)
        if page_num == 1 and bbox.y0 < page_h * 0.35 and len(clean_text) < 120 and line_count <= 3:
            if clean_text.isupper() or len(clean_text.split()) < 15:
                return ContentType.TITLE, "title", 0

        # 7. Section Header (e.g., "1. Giới thiệu", "II. Thực nghiệm", "1.2. Phương pháp")
        if re.match(r"^\s*(\d+(\.\d+)*|[A-Z]\.|[IVXLCDM]+\.|\bchương\b|\bphần\b|\bmục\b)\s+[^\n]+", clean_text, re.IGNORECASE):
            if line_count <= 2 and len(clean_text) < 150:
                return ContentType.SECTION_HEADER, "section_header", 1

        # 8. List
        if re.match(r"^\s*([\-\*•–\+]|\(\d+\)|\d+\))\s+", text):
            return ContentType.LIST, "list", 9

        # Default: Standard Body Paragraph
        return ContentType.TEXT, "text", 2


# Backward compatibility alias (Proposal R4)
DLAEngine = HeuristicLayoutClassifier
