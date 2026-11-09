# Bàn giao

Cập nhật 09/11/2026, Asia/Bangkok. Nhánh `v8-diacritic-bounds-keyword-challenger` (`24a5558`..`20207a2` trên `08f7602`; V8-120: `67a4e12`; 10 sửa review: `20207a2`, chưa push), PR [#1](https://github.com/VuTuanAn1403/OCR/pull/1) có Auto-fix. Commit chốt phiên ngay sau `20207a2` (người dùng duyệt, chưa push): V8-130, V8-065, V8-030, V8-050, tài liệu 11–13, registry, HANDOFF này; file `.onnx` không vào Git (`.gitignore`). OCR identity khác khóa 002 từ V8-033. Trạng thái: skill `ocr-pdf-knowledge-map` hoặc `scripts/check_knowledge_map.py --summary`. [Phiên 09/11](../../scratch/dev_sessions/20261109-v8-metric-keyword-challenger/session.md); [HANDOFF trước phiên](../../scratch/dev_sessions/20261109-v8-metric-keyword-challenger/handoff-before.md).

## 09/11: metric dấu, keyword, challenger (theo `cai tien v2`)

- **V8-020..022**: `DSER_strict` song song `DER_VN_v1`; cận Clopper-Pearson (`exact_bounds.py`); cổng OCR `release_gate.py::_ocr_diacritic_bound_gate` dùng cận trên, 0 lỗi cần `design_effect` đã khóa.
- **V8-031/032**: `single_word_variants` (không cộng); challenger `literal_v2`, sản phẩm vẫn `literal_v1`. Trên V8-006: v1 164, v2 154 (`B2B`/`B2C` trong `B2B2C`, VIC); 0 biến thể một từ.
- **V8-040/041/043, V8-110, V8-012, V8-170**: `benchmark/challengers/` (experiment_id, manifest, catalog 0/8 được tải, contract riêng); E01–E13; 1.788 slot CLW; harness thiếu thì skip.
- **Khóa** `BASELINE-V8-20261109-002` tại `24a5558`. **V8-006 DONE**: `output/v8_baseline_20261109_r2` 9/9 PDF, 938 trang; audit exit 0; identity MATCH 9/9. Lần 1 hỏng vì sửa `src/` khi batch chạy.
- **V8-042 DONE**: `matrix_runner`, `run_perf` chạy sản phẩm qua `ocr_pipeline.cli.main` ở tiến trình con (`benchmark/product_run.py`); ACL: F/V1/A6 COMPLETED, F (`png`) và perf khớp khóa 002.
- **V8-033 DONE** (đổi `src/ocr_text`, identity mới): luật "cổ ông" chỉ viết lại `cổ ông`/`CỔ ÔNG`, giữ danh xưng `Cổ Ông`. Replay 53.291 dòng V8-006: 0 dòng đổi. Smoke ACL `output/v8_033_smoke_acl_20261109` exit 0.
- **Review 09/11**: 10 sửa ([phiên](../../scratch/dev_sessions/20261109-review-fixes/session.md)): "cổ ông" không vượt dòng, company_id, chặn trùng tên, perf.json, throughput/lock.
- **V8-010 DONE**: `synthetic_diacritics.py` (`STRESS_TEST_ONLY`). 150 DPI: keyword DSER 0/375 slot; lưới âm tiết 165/530 và 148/530.
- **V8-130 DONE**: `structured_export.py`: DOCX/XLSX giữ ô gộp. 9 PDF: 815/815 bảng round-trip đạt, không mất chữ.
- **Tài liệu 11–13 DONE**: `11` (8 quy tắc R-RO); `12` (quy trình 6 bước, 938 trang, tách 2-UP); `13` (toán D/I/S, DSER_strict). Xuất `OCR_PDF_V8_BO_TAI_LIEU.docx` (49.213 B).
- **V8-065 PP-OCRv6 Det**: Tải `PP-OCRv6_medium_det` (62 MB), ghim BGR, threshold 0.2/0.45. Smoke ACL exit 0.
- **V8-030 DONE**: `diacritic_retry` nhận `extra_phrases` từ keyword/config; 34 test pass (`test_diacritic_retry.py`).
- **V8-050 IN_PROGRESS**: `page_spread.py` (1-UP/2-UP/UNCERTAIN, tách L/R, map bbox ngược) và `scripts/analyze_page_spreads.py`; 938 trang khớp đặc tả 12 (324 ngang: 252 2-UP, 39 1-UP, 33 UNCERTAIN); 6 test pass.
- **Nguồn đã xóa**: 3 tài liệu; registry `git_preserved` = `08f7602` (clone nông: NOT_EVALUATED).

## Kiểm tra đã chạy

- Hồi quy CPU sau review: 2536 passed; sau V8-030/050: 181 passed (recognition, text, spread, dser_strict).
- `lint-imports` (pyproject) và contract `challengers`, `v8-runners`: 21 passed. `check_knowledge_map.py --check`: 0 lỗi.
- Quality vẫn NOT_EVALUATED; chưa có GT độc lập.

## Phát hiện mới

- `src/ocr_document/validation.py` import lười `benchmark.accuracy_first` (dòng 326). Contract chính không thấy (`benchmark` là gói external); sửa đổi closure extraction.
- Docling `FAILED_FALLBACK` tạm thời: 3/938 trang ở V8-006, thêm ACL trang 23 ở smoke V8-033; worker chết không có traceback.
- **V8-120 (đổi `src/`)**: lỗi trang Docling ghi mã thoát và `worker.log`; log pha theo lần chạy ở `<generation>/logs/<run>/`. Tiêm lỗi trên ACL (`scripts/inject_docling_fault.py`): trang 1 `exit code 15`, trang 2–24 phục hồi, audit đạt.

## Bằng chứng trước phiên: giữ nguyên, chưa đo lại

QA-02 registry offline, dọn dẹp 06/11, Global Alias v1 86/86, GAP-03/DC-01/DC-02/TAB_05: xem [HANDOFF trước phiên](../../scratch/dev_sessions/20261109-v8-metric-keyword-challenger/handoff-before.md).

## Giới hạn và bước kế tiếp

User xác nhận không có người A/B; không dùng AI hay protocol làm GT. GT, split, protocol và ngưỡng còn thiếu.

1. Commit đã chốt; kế tiếp: khóa mới và chạy dự đoán 938 trang cho mã có V8-033.
2. V8-120 còn soak dài. V8-030 cần GT để đo fix/harm. Mã hiện tại (sau review) chưa smoke OCR.
3. Khi batch chạy, không sửa `src/`. V8-013, V8-170: người dùng chọn.

Đổi trạng thái thì sửa registry, chạy `--render` rồi `--check`. Commit khi người dùng duyệt.
