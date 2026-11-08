# Bàn giao

Cập nhật 09/11/2026, Asia/Bangkok. Gốc `08f7602`, chưa push. Mọi thay đổi **chưa commit**. Trạng thái: skill `ocr-pdf-knowledge-map` hoặc `scripts/check_knowledge_map.py --summary`. [Phiên 09/11](../../scratch/dev_sessions/20261109-v8-metric-keyword-challenger/session.md); [HANDOFF trước phiên](../../scratch/dev_sessions/20261109-v8-metric-keyword-challenger/handoff-before.md).

## 09/11: metric dấu, keyword, challenger (theo `cai tien v2`)

- **V8-020..022** (benchmark):
  - `ocr_metric.py::compute_dser_strict_detailed` báo `DSER_strict` song song `DER_VN_v1` trên cùng căn chỉnh.
  - `exact_bounds.py` có cận Clopper-Pearson; bảng cỡ mẫu của đặc tả 04 tái tạo đúng.
  - Khi 0 lỗi: cận chính xác trên N_eff, cần `design_effect` đã khóa.
  - Cổng OCR `release_gate.py::_ocr_diacritic_bound_gate` dùng cận trên thay ước lượng điểm.
- **V8-031**: `alias_map.py::find_single_word_variants` liệt kê keyword một từ sai dấu trong `keyword_two_tier.json` (`single_word_variants`), không cộng vào số đếm.
- **V8-032**: challenger `literal_v2` trong `counter.py`; sản phẩm vẫn `literal_v1`. `scripts/compare_keyword_policies.py` báo chênh lệch; chạy thật chờ extraction V8-006.
- **V8-033**: lỗi regex "cổ ông" đã tái hiện (5 xfail strict). Chưa sửa vì đổi closure extraction.
- **V8-040/041/043**:
  - `benchmark/challengers/` có experiment_id, manifest identity, output canonical và catalog với cổng tải (0/8 ứng viên được tải).
  - Contract riêng `benchmark/challengers/importlinter.toml` cấm production và evaluator import challenger.
- **V8-110** ánh xạ E01–E13 vào `ERROR_TAXONOMY.md`. **V8-012**: `scripts/inventory_diacritic_slots.py` tái lập 1.788 slot CLW. **V8-170**: harness thiếu thì skip (18).
- **Nguồn đã xóa**: người dùng xóa 3 tài liệu nguồn trong `cai tien v2/`. Registry ghi `git_preserved` = `08f7602`, và trình kiểm xác minh sha qua `git cat-file`.
- **Khóa baseline mới** `BASELINE-V8-20261109-001` LOCKED, vì `src/ocr_keywords` đổi. Extraction `20e15efae22917bd` không đổi, `ocr_identity` 9 PDF trùng khóa 20261108-001.
- **V8-006 đang chạy**: `run_batch.py --input inputs --output output/v8_baseline_20261109`, log `scratch/v8/v8_006_baseline_run_20261109.log`. Nếu bị ngắt, chạy lại với `--resume`.

## Kiểm tra đã chạy

- Hồi quy CPU unit/scientific/legacy: 2459 passed, 19 skipped, 5 xfailed, 0 lỗi ([run](../../scratch/runs/20261109-015750-6e8c57d7/run.json)). Sửa sau lúc run bắt đầu đã chạy lại: 453 passed, 5 xfailed ([run](../../scratch/runs/20261109-020734-d25fcf73/run.json)).
- `lint-imports` (pyproject) và contract challengers: kept. `check_knowledge_map.py --check`: 0 lỗi.
- Quality vẫn NOT_EVALUATED; chưa có GT độc lập.

## Phát hiện mới

- `src/ocr_document/validation.py` import lười `benchmark.accuracy_first` (dòng 326). Contract chính không thấy vì `benchmark` là gói external. Sửa sẽ đổi closure extraction.
- Bash heredoc và Write tool đổi chuỗi thoát (`\\n`, `\u…`). Khi patch file có backslash, dùng `chr()`.

## Bằng chứng trước phiên: giữ nguyên, chưa đo lại

QA-02 registry offline, dọn dẹp 06/11, Global Alias v1 86/86, GAP-03/DC-01/DC-02/TAB_05: xem [HANDOFF trước phiên](../../scratch/dev_sessions/20261109-v8-metric-keyword-challenger/handoff-before.md).

## Giới hạn và bước kế tiếp

User xác nhận không có người A/B; không dùng AI hay protocol làm GT. GT, split, protocol và ngưỡng còn thiếu.

1. V8-006: khi batch xong, chạy `scripts/audit_batch_outputs.py --output output/v8_baseline_20261109 --report scratch/<moi>.json --validate`, rồi `scripts/check_baseline_identity.py --lock scratch/benchmarks/BASELINE-V8-20261109-001/baseline_lock.json --output output/v8_baseline_20261109 --report scratch/<moi>.json`.
2. Trên extraction đó: V8-032 (`compare_keyword_policies.py`), rồi V8-033 và V8-030 trên output mới.
3. V8-013: người dùng chọn nguồn GT. V8-170: chọn phương án cuối cho harness.
4. V8-042: gỡ `src.ocr` khỏi `matrix_runner` và `perf`.

Đổi trạng thái thì sửa registry, chạy `--render` rồi `--check`. Commit khi người dùng duyệt.
