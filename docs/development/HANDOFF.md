# Bàn giao

Cập nhật 09/11/2026 đêm, Asia/Bangkok. Nhánh `v8-diacritic-bounds-keyword-challenger`; `3c6fdcf` đã push, PR [#1](https://github.com/VuTuanAn1403/OCR/pull/1) bật Auto-fix. Chưa push: `5b4c6c5` (P1), `c477f34` (ghim LF), `39b0f0d` (V8-060) và commit dời `verified_head` lên `39b0f0d`. Không phiên nào sửa `src/`, nên OCR identity không đổi; identity khớp khóa `BASELINE-V8-20261109-003` (extraction `ccdbe84a3691d645`, detector v6). Trạng thái dự án: skill `ocr-pdf-knowledge-map` hoặc `scripts/check_knowledge_map.py --summary`. Nhật ký: [V8-060](../../scratch/dev_sessions/20261109-v8-060-detector/session.md), [P1 khóa GT](../../scratch/dev_sessions/20261109-v8-p1-gt-lock/session.md), [rà soát chỉ tiêu](../../scratch/dev_sessions/20261109-v8-target-review/session.md).

## 09/11 đêm: V8-060, so sánh detector v4 và v6

- **Batch khóa 003 xong 9/9.** Lần resume (`--resume --retry-failed`, 21:02–22:21, exit 0) chạy AAA, BHN, VIC. Identity MATCH 9/9, 938 trang (`scratch/v8/v8_060_identity_003_full_20261109.json`); audit `--validate` đủ trang, GPU gate PASS (`scratch/v8/v8_060_audit_003_20261109.json`).
- **Experiment `EXP-V8-DET-20261109-002`** (thay EXP-001, 6/9 PDF). `scripts/compare_detector_snapshots.py` chấm snapshot detector chính của run khóa 002 (`v8_baseline_20261109_r2`, v4) và khóa 003 (`v8_003_baseline_20261109`, v6). Báo cáo [`v8_060_detector_v4_v6_full_20261109.md`](../../scratch/v8/v8_060_detector_v4_v6_full_20261109.md) và `.json`; manifest ở `scratch/benchmarks/EXP-V8-DET-20261109-002/`.
- **Đồng thuận (938 trang cùng pixel):** 64.580 cặp, 3.459 box chỉ v6, 5.470 box chỉ v4, IoU 0,811. Không phải accuracy.
- **Text layer chưa xác minh (653 trang):** v4 P/R/H 0,750/0,917/0,825; v6 0,774/0,914/0,838. v6 cao hơn trên 371 trang, thấp hơn trên 135; Hmean cao hơn ở 6/7 PDF (AGR 2020 ngược lại).
- **Quyết định:** chỉ được `INCONCLUSIVE`; chưa có GT detection, manifest thiếu 17 trường.
- **Vận hành:** AAA hết ONNX arena (`gpu_mem_limit_mb` 1024) dưới v6 ở lần đầu, qua ở lần chạy lại từ trang 1 dù ứng dụng khác chiếm ~778 MiB VRAM. 1/2 lần thất bại, nguyên nhân chưa rõ.
- Đã cập nhật V8-060, L2, xuất lại DOCX; commit `39b0f0d`.

## 09/11 tối: khóa quy trình GT text layer (P1)

- Người dùng quyết: 9 PDF `inputs/` là `development_only`, holdout là PDF mới, người dùng là người duyệt kiêm custodian.
- Khóa [`v8_011_text_layer_procedure_lock_v1.json`](../quality_assurance/locks/v8_011_text_layer_procedure_lock_v1.json) (sha256 `b0c20a84…`) và protocol §7 LOCKED v1. V8-013 `DONE`. V8-011/012 còn chờ sàng lọc 7 PDF (58 trang, 24.194 slot), ρ và holdout.

## Trước đó

- Rà soát chỉ tiêu 09/11: chưa đạt chỉ tiêu nào; quality `NOT_EVALUATED`.
- Hồi quy CPU tại `2af5454`: 2553 passed, 19 skipped (`scratch/runs/20261109-160031-20596da1`). Chưa chạy hồi quy đầy đủ sau đó.

## Phát hiện còn mở

- `src/ocr_document/validation.py` import lười `benchmark.accuracy_first`, contract chính không thấy.
- Docling `FAILED_FALLBACK` tạm thời: 3/938 trang ở V8-006.
- `models/v62/runtime-models.json` ghi `V8-065` trong `decision`; không sửa vì thuộc identity model.

## Bước kế tiếp

Không dùng AI hay output pipeline làm GT.

1. Push các commit trên khi người dùng duyệt.
2. Người dùng sàng lọc 7 PDF theo worklist (§7.4 B) để hoàn tất V8-011.
3. Viết công cụ còn thiếu: phiếu sàng lọc và phân xử, ghép OCR với span theo bbox, ước lượng ρ, nhãn detection A/B (ưu tiên trang v4/v6 lệch nhiều, BCE và BHN).
4. Mỗi lần chạy AAA dưới v6, ghi lại có hết arena không và VRAM của ứng dụng khác.
