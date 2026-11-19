# Hồ sơ chọn candidate V8-140 (bản 4, 19/11/2026)

Hồ sơ so candidate end-to-end với baseline theo `05_HOP_DONG_BENCHMARK_ADAPTER.md` §5. Operator đề xuất; người duyệt (VuTuanAn1403) đã chốt `Q15 A`, `Q16 B`, `Q17 A`, `Q18 A`, `Q19 A` ngày 19/11/2026. Chất lượng tổng thể vẫn giữ `NOT_EVALUATED` khi thiếu GT độc lập đầy đủ.

## Candidate 1: nhóm sửa bất biến dữ liệu (004 / 006)

- **Output:** `003` (`BASELINE-V8-20261109-003`) → `004` (`BASELINE-V8-20261112-001`, 9/9 `MATCH`, `84a023d38f1ffe4b`) → `006` (`BASELINE-V8-20261113-001`, Q1 chọn làm baseline). Pha A trùng hệt: 64.387 dòng nguồn có cùng `source_id`, chữ và bbox.
- **Sửa:** (1) đặc tả 13 §4.1 ghi `rejected_ocr_lines` vào `extraction.json` và gói review; (2) V8-080 ô bảng heuristic mang bbox dòng nguồn, không sửa số; (3) một dòng khớp cả bảng heuristic lẫn đúng một bảng model thì bảng model nhận dòng đó.

| Thước đo (dev, 9 PDF, 938 trang) | Baseline `003` | Candidate `004` | Hiện vật (`scratch/v8/…`) |
| --- | ---: | ---: | --- |
| Dòng nhận dạng vắng khỏi extraction (§4.1) | 3.652 | 0 (3.652 giữ review) | `v8_140_invariants_003_vs_004_20261112.json` |
| Ô số không truy được nguồn / lặp bbox | 292 / 315 | 2 / 0 | như trên |
| Ô số thiếu ánh xạ nguồn (heuristic / TableFormer) | 453 / 1.310 | 323 / 1.193 | như trên |
| Dòng vừa trong bảng vừa ở thân văn bản | 333 | 0 | `v8_080_dispositions_003_vs_004_20261112.json` |
| DSER khóa v7 (7 PDF) / keyword (9 PDF) / đổi số | 13.751 / — / 0 | 13.751 / 0 đổi / 0 | `v8_011_measurement_dev_00{3,4}_v7_20261112.json` |

Khác biệt 69 dòng ngoài mã thuộc các trang Docling crash `0xC0000005` (fallback giữ chữ pha A). Đề xuất: sửa đúng mọi bất biến đo được, 0 harm; dùng `006` làm baseline, chờ quyết định `PROMOTE` tại Q15.

## Candidate 2: phóng dòng ×2 trước VietOCR (V8-050)

- **Lượt 1 (12/11, arena 1024 MB, `005`):** 6 PDF dev `1.208` sửa / `258` sai (`11.046 → 9.743`), keyword `3/0`, bất biến `2 → 2`; nhưng AAA lỗi ONNX BFC arena 3/3 lần ở tr.21 (`REJECT`, `v8_005_upscale2_batch_20261112.log`). Nâng arena `1024 → 1536 MB` (`4274a49`) rồi chạy lại cả hai bên.
- **Lượt 2 (13/11 dev & 18/11 holdout, arena 1536 MB):** `006` (`20261113-001`) vs `007` (`20261113-002`, `config/candidates/v8_050_line_upscale2.yaml`), 9/9 dev & 6/6 holdout `MATCH` (`h01` vs `h02`). Nâng arena không đổi pha A hay keyword của `006` (`v8_050_arena_dispositions_004_vs_006_20261112.json`).

| Thước đo (chưa phân xử mù; tham chiếu text layer) | `006` / `h01` | `007` / `h02` (`×2`) | Hiện vật (`scratch/v8/…`) |
| --- | ---: | ---: | --- |
| Dev DSER khóa v7 (7 PDF, `345.300` slot) | 13.751 | 11.647 (`6.307→5.032` đơn vị) | `v8_011_measurement_dev_00{6,7}_v7_20261113.json` |
| Dev DSER đơn vị (`v8`) / keyword (9 PDF) | 13.777 / — | 11.671 (`1.780` sửa / `307` sai) / `3` sửa, `0` sai | `v8_050_upscale2_e2e_dser_006_vs_007_v8_20261113.json` |
| **Holdout 4 PDF `ACCEPTED` (`93.481` slot, khóa `holdout_v8`)** | **`3.183`** (`0,03405`) | **`2.581`** (`0,02761`, `448` sửa / `63` hại) | `holdout/v8_011_measurement_holdout_h02_upscale2_20261118.json` |
| Holdout `DER_VN_v1` / đơn vị phân xử | `5.240` / `1.590` | `4.864` / `1.247` | `holdout/v8_050_holdout_dser_cer_h01_vs_h02_20261118.json` |
| Holdout CER (`317.262` ký tự chung) / kw (`292`p) | `18.989` / `1` thiếu, `1` thừa | **`18.611`** / `1` thiếu, `1` thừa (`0` hại) | `holdout/v8_100_holdout_keywords_h01_vs_h02_20261118.json` |
| Holdout V8-030 acronym (`h01` vs `h02`) | `3.183→3.117` (`58/1`) | `2.581→2.581` (`1/1`) | `holdout/v8_030_acronym_holdout_h02_20261118.json` |

## Candidate 3: VLM Vintern-1B-v3.5 cho trang khó (V8-090, 12/11)

- `EXP-V8-VLM-20261112-002`: đọc 137/137 trang chọn trên `004`, gắn `review_required`. Trên 90 trang text layer dev: DSER VLM `4.647` vs production `1.606` (tốt hơn 33p, kém 43p, ngang 14p, `v8_090_vintern_pages_004_20261112.json`). Người duyệt chốt Q4 A: **`KEEP BASELINE`**.

## Candidate 4: VietOCR `vgg_transformer` (V8-065, 15/11–18/11)

- **Identity:** `480285b → 1a6864c`, `v8_065_vgg_transformer.yaml`, `runtime-models-v8-065-vgg-transformer.json`, khóa `BASELINE-V8-20261115-002` (`MATCH` 9/9 dev `938`p & 6/6 holdout `h03` `468`p).

| Thước đo (`NOT_EVALUATED` khi chưa phân xử mù) | `006` / `h01` | `065` / `h03` (`vgg_transformer`) | Hiện vật (`scratch/v8/…`) |
| --- | ---: | ---: | --- |
| Dev `DSER_strict` (`v8`, 7 PDF, `346.393` slot) / `rho` | `13.777` / `0,0222` | `5.158` (`adj 4.009`) / `0,0139` | `v8_011_measurement_dev_065_vgg_transformer_v8_20261115.json` |
| Dev V8-030 (text layer / đã seal 18/11) | `13.802→13.453` (`278/5`) | `5.158→4.800` (`271/2`) | `v8_030_acronym_adjudicated_dev_006_v8_20261118.json` |
| Dev V8-080 phiếu 72 số (`in_table`/`visible`/`absent`) | `6 / 52 / 0` | `24 / 22 / 12` | `v8_080_table_numbers_065_vgg_transformer_20261115.json` |
| Dev V8-140 `EXTRACTED`/`LOW_CONF`/thiếu bảng/`untraced` | `10.497`/`3.005`/`67`/`2` | `27.017`/`849`/`207`/`4` | `v8_065_vgg_transformer_invariants_006_vs_dev_20261115.json` |
| Dev V8-071 thứ tự đọc / V8-100 `--analysis-from` | `0,951` / `156` kw | `0,951247` / `v1=170, v2=159` | `v8_071_reading_order_065_…`, `v8_100_065_analysis_pending_audit_…` |
| **Holdout 4 PDF `ACCEPTED` (`93.481` slot, khóa `holdout_v8`)** | **`3.183`** (`0,03405`) | **`969`** (`0,01037`, `879` sửa / `148` hại) | `holdout/v8_011_measurement_holdout_h03_vgg_transformer_20261118.json` |
| Holdout `DER_VN_v1` / đơn vị phân xử / V8-030 | `5.240` / `1.590` / `58-1` | `3.085` / `790` / `969→911` (`50/1`) | `holdout/v8_030_acronym_holdout_h03_20261118.json` |
| Holdout CER (`317.710` ký tự chung) / kw (`292`p) | `18.956` / `1` thiếu, `1` thừa | **`10.229`** / `2` thiếu, `1` thừa (`harmed=1`) | `holdout/v8_065_holdout_dser_cer_h01_vs_h03_20261118.json` |

## Đánh giá GT cấu trúc 9 PDF & Layout candidate (18–19/11)

Chuẩn hóa 9 file `output/labels-*-2026-11-18*.json` → `normalized_labels_20261119/` (`numeric_cells_complete=true` & `html_numeric_cells`) → 9 `scratch/gt/<DOC>.structure.json`, chạy `run_v8_evidence_chain.py --run` (`20261119-210438`, `35/35` exit 0) & `V8-071` `AAA` comparison:

| Hạng mục GT | Phạm vi | `006` (baseline) | `007` (`×2`) | `065` (`vgg_transformer`) | Candidate khác |
| --- | --- | ---: | ---: | ---: | --- |
| **V8-060** Dòng chữ (`PP-OCRv6`) | 33 trang | `TP=597, FP=1.759, FN=842` (`F1=0,3146`) | `0,3146` (chung detector) | `0,3146` (chung detector) | — |
| **V8-080** Bảng (`TEDS` / struct) | 23p, 43 bảng | `0,6054` / `0,7101` (`39/43` khớp) | `0,6077` / `0,7152` | `0,6085` / `0,7162` | — |
| **V8-080** Ô số (`numeric_cells`) | 9 PDF, `1.255` ô | `F1=0,4192` (`bag 0,6542`) | `F1=0,4323` (`bag 0,6614`) | `F1=0,4165` (`bag 0,6837`) | Exact địa chỉ ô `(row, col)` |
| **V8-070** Bố cục (`layout_candidate.json`) | 43 trang | `TP=54, FP=1.962, FN=192` (`F1=0,0477`) | — | `F1=0,0553` (`55/1.689/191`) | **`PP-DocLayout_plus-L` `TP=85, FP=470, FN=161` (`F1=0,2122`, `16` sửa / `1` hại)** |
| **V8-071** Thứ tự đọc (`AAA`, `reviewed_spans`) | 4p, `24` node/`19` cặp | prod `0,7143` (pen `0,5263`) | prod `0,7143` (pen `0,5263`) | **prod `1,0000` (pen `0,5789`)** | Challenger `006=0,6429`, `065=0,8182` (`KEEP BASELINE`) |

## Bảng quyết định V8-140 — ĐÃ CHỐT VÀ TÍCH HỢP `8.0.0` (19/11/2026)

| Mã | Candidate | Bằng chứng & Chẩn đoán bổ sung | Quyết định đã chốt (VuTuanAn1403) | Trạng thái tích hợp |
| --- | --- | --- | --- | --- |
| **Q15** | **C1: Bất biến dữ liệu (`006` + Q6 B/Q7 A)** | 0 harm dev/holdout; giữ dòng bị loại & sheet chờ duyệt; bỏ mất dòng `3.652→0` | **A: `PROMOTE`** | Đã hợp nhất ở `1a6864c` |
| **Q16** | **C2: Phóng dòng `×2` (`V8-050`)** | Holdout `DSER 3.183→2.581`; giữ tách riêng để đo gộp `vgg_transformer + ×2` sau | **B: `HOLD`** | Tắt mặc định (`line_upscale=1`), giữ `v8_050_line_upscale2.yaml` |
| **Q17** | **C4: `vgg_transformer` (`V8-065`)** | Holdout `DSER 3.183→969`, CER `18.956→10.229`, dev kw missing `28→16` (sau review `14→6`). Audit `v8_065_table_number_absent_audit_20261119.json`: 12/17 `absent` ở chart `BCE p18`; 3 ca `ASM`/`BHN` là `065` sửa đúng trong `blocks`; 2 `NOT_PRINTED` hết ảo giác; `missing_from_table 67→207` do `image_table 44→103` & 2 bảng 1-ô `BHN p66/p63` (`96` block còn nguyên) | **A: `PROMOTE` kèm rà soát** | Mặc định ở `profiles.yaml` & `runtime-models.json` (`7745704`) |
| **Q18** | **C5: `PP-DocLayout_plus-L` (`V8-070`)** | GT 43p `F1 0,0477→0,2122` (`16` sửa/`1` hại, FP `1.962→470`) | **A: `PROMOTE`** | `PaddleDetrLayoutAdapter` (`paddle_detr`), ONNX Pha A, giữ Heron cho Pha B |
| **Q19** | **Phát hành `8.0.0` (`V8-160`)** | Cổng dấu 99,99% holdout vẫn **`FAIL`** (`1,037% > 0,01%`, chất lượng giữ `NOT_EVALUATED`); tích hợp kỹ thuật `8.0.0` & 38/38 backlog `DONE` | **A: `PROMOTE 8.0.0`** | `PIPELINE_VERSION = "8.0.0"`, commit `7745704`, smoke `output/v8_160_release_800_smoke_20261119` (`PASS`), khóa `BASELINE-V8-20261119-002` (`LOCKED`) |
