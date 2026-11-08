# Lộ trình v8.0 theo tầng (Benchmark-first)

Căn cứ: Kế hoạch Benchmark-first và So sánh công nghệ (hai DOCX lưu ở commit `08f7602`, xem [00](00_README.md)), kiểm toán [02](02_KIEM_TOAN_KHOANG_TRONG.md) và [IMPLEMENTATION_ROADMAP](../docs/quality_assurance/IMPLEMENTATION_ROADMAP.md) (QA-01..09).

"v8.0" là **nhãn chương trình**. Mã nguồn vẫn ở `PIPELINE_VERSION = 7.0.0` cho tới PR tích hợp (V8-160).

## Trạng thái pha

<!-- v8-status:phases:begin -->
| Pha | Tên | Trạng thái | Cổng ra | Backlog |
| --- | --- | --- | --- | --- |
| R1 | Tài liệu nền, bản đồ kiến thức, skill | DONE | check_knowledge_map exit 0; hồi quy không có lỗi mới | V8-002, V8-003, V8-004, V8-005, V8-170 |
| P0 | Khóa baseline | IN_PROGRESS | BASELINE_LOCK_REPORT có đủ identity | V8-001, V8-006 |
| P1 | Ground Truth và protocol | BLOCKED | Protocol LOCKED, GT độc lập đủ cỡ mẫu | V8-010, V8-011, V8-012, V8-013 |
| P2 | Tiền xử lý ảnh IMG-01..06 | TODO | Paired fix/harm từng biến | V8-050 |
| P3 | Phát hiện chữ DET-01..07 | TODO | TP/FP/FN cùng snapshot | V8-060 |
| P4 | Nhận dạng chữ A/B/C/D | TODO | Tách hiệu ứng detector và recognizer | V8-065, V8-030 |
| P5 | Layout và thứ tự đọc | TODO | Class/region/order scorecard trên GT | V8-070, V8-071 |
| P6 | Bảng và công thức | TODO | TEDS, numeric cell, ownership | V8-080, V8-085 |
| P7 | VLM fallback và parser đối chứng | TODO | Identity, tài nguyên, GT | V8-090, V8-095 |
| P8 | Hậu xử lý, dấu, keyword | IN_PROGRESS | Cổng dấu 99,99% và 0 thiếu/thừa occurrence | V8-020, V8-021, V8-022, V8-031, V8-032, V8-100 |
| P9 | End-to-end và hồ sơ quyết định | TODO | Quyết định thủ công PROMOTE/KEEP/REJECT/INCONCLUSIVE | V8-140, V8-160 |
<!-- v8-status:phases:end -->

## Nguyên tắc chuyển pha

- **Mọi tầng hiện tại là Baseline.** Model mới là Challenger, chạy trong `benchmark/challengers/` với venv riêng ([05](05_HOP_DONG_BENCHMARK_ADAPTER.md)).
- **Mỗi experiment chỉ đổi một biến.** Tham số chỉnh trên development, ngưỡng chọn trên calibration, holdout chỉ dùng một lần sau khi khóa.
- **Không có GT độc lập thì quyết định là `INCONCLUSIVE`**, kể cả khi test pass hay artifact PASS.
- **Tốt riêng lẻ chưa đủ.** Phải qua end-to-end (P9) trước mọi đề xuất PROMOTE.

## Chi tiết pha

| Pha | Mục tiêu | Cổng vào | Deliverable | QA |
| --- | --- | --- | --- | --- |
| R1 | Tài liệu nền, bản đồ kiến thức, skill, sửa template/link (đợt này) | Kế hoạch được duyệt | Bộ `cai tien v2/00–10`, `scripts/check_knowledge_map.py`, skill | — |
| P0 | Khóa baseline: commit, diff, lock, sha model, GPU/CUDA, sha PDF | R1 | `bao_cao/BASELINE_LOCK_REPORT.md` | QA-01 |
| P1 | Chọn nguồn GT, khóa protocol, split theo công ty, kế hoạch cỡ mẫu ([04](04_DAC_TA_DO_DAU_9999.md) §4–5) | P0; người dùng quyết định nguồn GT (V8-013) | `GROUND_TRUTH_AND_PROTOCOL_STATUS`, protocol LOCKED | QA-01 |
| P2 | IMG-01..06: deskew, CLAHE, denoise, threshold, dewarp, DPI 180/300/400 | P1 | Paired fix/harm từng biến; ảnh trước/sau có sha | QA-09 |
| P3 | DET-01..07: PP-OCRv4 so với ứng viên detection | P1, V8-040 | TP/FP/FN trên `primary-text-detections-v1` | QA-04 |
| P4 | Recognition A/B/C/D (detector × recognizer); retry dấu theo keyword (V8-030) | P3 | Scorecard crop cố định và end-to-end; DSER, CER, keyword | QA-04 |
| P5 | LAY-01..08 Heron so với ứng viên; reading order | P1 | Precision/recall theo class, pair accuracy | QA-06 |
| P6 | Bảng (TEDS, numeric cell, ownership DC-01/TAB_05) và công thức | P1 | Table/formula scorecard, counterexample | QA-05 |
| P7 | VLM fallback cho trang khó; parser đối chứng | P3–P6 có baseline | Báo cáo VLM có identity, VRAM, latency | QA-09 |
| P8 | Hậu xử lý, cổng dấu 99,99%, keyword 0 thiếu/0 thừa | P1, V8-020..022 | `PAIRED_FIX_HARM_REPORT`, báo cáo dấu theo [04](04_DAC_TA_DO_DAU_9999.md) §8 | QA-04, QA-06 |
| P9 | End-to-end candidate và hồ sơ quyết định | P2–P8 | `END_TO_END_BENCHMARK_REPORT`, `CANDIDATE_SELECTION_DOSSIER` | QA-08, QA-09 |

## Thứ tự đề xuất

1. **R1 → P0 → P1.** Không đo accuracy khi protocol còn DRAFT.
2. **V8-020..022** (metric và thống kê dấu) song song với P1, vì chúng chặn mệnh đề 99,99%.
3. **V8-031/032** (keyword): chạy analysis mới trên extraction đã xác minh, không cần OCR lại.
4. **P3 → P4**, ưu tiên recognition vì liên quan trực tiếp tới dấu.
5. **P6, P5, P7**, rồi **P9**.

## Điểm dừng bắt buộc

- **P1 chưa khóa thì dừng.** Kết quả ghi `NOT_EVALUATED` và không công bố chất lượng.
- **Challenger cần dependency xung đột với production thì dừng.** Chuyển sang venv riêng hoặc loại khỏi danh sách.
- **VLM ghi đè raw hoặc tự suy số tài chính thì REJECT.**
