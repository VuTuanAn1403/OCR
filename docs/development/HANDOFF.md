# Bàn giao

Cập nhật 10/11/2026 rạng sáng, Asia/Bangkok. Nhánh `v8-diacritic-bounds-keyword-challenger`, PR [#1](https://github.com/VuTuanAn1403/OCR/pull/1); các commit tới `bfd78c8` đã push. Không phiên nào sửa `src/`, nên OCR identity vẫn khớp khóa `BASELINE-V8-20261109-003` (extraction `ccdbe84a3691d645`, detector v6). Trạng thái: skill `ocr-pdf-knowledge-map` hoặc `scripts/check_knowledge_map.py --summary`. Nhật ký: [10/11 công cụ](../../scratch/dev_sessions/20261110-v8-goal-tools/session.md), [V8-060](../../scratch/dev_sessions/20261109-v8-060-detector/session.md), [P1 khóa GT](../../scratch/dev_sessions/20261109-v8-p1-gt-lock/session.md).

## 10/11: công cụ GT, challenger và kiểm bất biến

Mục tiêu người dùng giao là đưa đủ 38 mục backlog lên `DONE`. Mục nào cần GT do người tạo hay quyết định của người dùng thì giữ `IN_PROGRESS`/`TODO`; không mục nào được đánh `DONE` khi thiếu bằng chứng.

- **P1 (V8-011/012):** `text_layer_reference.py` (lọc glyph hiển thị), `screen_text_layer.py` (phiếu sàng lọc, seal, kiểm lại mù), `measure_text_layer_diacritics.py` (ghép bbox, cổng `DSER_strict`), `adjudicate_text_layer_diacritics.py` (phân xử mù A/B), `cluster_correlation.py` (ρ_U beta-binomial; cận F của ANOVA chỉ phủ 58–89% trong mô phỏng). 7 phiếu sàng lọc đã dựng ở `scratch/v8/screening/*_v1_20261109/index.html`. Protocol §7.6 ghi các lựa chọn chờ khóa v2. Công cụ `lock_text_layer_measurement.py` (10/11) ghim 9 công cụ đo; đo và phân xử từ chối khi chưa có khóa v2 `LOCKED_PROCEDURE`. Nháp chờ duyệt: `scratch/v8/v8_011_measurement_lock_v2_draft_20261110.json` (`ea51ae6e…`, còn mở luồng đo).
- **V8-150 `DONE`:** `label_structured_gt.py` cùng phiếu HTML gán nhãn detection, layout, thứ tự đọc, bảng; xuất `structured-page-gt-v1`, và scorer đọc được file xuất.
- **V8-120 `DONE`:** `summarize_batch_operations.py` trên soak khóa 003: p50 6,57 s/trang, VRAM đỉnh 2.673/4.096 MiB, 2 lần chạy lại đều phục hồi.
- **Quyết định 10/11 của người dùng:** bỏ 18 test harness `Test case/` (V8-170 `DONE`); "B2B2C" tính một lần B2B và một lần B2C như `literal_v1` (V8-100, sửa đặc tả 13); lỗi §4.1 ghi nhận, sửa sau.
- **Hồi quy CPU tại `1ebba74`:** 2.610 passed, 19 skipped (`scratch/runs/20261110-010839-9d80fdb1`); sau khi bỏ test harness, `tests/scientific` 657 passed, 0 skipped. Tại `21f3cb3`: 2.612 passed, 1 skipped (`scratch/runs/20261110-013831-8339d788`).
- **`IN_PROGRESS` có số liệu, chưa có GT:**
  - V8-071: thứ tự đọc R-RO-01..08, đồng thuận cặp 0,951.
  - V8-090: adapter VLM; 137/938 trang được chọn; Vintern-1B-v3.5 đã ghim, chưa chạy.
  - V8-080: kiểm bất biến đặc tả 13.
  - V8-100: `literal_v2` cho 148 so với 156; 8 khác biệt đều là "B2B2C" ở VIC.

## 09/11: V8-060 và khóa P1

- EXP-V8-DET-20261109-002 (9/9 PDF): đồng thuận v4/v6 IoU 0,811; text layer chưa xác minh v4 H 0,825, v6 H 0,838; chỉ được `INCONCLUSIVE`. AAA hết arena ONNX ở 1/2 lần chạy.
- Khóa quy trình text layer v1 (`b0c20a84…`); 9 PDF `inputs/` là development; người dùng là người duyệt kiêm custodian.

## Phát hiện còn mở

- Đặc tả 13 §4.1: 3.652 khối chữ trong ảnh bị pha A loại (confidence thấp, ảo giác) chỉ còn trong `pages/*.json`, không vào `extraction.json` (671/938 trang). Sửa phải đổi `src/` và identity.
- Bảng (audit v2, bản r1 báo nhầm 2.296 ô do đối chiếu `evidence_blocks`):
  - Bảng heuristic chép bbox của ô đầu hàng cho cả hàng: 315/513 ô có số; 453 ô thiếu ánh xạ nguồn. Lỗi nằm ở `src/ocr_structure/document_layout_engine.py:661` (`bbox=r[0].bbox`). Cùng hàm còn sửa chữ số "12…HDPE" thành "D…" (dòng 646–647) và bỏ ô đầu "0"/"-" (dòng 651–652).
  - Trên toàn bộ bảng, 292/17.259 ô có số không truy được; 287 ô trong số đó thuộc lỗi bbox trên.
  - 67 số của dòng OCR nằm trong ô nhưng không có ở ô nào của bảng. Cần xem bằng mắt.
- Cổng cũ (`diacritic_acceptance.py`, `release_gate.py`) đếm lỗi DER_VN_v1, trong khi khóa ghi `DSER_strict`.
- `src/ocr_document/validation.py` import lười `benchmark.accuracy_first`; `runtime-models.json` ghi nhầm `V8-065`.

## Bước kế tiếp (cần người dùng)

1. Duyệt nháp khóa v2 (§7.6), chọn `text_corrected` hay `text_raw`, rồi khóa bằng `lock_text_layer_measurement.py --stream --reviewer --decided-on`; sau đó sàng lọc 7 PDF bằng phiếu đã dựng → seal → đo → phân xử.
2. Gán nhãn GT bằng `label_structured_gt.py`: detection (V8-060), layout/thứ tự đọc (V8-070/071), bảng (V8-080); ưu tiên worklist trong các báo cáo V8-060/071.
3. Khi muốn sửa lỗi §4.1: đổi `src/`, khóa baseline mới và chạy batch mới.
4. VLM: Vintern-1B-v3.5 đã ghim (revision `b98f263e`, cần `trust_remote_code`); bạn tự tải, xem mã repo và chạy theo [`vlm/README.md`](../../benchmark/challengers/vlm/README.md). Recognizer, layout, parser (V8-065/070/095) chưa ghim.
5. Push các commit mới khi người dùng duyệt.
