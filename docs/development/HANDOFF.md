# Bàn giao

Cập nhật 09/11/2026, Asia/Bangkok. Nhánh `v8-diacritic-bounds-keyword-challenger`, HEAD `2af5454` đã push, PR [#1](https://github.com/VuTuanAn1403/OCR/pull/1) bật Auto-fix. Sửa registry, backlog và protocol của phiên rà soát nằm ở commit ngay sau `2af5454`, chưa push (chỉ tài liệu, không đổi OCR identity). Identity hiện tại khớp khóa `BASELINE-V8-20261109-003` (extraction `ccdbe84a3691d645`, detector v6). Trạng thái: skill `ocr-pdf-knowledge-map` hoặc `scripts/check_knowledge_map.py --summary`. Phiên: [rà soát chỉ tiêu](../../scratch/dev_sessions/20261109-v8-target-review/session.md), [metric/keyword](../../scratch/dev_sessions/20261109-v8-metric-keyword-challenger/session.md), [review](../../scratch/dev_sessions/20261109-review-fixes/session.md).

## 09/11 chiều: rà soát chỉ tiêu `cai tien v2`

- **Chưa đạt chỉ tiêu nào.** Cổng dấu 99,99% `NOT_EVALUATED`: GT độc lập 1.788/29.956 slot. Keyword, thứ tự đọc và bảng chưa có GT; P3–P9 chưa đo.
- **Người dùng quyết:** V8-013 chọn nguồn (b) text layer born-digital. Giữ `PP-OCRv6_medium_det` trong production như ngoại lệ chưa qua GT (V8-060). Khóa 003 đã có từ trước và khớp fingerprint HEAD.
- **V8-011:** kiểm kê có 720/938 trang ứng viên, 345.687 slot (`scratch/v8/v8_011_text_layer_inventory_2af5454_20261109.json`), chưa là GT. Quy trình xác minh DRAFT ở `docs/quality_assurance/GROUND_TRUTH_PROTOCOL.md` §7.
- **Registry:**
  - L2 ghi PP-OCRv6; G02/G08 cập nhật.
  - V8-030 chuyển `IN_PROGRESS` (fix/harm cần GT); V8-011/013 chuyển `IN_PROGRESS`.
  - Pha R1/P1/P2/P4 chuyển `IN_PROGRESS`; xuất lại DOCX.

## 09/11 sáng: metric, keyword, challenger

- V8-020..022: `DSER_strict`, cận Clopper-Pearson, cổng OCR dùng cận trên. V8-031/032: `single_word_variants`, challenger `literal_v2` (v1 164, v2 154 trên V8-006).
- V8-040/041/043/110: `benchmark/challengers/`, E01–E13. V8-042: runner chạy qua `ocr_pipeline.cli.main`.
- Khóa `BASELINE-V8-20261109-002` tại `24a5558` (PP-OCRv4). V8-006: `output/v8_baseline_20261109_r2` 9/9 PDF, 938 trang, audit exit 0.
- V8-033: luật "cổ ông"; replay 53.291 dòng, 0 dòng đổi. V8-010: GT tổng hợp chỉ cho stress test.
- V8-130: DOCX/XLSX giữ ô gộp, 815/815 bảng round-trip. Tài liệu 11–13 xong.
- V8-065 (thực chất là V8-060): detector `PP-OCRv6_medium_det`, BGR, threshold 0.2/0.45; smoke ACL exit 0.
- V8-050 đang làm: `page_spread.py`, 324 trang ngang (252 2-UP, 39 1-UP, 33 UNCERTAIN).

## Kiểm tra đã chạy

- Hồi quy CPU tại `2af5454`: 2553 passed, 19 skipped, 1 failed (`scratch/runs/20261109-155207-40a5723e`). Lỗi là `test_real_checkout_map_has_no_errors`, do chạy đúng lúc sửa registry trước `--render`; chạy lại `test_check_knowledge_map.py` cho 36 passed (`scratch/runs/20261109-160031-20596da1`).
- 77 test sát thay đổi (`scratch/runs/20261109-154346-d676bcfb`); `check_knowledge_map.py --check` 0 lỗi.
- Quality vẫn `NOT_EVALUATED`.

## Phát hiện còn mở

- `src/ocr_document/validation.py` import lười `benchmark.accuracy_first`, contract chính không thấy.
- Docling `FAILED_FALLBACK` tạm thời: 3/938 trang ở V8-006. V8-120 ghi mã thoát worker; còn soak dài.
- `models/v62/runtime-models.json` ghi `V8-065` trong `decision`; không sửa vì thuộc identity model.

## Bước kế tiếp

Không có người gán A/B; không dùng AI hay output pipeline làm GT.

1. Người dùng duyệt và khóa §7 (seed, mẫu theo producer, α/k, split), chỉ định người duyệt và custodian. AGR/ASM/VIC chỉ dùng cho development.
2. Prediction 938 trang cho khóa 003: `output/v8_003_baseline_20261109` (log `scratch/v8/v8_003_baseline_batch_20261109.log`), rồi chạy audit `--validate` và `check_baseline_identity.py`. Khi batch chạy không sửa `src/`.
3. Xác minh text layer theo §7, ước lượng ρ trên development, rồi đo theo 04 §7. V8-170: người dùng chọn.

Đổi trạng thái thì sửa registry, chạy `--render` rồi `--check`. Commit khi người dùng duyệt.
