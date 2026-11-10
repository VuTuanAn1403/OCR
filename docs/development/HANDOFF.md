# Bàn giao

Cập nhật 10/11/2026, Asia/Bangkok. Nhánh `v8-diacritic-bounds-keyword-challenger`, PR [#1](https://github.com/VuTuanAn1403/OCR/pull/1). Đã push tới `bfd78c8`; các commit sau chưa push. Không phiên nào sửa `src/`, nên OCR identity vẫn khớp khóa `BASELINE-V8-20261109-003` (extraction `ccdbe84a3691d645`). Trạng thái: skill `ocr-pdf-knowledge-map` hoặc `scripts/check_knowledge_map.py --summary`. Nhật ký: [10/11](../../scratch/dev_sessions/20261110-v8-goal-tools/session.md), [V8-060](../../scratch/dev_sessions/20261109-v8-060-detector/session.md), [P1](../../scratch/dev_sessions/20261109-v8-p1-gt-lock/session.md).

## 10/11

Mục tiêu: đưa 38 mục backlog lên `DONE`. Mục nào cần GT do người tạo hoặc cần người dùng quyết thì giữ `IN_PROGRESS`/`TODO`; không có bằng chứng thì không đánh `DONE`.

- **P1 sàng lọc (V8-011):** ngày 10/11 người dùng sàng lọc 7 PDF; cả 7 `ACCEPTED` (24.172 slot `MATCH`, 0 `MISMATCH`), seal ở `scratch/v8/screening/sealed/`. 6 PDF được chấm trong 3–6 phút mỗi PDF, chủ yếu bằng MATCH cả dòng. Kiểm lại mù 1.552 chữ làm từ 17/11 (`scratch/v8/screening/recheck/`).
- **P1 đo dev (V8-012):** `scratch/v8/v8_011_measurement_dev_003_20261110.json` (identity MATCH, khóa v1+v2) cho 83.127/345.300 lỗi. 71.884/78.192 slot bị xóa là chữ trong bảng, do quy tắc ghép §7.6 mục 3 chỉ dùng item `b`, nên số này không phải độ chính xác. Chờ khóa v3: ghép với `text_evidence` và ghi sha256 seal.
- **Khóa v2 §7.6 `LOCKED` 10/11, người dùng duyệt:** `docs/quality_assurance/locks/v8_011_text_layer_measurement_lock_v2.json` (`a0dc5712…`), luồng đo `text_corrected`. Khóa ghim 10 công cụ đo; khâu đo và phân xử từ chối chạy nếu khóa không còn khớp.
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

1. Duyệt khóa v3 (quy tắc ghép mới, §7.6), rồi đo lại và phân xử. Kiểm lại mù từ 17/11.
2. Xem 72 mục của phiếu số trong bảng, xuất JSONL, rồi `build_table_number_review.py seal`.
3. Gán nhãn GT bằng `label_structured_gt.py` cho V8-060/070/071/080.
4. Chạy Vintern theo [`vlm/README.md`](../../benchmark/challengers/vlm/README.md); V8-065/070/095 chưa ghim ứng viên.
5. Quyết định thời điểm sửa các lỗi `src/` (§4.1, bảng heuristic), và push.
