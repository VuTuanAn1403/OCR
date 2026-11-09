# Bàn giao

Cập nhật 09/11/2026 tối, Asia/Bangkok. Nhánh `v8-diacritic-bounds-keyword-challenger`, HEAD `3c6fdcf` đã push, PR [#1](https://github.com/VuTuanAn1403/OCR/pull/1) bật Auto-fix. Thay đổi của phiên P1 chưa commit; phiên không sửa `src/`, nên OCR identity không đổi. Identity khớp khóa `BASELINE-V8-20261109-003` (extraction `ccdbe84a3691d645`, detector v6). Trạng thái dự án: skill `ocr-pdf-knowledge-map` hoặc `scripts/check_knowledge_map.py --summary`. Nhật ký phiên: [P1 khóa GT](../../scratch/dev_sessions/20261109-v8-p1-gt-lock/session.md), [rà soát chỉ tiêu](../../scratch/dev_sessions/20261109-v8-target-review/session.md), [metric/keyword](../../scratch/dev_sessions/20261109-v8-metric-keyword-challenger/session.md).

## 09/11 tối: khóa quy trình GT text layer (P1)

- **Người dùng quyết:**
  - Cả 9 PDF `inputs/` là `development_only`, vì AAA, BCE và BHN cũng đã có exposure qua alias và keyword.
  - Holdout sẽ là PDF born-digital mới.
  - Người dùng là người duyệt kiêm custodian.
- **Khóa v1:** [`locks/v8_011_text_layer_procedure_lock_v1.json`](../quality_assurance/locks/v8_011_text_layer_procedure_lock_v1.json), sha256 `b0c20a84…2e0a`. Khóa gắn với inventory v2 (`129f18dc…`), seed `V8-011-LOCK-20261109`, α = 0,05, k = 0, N_eff ≥ 29.956, ngưỡng sàng lọc 2.995 slot. Tạo và kiểm bằng `scripts/lock_text_layer_procedure.py`; `--verify --pdf-root inputs` exit 0.
- **Protocol §7 LOCKED v1:** gồm tiêu chí chọn mẫu (lấy toàn bộ slot đủ điều kiện, ⌊N/DEFF⌋ ≥ 29.956 với m_w = Σm²/Σm) và cơ chế người duyệt (sàng lọc trước đo, phân xử A/B mù, kiểm lại mù sau 7 ngày, hồ sơ JSONL có seal).
- **Backlog:** V8-013 chuyển `DONE`. V8-011 và V8-012 vẫn `IN_PROGRESS`: chưa sàng lọc 7 PDF (58 trang, 24.194 slot), chưa có ρ và holdout. Đã cập nhật registry G02 và cổng dấu, cùng 02/04. DOCX được xuất lại.
- **Kiểm tra:**
  - `check_knowledge_map.py --check`: exit 0, 0 lỗi, 0 STALE.
  - 81 test sát thay đổi đạt (`scratch/runs/20261109-200940-cc2e87bc`).
  - Chưa chạy hồi quy CPU đầy đủ.
  - Quality vẫn `NOT_EVALUATED`.

## 09/11 trước đó

- Rà soát chỉ tiêu: chưa đạt chỉ tiêu nào. Keyword, thứ tự đọc và bảng chưa có GT; P3–P9 chưa đo.
- Đã có V8-020..022 (`DSER_strict`, cận Clopper-Pearson), V8-031/032 (`literal_v2`), V8-040..043/110 (challenger), V8-033 và V8-130.
- V8-060: production dùng `PP-OCRv6_medium_det` như ngoại lệ chưa qua GT. V8-050: `page_spread.py` (324 trang ngang).
- Hồi quy CPU tại `2af5454`: 2553 passed, 19 skipped. Test hỏng duy nhất là do chạy giữa lúc sửa registry; chạy lại thì đạt (`scratch/runs/20261109-160031-20596da1`).

## Phát hiện còn mở

- `src/ocr_document/validation.py` import lười `benchmark.accuracy_first`, contract chính không thấy.
- Docling `FAILED_FALLBACK` tạm thời: 3/938 trang ở V8-006; còn soak dài.
- `models/v62/runtime-models.json` ghi `V8-065` trong `decision`; không sửa vì thuộc identity model.

## Bước kế tiếp

Không dùng AI hay output pipeline làm GT.

1. Người dùng sàng lọc 7 PDF theo worklist trong khóa (§7.4 B) và ghi sai lệch theo producer. Xong việc này thì V8-011 hoàn tất.
2. Viết công cụ còn thiếu: phiếu sàng lọc và phân xử, lọc span hiển thị, ghép OCR với span theo bbox, ước lượng ρ kèm cận trên.
3. Chạy prediction 938 trang cho khóa 003 vào `output/v8_003_baseline_20261109`, rồi chạy audit `--validate` và `check_baseline_identity.py`. Khi batch đang chạy không sửa `src/`.
4. Đo development, ước lượng ρ, rồi thu thập holdout mới theo §7.4 F.

Đổi trạng thái thì sửa registry, chạy `--render` rồi `--check`. Commit khi người dùng duyệt.
