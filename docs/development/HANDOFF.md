# Bàn giao

Cập nhật 19/11/2026, Asia/Bangkok. Nhánh `v8-diacritic-bounds-keyword-challenger`, commit mã sạch **`7745704`**, [PR #1](https://github.com/VuTuanAn1403/OCR/pull/1). **`PIPELINE_VERSION = "8.0.0"`**, khóa **`BASELINE-V8-20261119-002`** (`LOCKED`, `code_scope_changes=[]`, `portable_identity` `0a07bdfbe80fc725…`, 37 model, `runtime-models.json` sha `602e75b7…`). Nhật ký: [18–19/11](../../scratch/dev_sessions/20261118-gt-holdout-scoring/session.md) · [14–15/11](../../scratch/dev_sessions/20261114-antigravity-takeover/session.md) · [13/11](../../scratch/dev_sessions/20261113-codex-takeover/session.md).

## Quyết định đã chốt (`Q15–Q19`, 19/11/2026)

- **Q15 A (`PROMOTE` C1 bất biến `006` + Q6 B/Q7 A):** Giữ baseline đã hợp nhất ở `1a6864c`.
- **Q16 B (`HOLD` C2 `×2` `V8-050`):** Giữ tắt `recognition_line_upscale` mặc định; giữ [v8_050_line_upscale2.yaml](../../config/candidates/v8_050_line_upscale2.yaml).
- **Q17 A (`PROMOTE` C4 `vgg_transformer` `V8-065`):** Đặt trong [profiles.yaml](../../config/profiles.yaml) & [runtime-models.json](../../models/v62/runtime-models.json). Kiểm toán 17 `absent` & `missing_from_table=207` ([audit](../../scratch/v8/v8_065_table_number_absent_audit_20261119.json)): 12/17 ở `BCE p18`, 3 ca `ASM`/`BHN` là `065` đọc đúng trong `blocks`, 2 `NOT_PRINTED` hết ảo giác; `missing` do `image_table` (`44→103`) & 2 bảng 1-ô `BHN p66/p63` (`96` block nguyên vẹn).
- **Q18 A (`PROMOTE` C5 `PP-DocLayout_plus-L` `V8-070`):** `PaddleDetrLayoutAdapter` tại [model_adapters.py](../../src/ocr_layout/model_adapters.py), ONNX placement ở [dla_engine.py](../../src/ocr_layout/dla_engine.py) & [phase_text.py](../../src/ocr_workers/phase_text.py); giữ Heron Pha B.
- **Q19 A (`PROMOTE` `V8-160` `8.0.0`):** Nâng `8.0.0`, alias `v7.0`/`v6.3` ở [config.py](../../src/ocr_runtime/config.py). Cổng dấu 99,99% holdout giữ `FAIL` (`1,037% > 0,01%`), `quality` giữ `NOT_EVALUATED`.

## Đã kiểm và trạng thái hoàn thiện 100% lộ trình v8

- **Backlog & Registry (19/11):** [06_BACKLOG_V8.csv](../../cai%20tien%20v2/06_BACKLOG_V8.csv) đạt **`38 DONE, 0 IN_PROGRESS, 0 TODO`**; [10_TRANG_THAI_V8.json](../../cai%20tien%20v2/10_TRANG_THAI_V8.json) **`11/11` pha `DONE`** (`R1, P0–P9`); [CANDIDATE_SELECTION_DOSSIER.md](../../cai%20tien%20v2/bao_cao/CANDIDATE_SELECTION_DOSSIER.md) bản 4; [BASELINE_LOCK_REPORT.md](../../cai%20tien%20v2/bao_cao/BASELINE_LOCK_REPORT.md); DOCX.
- **Hoàn tất 6 hạng mục mở cuối:**
  - `V8-080`: Thêm `html_numeric_cells()` tại [label_structured_gt.py](../../scripts/label_structured_gt.py), tái xuất 9/9 GT (`1.255` ô số), `evidence_chain/20261119-210438` (`35/35` exit 0): `numeric_cells` exact F1 `006=0,4192` (`bag 0,6542`), `007=0,4323` (`0,6614`), `065=0,4165` (`0,6837`).
  - `V8-071`: Chấm `AAA` 4p (`24` node/`19` cặp, `reading_order_reviewed_spans_v1`, [so sánh](../../scratch/v8/v8_071_reading_order_gt_comparison_20261119.json)): prod `006=0,7143`, `065=1,0000` (`pen 0,5789`) > challenger (`KEEP BASELINE`).
  - `V8-100`: Dev 718p ([so cặp](../../scratch/v8/v8_100_dev_keywords_006_vs_065_20261119.json)): `065` giảm thiếu `28→16` (`sau review 14→6`, `16/4`); holdout `missing 1→2`.
  - `V8-011`, `V8-012`, `V8-085`: Đóng `DONE` kỹ thuật kèm kết quả thực (`gate_clustered=FAIL`, `OmniDocBench` CDM `0,2760` + `457` unscorable `NOT_EVALUATED`).
- **Kiểm thử & Smoke `8.0.0`:** GPU smoke `output/v8_160_release_800_smoke_20261119` `PASS` ([audit](../../scratch/v8/v8_160_release_800_smoke_audit_20261119.json)); khóa `20261119-002` `LOCKED`; CPU `2.750 passed, 1 skipped` ([run.json](../../scratch/runs/20261119-193947-538dcca0/run.json)) + `10 passed` (`test_label_structured_gt.py`).

## Lưu ý vận hành sau v8.0.0

- Khi cần đo accuracy nghiệm thu độc lập (cổng 99,99% hoặc sau bổ sung PDF holdout mới), mở quy trình mới dưới nhánh tiếp theo; không sửa kết quả `NOT_EVALUATED`/`FAIL` đã ghi nhận.
