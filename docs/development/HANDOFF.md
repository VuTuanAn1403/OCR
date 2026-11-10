# Bàn giao

Cập nhật 10/11/2026 tối, Asia/Bangkok. Nhánh `v8-diacritic-bounds-keyword-challenger`, PR [#1](https://github.com/VuTuanAn1403/OCR/pull/1); đã push tới `e422ced`. Không phiên nào sửa `src/`, nên OCR identity vẫn khớp khóa `BASELINE-V8-20261109-003`. Trạng thái: skill `ocr-pdf-knowledge-map` hoặc `scripts/check_knowledge_map.py --summary`. Nhật ký: [10/11](../../scratch/dev_sessions/20261110-v8-goal-tools/session.md), [P1](../../scratch/dev_sessions/20261109-v8-p1-gt-lock/session.md).

## 10/11: P1 (V8-011/012)

Mục tiêu: đưa 38 mục backlog lên `DONE`. Không có bằng chứng thì không đánh `DONE`.

- **Sàng lọc:** người dùng sàng lọc 7 PDF development; cả 7 `ACCEPTED` (24.172 slot `MATCH`, 0 `MISMATCH`), seal ở `scratch/v8/screening/sealed/`. Kiểm lại mù 1.552 chữ làm từ 17/11 (`scratch/v8/screening/recheck/`).
- **Khóa đo (§7.6):**
  - v2: lần đo đầu tính chữ trong bảng là bị xóa (71.884/78.192 slot), nên bị thay.
  - v3: ghép với dòng pha A (`text_evidence`) và ghi 7 seal.
  - v4 (hiện hành, `c3283795…`): giữ nguyên v3, thêm mẫu phân xử 3.000/9.733 mục chọn theo seed; mục ngoài mẫu tính là lỗi.
- **Đo dev theo v4** (`scratch/v8/v8_011_measurement_dev_003_v4_20261110.json`), trước phân xử:
  - `DSER_strict` 13.751/345.300: dấu thanh 4.421, đ 601, xóa 7.933;
  - 3.195 slot xóa do lỗi §4.1;
  - ρ_U 0,025.
- **Phiếu phân xử mẫu:** `scratch/v8/adjudication/v8_011_dev_003_v4_sample3000_20261110/`. 122 quyết định trên phiếu đầy đủ cũ thuộc mẫu, chờ chuyển sang.
- **Cổng dấu:** `diacritic_acceptance.py` và `release_gate.py` đếm theo `DSER_strict`.
- **V8-080:** audit v2 (`..._003_r2_20261110.json`) và phiếu 72 số trong bảng.
- **`DONE` mới:** V8-150, V8-120, V8-170.
- **Hồi quy CPU sau khóa v4:** passed (`scratch/runs/20261110-211007-829a62be`).

## Phát hiện còn mở

- **Phiếu mất dữ liệu:** khung trình duyệt của app giữ localStorage trong RAM, nên đã mất 71 quyết định bảng và khoảng nửa phiếu phân xử đầy đủ. Từ nay chỉ mở phiếu qua `scripts/serve_review_sheets.py` (cấu hình `screening-sheets`, `table-review`, `adjudication-sheets`); mọi quyết định được ghi ra `<phiếu>/autosave/`.
- **Đặc tả 13 §4.1:** 3.652 khối chữ trong ảnh vắng khỏi `extraction.json`.
- **Bảng heuristic:** `src/ocr_structure/document_layout_engine.py:661` gán `bbox=r[0].bbox` cho cả hàng (315/513 ô có số). Cùng hàm sửa "12…HDPE" thành "D…" (646–647) và bỏ ô đầu "0"/"-" (651–652).
- **Lỗi nhỏ:** `validation.py` import lười `benchmark.accuracy_first`; `runtime-models.json` ghi nhầm `V8-065`.
- Sửa các lỗi `src/` ở trên là đổi identity, cần khóa baseline mới.

## Bước kế tiếp (cần người dùng)

1. Chấm phiếu mẫu 3.000 mục (không mở `ab_key.json`), rồi `adjudicate_text_layer_diacritics.py seal --decisions <phiếu>/autosave/*.decisions.jsonl`. Kiểm lại mù sàng lọc từ 17/11.
2. Chấm 72 mục phiếu số trong bảng, rồi `build_table_number_review.py seal`.
3. Gán nhãn GT bằng `label_structured_gt.py` (V8-060/070/071/080); chạy Vintern theo [`vlm/README.md`](../../benchmark/challengers/vlm/README.md).
4. Quyết định thời điểm sửa lỗi `src/`, và push.
