# Bàn giao

Cập nhật 10/11/2026 tối, Asia/Bangkok. Nhánh `v8-diacritic-bounds-keyword-challenger`, PR [#1](https://github.com/VuTuanAn1403/OCR/pull/1); đã push tới `e422ced`. Không phiên nào sửa `src/`, nên OCR identity vẫn khớp khóa `BASELINE-V8-20261109-003`. Trạng thái: skill `ocr-pdf-knowledge-map` hoặc `scripts/check_knowledge_map.py --summary`. Nhật ký: [10/11](../../scratch/dev_sessions/20261110-v8-goal-tools/session.md), [P1](../../scratch/dev_sessions/20261109-v8-p1-gt-lock/session.md).

## 10/11: P1 (V8-011/012)

Mục tiêu: đưa 38 mục backlog lên `DONE`. Không có bằng chứng thì không đánh `DONE`.

- **Sàng lọc:** người dùng sàng lọc 7 PDF development; cả 7 `ACCEPTED` (24.172 slot `MATCH`, 0 `MISMATCH`), seal ở `scratch/v8/screening/sealed/`. Kiểm lại mù 1.552 chữ làm từ 17/11 (`scratch/v8/screening/recheck/`).
- **Khóa đo (§7.6):**
  - v2→v5: bỏ ghép chỉ item `b` (tính bảng là xóa), ghép dòng pha A và ghi 7 seal, phân xử một phần (mục chưa chấm là lỗi). Chi tiết ở protocol §7.6.
  - v6 (`5fc27a6f…`): phiếu ghi loại mục ("một bên trống") và ngữ cảnh trung lập.
  - v7 (hiện hành, `e7e875ce…`): khung đóng vào chỗ trống, không vào chữ bên cạnh (`gap_box`). Cả hai không thêm lựa chọn.
- **Đo dev** (`..._dev_003_v6_20261111.json`), trước phân xử: 13.751/345.300 (thanh 4.421, đ 601, xóa 7.933; 3.195 slot xóa do lỗi §4.1).
- **Phân xử v6 (seal `scratch/v8/adjudication/sealed/v8_011_dev_003_v6_partial_20261111/`):** 5.021/9.733 mục; AAA, AGR 2022, ASM, BCE đủ, AGR 2020 782/783; VIC chưa chấm.
  - Khi khác OCR: text layer đúng 82,2%, OCR đúng 6,1%, cả hai sai 11,6%. ASM: text layer dùng `ƣ` thay `ư` (352 mục).
  - Đếm bảo thủ 14.274/346.402 (4,1%); AAA 3,7%, ASM 3,6%; ρ_U 0,026. OCR còn rất xa 99,99%.
  - 464 mục "cả hai sai" là chữ OCR chèn ở đầu/cuối dòng; khung đóng vào chữ bên cạnh nên người duyệt gõ lại chữ đó. Độ nhạy: 14.175/345.779. Khóa v7 đã sửa khung.
  - Loại lỗi (seal v5) AAA+AGR 2020 (`..._v8_012_diacritic_confusions_aaa_agr2020_20261111.json`): 350/354 lỗi đ là Đ hoa→D (HĐQT→HDQT ~209); mất dấu nặng 260, huyền 170; hỏi→huyền/sắc 260.
  - Challenger `benchmark/challengers/acronym_diacritics.py` (V8-030): `DSER_strict` 3.499→3.229 trên AAA và AGR 2020, 226 đơn vị được sửa, 2 bị làm sai (`scratch/v8/v8_030_acronym_challenger_dev_20261111.json`). Đo trên chính dữ liệu dev nên là `INCONCLUSIVE`; cần holdout.
- **Cổng dấu:** `diacritic_acceptance.py` và `release_gate.py` đếm theo `DSER_strict`.
- **V8-080:** audit v2 (`..._003_r2_20261110.json`) và phiếu 72 số trong bảng.
- **`DONE` mới:** V8-150, V8-120, V8-170.
- **Hồi quy CPU sau khóa v7:** 2.648 passed, 1 skipped (`scratch/runs/20261111-232032-ae46506f`).

## Phát hiện còn mở

- **Phiếu mất dữ liệu:** khung trình duyệt của app giữ localStorage trong RAM, nên đã mất 71 quyết định bảng và khoảng nửa phiếu phân xử đầy đủ. Từ nay chỉ mở phiếu qua `scripts/serve_review_sheets.py` (cấu hình `screening-sheets`, `table-review`, `adjudication-sheets`); mọi quyết định được ghi ra `<phiếu>/autosave/`.
- **Đặc tả 13 §4.1:** 3.652 khối chữ trong ảnh vắng khỏi `extraction.json`.
- **Bảng heuristic:** `src/ocr_structure/document_layout_engine.py:661` gán `bbox=r[0].bbox` cho cả hàng (315/513 ô có số). Cùng hàm sửa "12…HDPE" thành "D…" (646–647) và bỏ ô đầu "0"/"-" (651–652).
- **Lỗi nhỏ:** `validation.py` import lười `benchmark.accuracy_first`; `runtime-models.json` ghi nhầm `V8-065`.
- Sửa các lỗi `src/` ở trên là đổi identity, cần khóa baseline mới.

## Bước kế tiếp (cần người dùng)

1. Kiểm lại mù sàng lọc từ 17/11. Quyết định có chuẩn hóa `ƣ`→`ư` cho text layer không (đổi quy trình, cần khóa mới).
2. Chấm 72 mục phiếu số trong bảng, rồi `build_table_number_review.py seal`.
3. Gán nhãn GT bằng `label_structured_gt.py` (V8-060/070/071/080); chạy Vintern theo [`vlm/README.md`](../../benchmark/challengers/vlm/README.md).
4. Quyết định thời điểm sửa lỗi `src/`, và push.

## 11/11 tối — kiểm tra phiên Claude Code

- HEAD `ce4c58a`, hơn ref `origin` cục bộ 9 commit. Claude đang dựng phiếu V8-011 v6 và chuẩn bị chuyển quyết định cũ. Khóa v6 tái lập được. Đo 7 PDF dev trước phân xử cho `DSER_strict` 13.751/345.300. Cổng dấu 99,99% vẫn `NOT_EVALUATED`.
- Hồi quy của Claude có 2.646 đạt, 1 bỏ qua. Sau sửa chuyển quyết định, nhóm test phân xử có 10 đạt. Bản đồ v8 và diff check qua.
- Tái hiện `context()` có thể chứa từ đang khác giữa OCR và text layer ở mục bên cạnh. Kiểm tra tính trung lập trước khi dùng phiếu cho holdout.
  - Đã sửa trước khi khóa v6 lần cuối: ngữ cảnh chỉ lấy chữ nằm trong khối giống nhau và dừng ở chữ lệch đầu tiên (test `test_items_say_when_one_side_is_empty_and_show_neutral_context`).
- [Nhật ký và bằng chứng](../../scratch/dev_sessions/20261111-project-claude-status/session.md).
