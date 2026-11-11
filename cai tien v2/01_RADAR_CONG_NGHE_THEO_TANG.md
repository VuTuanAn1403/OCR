# Radar công nghệ theo tầng

Tra ngày 08/11/2026. Dữ liệu thô là `scratch/dev_sessions/20261108-v8-knowledge-map/radar_research.json` (59 mục, chỉ có ở máy local): một subagent nghiên cứu đã mở trang chính thức (README GitHub, tài liệu PaddleOCR, model card HF, arXiv) và ghi lại.

**Cách đọc nhãn**
- `VERIFIED`: phiên chính đã tự mở trang và đối chiếu.
- `HYPOTHESIS`: mới chỉ có subagent đọc. Phải kiểm lại trước khi dùng.
- Accuracy trên corpus của dự án: **mọi dòng đều `NOT_EVALUATED`**. Điểm benchmark trong bảng là số **nhà phát triển tự công bố**, không phải bằng chứng cho báo cáo thường niên tiếng Việt.

Mọi ứng viên chỉ được thử theo [hợp đồng 05](05_HOP_DONG_BENCHMARK_ADAPTER.md), trong venv riêng, không đụng production. Phải kiểm licence của **cả code lẫn weights** trước khi tải.

## Kiểm lại trực tiếp của phiên chính (08/11)

| Mục | Kết quả |
| --- | --- |
| [PP-OCRv6](https://www.paddleocr.ai/main/en/version3.x/algorithm/PP-OCRv6/PP-OCRv6.html) | Trang tồn tại. Ba tầng tiny/small/medium, 1,5M–34,5M tham số. Trang nói hỗ trợ "46 Latin-script languages" nhưng **không ghi đích danh tiếng Việt**. Thông tin "paper liệt kê Vietnamese, thêm khoảng 200 ký tự dấu" vẫn là `HYPOTHESIS` |
| [PaddleOCR-VL-1.6](https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6) | Tồn tại, Apache-2.0, khoảng 1,0B tham số, phát hành 2026-05-28. Model card **không** nêu tiếng Việt |
| [Vintern-1B-v3.5](https://huggingface.co/5CD-AI/Vintern-1B-v3_5) | Tồn tại, MIT, 0,9B. Model card nêu rõ khả năng OCR và hiểu tài liệu tiếng Việt |
| VietOCR, OmniDocBench (GitHub) | Hai lần fetch đều lỗi 504, nên chưa kiểm được. Licence VietOCR không nhất quán (GitHub ghi Apache, PyPI ghi MIT) vẫn là `HYPOTHESIS` |

## L1 Tiền xử lý

| Ứng viên | Phiên bản | Licence code / weights | Ghi chú | Nhãn |
| --- | --- | --- | --- | --- |
| PP-LCNet doc_ori, textline_ori | PaddleOCR 3.7.0 | Apache / Apache | Xoay trang 0/90/180/270 và xoay dòng 0/180 | HYPOTHESIS |
| [UVDoc](https://github.com/tanguymagne/UVDoc) | SIGGRAPH Asia 2023 | MIT / chưa ghi | Ảnh sau khi khử cong không còn chung tọa độ với trang gốc, nên phải map bbox ngược | HYPOTHESIS |

## L2–L3 Phát hiện và nhận dạng chữ

| Ứng viên | Phiên bản | Licence | Tiếng Việt | Ghi chú | Nhãn |
| --- | --- | --- | --- | --- | --- |
| **VietOCR (baseline)** | PyPI 0.3.13 (2024-03) | Apache (GitHub) và MIT (PyPI); licence weights chưa ghi | Có | Chỉ nhận dạng dòng | HYPOTHESIS |
| **PP-OCRv6** det/rec | PaddleOCR 3.7.0 | Apache / Apache | Chưa nêu đích danh (xem trên) | Có bản ONNX; Docling có thể chạy PP-OCRv6 qua RapidOCR. Là ứng viên ưu tiên cho P3/P4 | VERIFIED (trang tồn tại) |
| PP-OCRv5 latin rec | 3.3.0 | Apache / Apache | Model Latin có tiếng Việt | Cùng họ DB với baseline detection | HYPOTHESIS |
| [Surya](https://github.com/datalab-to/surya) 2.5 | v0.23.0 | Apache / Open Rail-M (miễn phí khi doanh thu dưới 5 triệu USD) | Có (tự báo) | VLM 0,7B, chạy qua vLLM | HYPOTHESIS |
| [docTR](https://github.com/mindee/doctr) | v1.1.0 | Apache / chưa ghi | Chỉ có trong bảng ký tự | Model được huấn luyện chủ yếu trên tiếng Pháp | HYPOTHESIS |
| **Vintern-1B-v3.5** | 2025-12 | MIT / MIT | Có | Output dạng chat/Markdown, **không có bbox**. Chỉ nên dùng đối chứng | VERIFIED |
| Qwen2.5-VL / Qwen3-VL | 2025 | Licence khác nhau theo cỡ model | Không nêu | VLM tổng quát | HYPOTHESIS |

## L4–L5 Layout và thứ tự đọc

| Ứng viên | Phiên bản | Licence | Ghi chú | Nhãn |
| --- | --- | --- | --- | --- |
| **Docling Heron (baseline)** | HF 2026-02 | MIT / Apache | RT-DETR v2, 42,9M tham số | HYPOTHESIS |
| PP-DocLayout plus-L / V2 / V3 | V3 đi kèm PaddleOCR-VL 1.5/1.6 | Apache | V3 dự đoán box đa điểm và thứ tự đọc trong một lần chạy | HYPOTHESIS |
| [DocLayout-YOLO](https://github.com/opendatalab/DocLayout-YOLO) | 2024-10 | **AGPL-3.0** / Apache | Licence copyleft nên khó nhúng vào sản phẩm | HYPOTHESIS |
| LayoutReader | EMNLP 2021 | MIT; biến thể hantian là **CC-BY-NC-SA** | Đầu vào chỉ là bbox | HYPOTHESIS |
| Docling reading order | v2.149.0 | MIT | Rule-based, không có weights | HYPOTHESIS |

## L6 Bảng và công thức

| Ứng viên | Phiên bản | Licence | Ghi chú | Nhãn |
| --- | --- | --- | --- | --- |
| **TableFormer V1 (baseline)** / V2 preview | V2 trên HF ngày 2026-10-13 | V2 Apache | V2 có 52,4M tham số, vẫn là preview nên weights có thể đổi | HYPOTHESIS |
| SLANeXt / SLANet_plus | PaddleOCR 3.x | Apache | Chính tài liệu PaddleOCR cảnh báo bbox ô của SLANeXt không hợp lệ | HYPOTHESIS |
| UniTable | v1.0.0 (2024) | MIT | Một model ra cả cấu trúc, bbox và nội dung | HYPOTHESIS |
| Granite-Docling-258M | 2025-09 | Apache | Output DocTags có token vị trí | HYPOTHESIS |
| **CodeFormulaV2 (baseline)** | HF 2025-08 | MIT / CDLA-Permissive-2.0 | Ra LaTeX | HYPOTHESIS |
| UniMERNet, PP-FormulaNet_plus | 2024 / 3.x | Apache | PP-FormulaNet chỉ báo BLEU, không báo CDM | HYPOTHESIS |

## L6+ VLM và parser đầu-cuối (chỉ làm fallback hoặc đối chứng)

| Ứng viên | Phiên bản | Licence | Tiếng Việt | Ghi chú | Nhãn |
| --- | --- | --- | --- | --- | --- |
| **PaddleOCR-VL-1.6** | 2026-05-28 | Apache | Không nêu | Ứng viên ưu tiên cho P7; output JSON/Markdown | VERIFIED |
| [MinerU](https://github.com/opendatalab/MinerU) | 4.1.7 (2026-11-04) | Code Apache có điều kiện; weights MinerU2.5 **AGPL-3.0** | Không | README có lời nhắc nhắm vào AI agent; đã coi là dữ liệu | HYPOTHESIS |
| DeepSeek-OCR / OCR-2 | 2026-01 | MIT / Apache | Không | 3B; định dạng bbox chưa rõ | HYPOTHESIS |
| olmOCR-2 | toolkit v0.4.27 | Apache | Không (tiếng Anh) | Ra Markdown, không có bbox | HYPOTHESIS |
| dots.ocr / dots.mocr | 2026-03 | MIT | Không | JSON có bbox và thứ tự đọc | HYPOTHESIS |
| Marker | 2.1.0 | Apache / Open Rail-M | Không | Phải tắt `--use_llm` vì tùy chọn này gọi API ngoài | HYPOTHESIS |
| Chandra OCR 2 | v0.2.0 | Apache / OpenRAIL-M (miễn phí khi doanh thu dưới 2 triệu USD) | Có (tự báo) | | HYPOTHESIS |
| MonkeyOCRv2 | 2026-07 | Apache | Có | Schema bbox chưa mô tả | HYPOTHESIS |
| Dolphin-v2 | 2025-12 | **Qwen Research License** (phi thương mại), dù README gắn badge MIT | Không | | HYPOTHESIS |

## Bộ đo và dữ liệu

| Nguồn | Licence | Tiếng Việt | Dùng được cho | Nhãn |
| --- | --- | --- | --- | --- |
| OmniDocBench v1.7 | Chỉ cho nghiên cứu | Không | Đối chuẩn quốc tế (đã có adapter `benchmark/scientific_evaluation/omnidocbench_adapter.py`) | HYPOTHESIS |
| olmOCR-Bench | ODC-BY | Không | Tham khảo | HYPOTHESIS |
| MDPBench | Apache | Có cột tiếng Việt | Đối chiếu công khai, không riêng báo cáo tài chính | HYPOTHESIS |
| VieBookRead | CC-BY-NC, gated | Có | GT là **pseudo-GT** sinh từ Azure, nên **không** dùng làm GT độc lập | HYPOTHESIS |
| VinText | Chỉ cho nghiên cứu | Có | Chữ cảnh (scene text); chỉ để kiểm phụ phần dấu | HYPOTHESIS |
| CDM, TEDS | Apache / chưa ghi | — | Đã có trong `benchmark/scientific_evaluation/` | HYPOTHESIS |

## Kết luận dùng cho lộ trình

1. **Recognition và dấu (P4):** PP-OCRv6 (detection và recognition, có ONNX) là challenger đầu tiên. Phải đo trên crop cố định với `DSER_strict` ([04](04_DAC_TA_DO_DAU_9999.md)). Hỗ trợ tiếng Việt chưa được ghi rõ trên trang chính thức.
2. **VLM (P7):** chọn PaddleOCR-VL-1.6 hoặc dots.ocr, vì cả hai có licence mở và có bbox. Vintern chỉ dùng đối chứng chữ tiếng Việt.
3. **Loại khỏi danh sách sản phẩm** cho tới khi được duyệt licence: DocLayout-YOLO (AGPL), weights MinerU2.5 (AGPL), Dolphin (phi thương mại), LayoutReader bản hantian (NC).
4. **Không bộ benchmark công khai nào thay được GT độc lập trên báo cáo thường niên tiếng Việt** (G02).
