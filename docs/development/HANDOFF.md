# Bàn giao

Cập nhật 10/11/2026, Asia/Bangkok. Nhánh `v8-diacritic-bounds-keyword-challenger`, PR [#1](https://github.com/VuTuanAn1403/OCR/pull/1). Đã push tới `bfd78c8`; các commit sau chưa push. Không phiên nào sửa `src/`, nên OCR identity vẫn khớp khóa `BASELINE-V8-20261109-003` (extraction `ccdbe84a3691d645`). Trạng thái: skill `ocr-pdf-knowledge-map` hoặc `scripts/check_knowledge_map.py --summary`. Nhật ký: [10/11](../../scratch/dev_sessions/20261110-v8-goal-tools/session.md), [V8-060](../../scratch/dev_sessions/20261109-v8-060-detector/session.md), [P1](../../scratch/dev_sessions/20261109-v8-p1-gt-lock/session.md).

## 10/11

Mục tiêu: đưa 38 mục backlog lên `DONE`. Mục nào cần GT do người tạo hoặc cần người dùng quyết thì giữ `IN_PROGRESS`/`TODO`; không có bằng chứng thì không đánh `DONE`.

- **P1 (V8-011/012):** đã có công cụ sàng lọc, đo ghép bbox, phân xử mù A/B và ρ_U (protocol §7.5). 7 phiếu sàng lọc nằm ở `scratch/v8/screening/*_v1_20261109/`.
- **Khóa v2 §7.6:** `lock_text_layer_measurement.py` ghim 9 công cụ đo; khâu đo và phân xử từ chối chạy khi chưa có khóa `LOCKED_PROCEDURE`. Bản nháp: `scratch/v8/v8_011_measurement_lock_v2_draft_20261110.json` (`ea51ae6e…`), còn mở luồng đo.
- **V8-150, V8-120, V8-170 `DONE`:** công cụ gán nhãn trực quan; soak khóa 003 (p50 6,57 s/trang, VRAM đỉnh 2.673 MiB); bỏ 18 test harness.
- **Quyết định của người dùng:** "B2B2C" tính như `literal_v1`; lỗi §4.1 ghi nhận, sửa sau.
- **V8-080, audit v2:** bản r1 đối chiếu nhầm `evidence_blocks` nên báo 2.296 ô. Bản đúng là `scratch/v8/v8_080_runtime_invariants_003_r2_20261110.json`.
- **Cổng dấu:** `diacritic_acceptance.py` và `release_gate.py` nay đếm lỗi theo `DSER_strict` (đặc tả 04 §3). Trước đây chúng đếm theo DER_VN_v1.
- **Phiếu xem số trong bảng:** `build_table_number_review.py` dựng `scratch/v8/table_review/v8_080_table_numbers_003_v1_20261110/index.html`, gồm 72 mục (67 số mất khỏi bảng, 5 số không truy được) trên 16 trang.
- **Hồi quy CPU sau khi đổi cổng dấu:** 2.625 passed, 1 skipped (`scratch/runs/20261110-055532-c9926228`).
- **`IN_PROGRESS` có số liệu, chưa có GT:**
  - V8-071: đồng thuận cặp 0,951.
  - V8-090: 137/938 trang được chọn; Vintern-1B-v3.5 đã ghim, chưa chạy.
  - V8-100: `literal_v2` cho 148 so với 156 (8 khác biệt đều là "B2B2C").
  - V8-060: IoU v4/v6 0,811, kết luận `INCONCLUSIVE`.

## Phát hiện còn mở

- **Đặc tả 13 §4.1:** 3.652 khối chữ trong ảnh bị loại vắng khỏi `extraction.json`, kể cả `text_evidence` (671/938 trang).
- **Bảng heuristic:**
  - `src/ocr_structure/document_layout_engine.py:661` gán `bbox=r[0].bbox` cho mọi ô của hàng: 315/513 ô có số mang bbox lặp, 453 ô thiếu ánh xạ nguồn.
  - Cùng hàm sửa "12…HDPE" thành "D…" (dòng 646–647) và bỏ ô đầu "0"/"-" (dòng 651–652).
  - Trên toàn bộ bảng có 292/17.259 ô mang số không truy được; 287 ô trong đó do bbox lặp.
- **Lỗi nhỏ:** `src/ocr_document/validation.py` import lười `benchmark.accuracy_first`; `runtime-models.json` ghi nhầm `V8-065`.
- Sửa các lỗi `src/` ở trên là đổi identity: cần khóa baseline mới và chạy batch mới.

## Bước kế tiếp (cần người dùng)

1. Duyệt nháp khóa v2 và chọn `text_corrected` hay `text_raw`, rồi khóa: `lock_text_layer_measurement.py --stream --reviewer --decided-on`. Sau đó sàng lọc 7 PDF → seal → đo → phân xử.
2. Xem 72 mục của phiếu số trong bảng, xuất JSONL, rồi `build_table_number_review.py seal`.
3. Gán nhãn GT bằng `label_structured_gt.py` cho V8-060/070/071/080.
4. Chạy Vintern theo [`vlm/README.md`](../../benchmark/challengers/vlm/README.md); V8-065/070/095 chưa ghim ứng viên.
5. Quyết định thời điểm sửa các lỗi `src/` (§4.1, bảng heuristic), và push.
