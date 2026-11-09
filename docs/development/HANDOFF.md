# Bàn giao

Cập nhật 09/11/2026, Asia/Bangkok. Nhánh `v8-diacritic-bounds-keyword-challenger`, commit `24a5558` trên `08f7602`, chưa push. Thay đổi sau commit (V8-010/033/042, tài liệu, registry) **chưa commit**; `src/ocr_text` đổi nên OCR identity khác khóa 002. Trạng thái: skill `ocr-pdf-knowledge-map` hoặc `scripts/check_knowledge_map.py --summary`. [Phiên 09/11](../../scratch/dev_sessions/20261109-v8-metric-keyword-challenger/session.md); [HANDOFF trước phiên](../../scratch/dev_sessions/20261109-v8-metric-keyword-challenger/handoff-before.md).

## 09/11: metric dấu, keyword, challenger (theo `cai tien v2`)

- **V8-020..022**: `DSER_strict` song song `DER_VN_v1` (`ocr_metric.py`; có trong `run_scientific_benchmark`); cận Clopper-Pearson trong `exact_bounds.py`; cổng OCR `release_gate.py::_ocr_diacritic_bound_gate` dùng cận trên, 0 lỗi cần `design_effect` đã khóa.
- **V8-031/032**: `single_word_variants` (không cộng); challenger `literal_v2`, sản phẩm vẫn `literal_v1`. Trên V8-006: v1 164, v2 154 (`B2B`/`B2C` trong `B2B2C`, VIC); 0 biến thể một từ.
- **V8-040/041/043, V8-110, V8-012, V8-170**: `benchmark/challengers/` (experiment_id, manifest, catalog 0/8 được tải, contract riêng); E01–E13; 1.788 slot CLW; harness thiếu thì skip.
- **Khóa** `BASELINE-V8-20261109-002` tại `24a5558`. **V8-006 DONE**: `output/v8_baseline_20261109_r2` 9/9 PDF, 938 trang; audit exit 0; identity MATCH 9/9. Lần 1 hỏng vì sửa `src/` khi batch chạy.
- **V8-042 DONE**: `matrix_runner`, `run_perf` chạy sản phẩm qua `ocr_pipeline.cli.main` trong tiến trình con (`benchmark/product_run.py`); contract `v8-runners`. ACL: F/V1/A6 COMPLETED; F (`--assets png`) và perf khớp khóa 002.
- **V8-033 DONE** (đổi `src/ocr_text`, identity mới): luật "cổ ông" chỉ viết lại `cổ ông`/`CỔ ÔNG`, giữ danh xưng `Cổ Ông`. Replay 53.291 dòng V8-006: 0 dòng đổi. Smoke ACL `output/v8_033_smoke_acl_20261109` exit 0.
- **V8-010 DONE**: `benchmark/ground_truth_tools/synthetic_diacritics.py` (build/score, `STRESS_TEST_ONLY`). 150 DPI: cụm keyword thật DSER 0/375 slot (sạch và nhiễu); lưới âm tiết vô nghĩa 165/530 và 148/530.
- **Nguồn đã xóa**: 3 tài liệu nguồn; registry `git_preserved` = `08f7602`.

## Kiểm tra đã chạy

- Hồi quy CPU unit/scientific/legacy sau V8-010/033/042: 2505 passed, 19 skipped, 0 lỗi; 5 xfail V8-033 nay đạt ([run](../../scratch/runs/20261109-100156-27f3abc9/run.json)).
- `lint-imports` (pyproject) và contract `challengers`, `v8-runners`: kept. `check_knowledge_map.py --check`: 0 lỗi.
- Quality vẫn NOT_EVALUATED; chưa có GT độc lập.

## Phát hiện mới

- `src/ocr_document/validation.py` import lười `benchmark.accuracy_first` (dòng 326). Contract chính không thấy vì `benchmark` là gói external. Sửa sẽ đổi closure extraction.
- Docling `FAILED_FALLBACK` tạm thời: 3/938 trang ở V8-006, thêm ACL trang 23 ở smoke V8-033. Worker chết không có traceback, client không ghi mã thoát; log pha ở `.cache/v62-jobs/<generation>` bị run cùng identity ghi đè (V8-120).
- Bash heredoc và Write tool đổi chuỗi thoát (`\\n`, `\u…`). Khi patch file có backslash, dùng `chr()`.

## Bằng chứng trước phiên: giữ nguyên, chưa đo lại

QA-02 registry offline, dọn dẹp 06/11, Global Alias v1 86/86, GAP-03/DC-01/DC-02/TAB_05: xem [HANDOFF trước phiên](../../scratch/dev_sessions/20261109-v8-metric-keyword-challenger/handoff-before.md).

## Giới hạn và bước kế tiếp

User xác nhận không có người A/B; không dùng AI hay protocol làm GT. GT, split, protocol và ngưỡng còn thiếu.

1. Sau khi người dùng duyệt commit: khóa mới và chạy dự đoán 938 trang cho mã có V8-033.
2. V8-120: ghi mã thoát worker Docling và giữ log theo output (đổi `src/`). V8-030 cần GT để đo fix/harm.
3. Khi batch chạy, không sửa `src/`. V8-013, V8-170: người dùng chọn.

Đổi trạng thái thì sửa registry, chạy `--render` rồi `--check`. Commit khi người dùng duyệt.
