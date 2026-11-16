# Hồ sơ chọn candidate V8-140 (bản 2, 15/11/2026)

Hồ sơ này so từng candidate end-to-end với baseline theo hợp đồng `05_HOP_DONG_BENCHMARK_ADAPTER.md` §5. Operator đề xuất; người duyệt (VuTuanAn1403) quyết. Mọi chất lượng giữ `NOT_EVALUATED` ở nơi chưa có GT độc lập (holdout chưa seal, phân xử chưa xong).

## Identity

| | Baseline | Candidate |
| --- | --- | --- |
| Output | `output/v8_003_baseline_20261109` | `output/v8_004_nosilentdrop_r2_20261112` |
| Khóa | `BASELINE-V8-20261109-003` | `BASELINE-V8-20261112-001` (`scratch/benchmarks/BASELINE-V8-20261112-001/baseline_lock.json`, LOCKED) |
| Mã | HEAD `20207a2` + diff | HEAD `1aef15c` + diff `2a2a58d3…`; fingerprint extraction `84a023d38f1ffe4b` |
| Kiểm identity | 9/9 MATCH | 9/9 MATCH (`scratch/v8/v8_004_identity_20261112.json`) |
| Model, config | PP-OCRv6 det, VietOCR, Docling Heron/TableFormer, `unified_gpu_full_ocr` | không đổi |
| Chạy | 9 PDF, 938 trang, CUDA | 9 PDF, 938 trang, CUDA. AAA lỗi ONNX BFC arena ở trang 56 lần đầu và qua ở lần retry. Audit 9/9 hoàn tất (`scratch/v8/v8_004_r2_batch_audit_20261112.json`) |

Candidate chỉ đổi mã hậu kỳ. Pha A (OCR) trùng hệt trên mọi trang: 64.387 dòng nguồn có cùng `source_id`, chữ và bbox. Thay đổi:

1. Đặc tả 13 §4.1: dòng bị cổng A1 loại được ghi vào `extraction.json` (`rejected_ocr_lines`) và vào gói review.
2. V8-080: ô bảng heuristic mang bbox của dòng nguồn. Chữ trong ô không bị viết lại. Token bị bỏ được ghi lại.
3. Một dòng khớp cả bảng heuristic lẫn đúng một bảng model thì bảng model nhận dòng đó.

## Fix/harm (development, 9 PDF; không phải accuracy)

| Thước đo | Baseline | Candidate | Hiện vật |
| --- | --- | --- | --- |
| Dòng nhận dạng không có trong extraction (§4.1) | 3.652 | 0 (3.652 giữ để review) | `scratch/v8/v8_140_invariants_003_vs_004_20261112.json` |
| Ô có số không truy được nguồn | 292 | 2 (cả hai TableFormer) | như trên |
| Ô số heuristic lặp bbox ô trước | 315 | 0 | như trên |
| Ô số heuristic thiếu ánh xạ nguồn | 453 | 323 | như trên |
| Ô số TableFormer thiếu ánh xạ nguồn | 1.310 | 1.193 | như trên |
| Dòng nguồn vừa nằm trong bảng vừa bị trả về thân văn bản | 333 | 0 (`KEPT_FOR_REVIEW→REPLACED_BY_TABLE`) | `scratch/v8/v8_080_dispositions_003_vs_004_20261112.json` |
| Dòng nguồn mất (không hiện, không thuộc bảng) | 0 | 0 | như trên |
| DSER_strict dev, khóa v7, trước phân xử (7 PDF) | 13.751/345.300 | 13.751/345.300, mọi thành phần trùng | `scratch/v8/v8_011_measurement_dev_00{3,4}_v7_20261112.json` |
| Keyword literal (9 PDF) | — | 0 keyword đổi số đếm | `…invariants_003_vs_004…` |
| Số đổi bởi hậu xử lý | 0 | 0 | `scratch/v8/v8_080_runtime_invariants_004_20261112.json` |

Thay đổi không do mã: 69 dòng (57 `REPLACED_BY_TABLE→VISIBLE`, 12 `KEPT_FOR_REVIEW→VISIBLE`). Tất cả nằm ở các trang mà worker Docling crash `0xC0000005` ở một lần chạy mà không crash ở lần kia (003: ABT 1 trang; 004: AAA tr.116, ASM 1 trang). Fallback giữ chữ pha A và gắn review.

45 số của bảng heuristic "vắng khỏi bảng" không phải chữ bị mất. Cả 48 dòng chứa chúng hoặc vẫn ở thân văn bản (41), hoặc thuộc một bảng có đủ các số đó (7). Audit đếm chúng vì ô rỗng của bảng ảnh mang bbox cấp bảng (`table_fallback`).

## Đề xuất

- **Bất biến dữ liệu (§4.1, ownership, numeric guard):** candidate sửa đúng mọi ca baseline vi phạm mà đo được; 0 ca làm sai, kể cả DSER và keyword.
- **Chất lượng OCR:** `INCONCLUSIVE`. Chưa có holdout, chưa có GT keyword, bảng hay detection. Dev chỉ dùng để sửa lỗi.
- Operator đề xuất dùng candidate làm baseline cho các thí nghiệm V8 tiếp theo, thay khóa 003. Quyết định này là của người duyệt. Nó không phải PROMOTE, và không nâng `PIPELINE_VERSION` (V8-160).

## Candidate 2: phóng dòng ×2 trước VietOCR (V8-050, 12/11)

| | Baseline | Candidate |
| --- | --- | --- |
| Output | `output/v8_004_nosilentdrop_r2_20261112` | `output/v8_005_upscale2_20261112` |
| Mã, cấu hình | `7097375`, `recognition_line_upscale` vắng (= 1) | `7097375`, `config/candidates/v8_050_line_upscale2.yaml` (= 2) |
| Khóa | `BASELINE-V8-20261112-001` | `BASELINE-V8-20261112-002` (LOCKED); identity 8/9 MATCH, AAA thiếu (`scratch/v8/v8_005_identity_20261112.json`) |

### Lượt 1 (12/11): giới hạn arena 1024 MB

Mã `7097375` thêm tùy chọn với mặc định tắt. Ở giá trị 1, mã chạy y như `5d8cbb5` (test `tests/unit/recognition/test_line_upscale.py`). Baseline 004 không được chạy lại dưới `7097375`.

| Thước đo (dev, tham chiếu là text layer, không phải GT) | Kết quả | Hiện vật |
| --- | --- | --- |
| DSER theo đơn vị, 6 PDF (AGR ×2, ASM, BCE, BHN, VIC) | 1.208 sửa / 258 sai; lỗi 11.046 → 9.743 trên 273.608 slot; 333 đơn vị không ghép được | `scratch/v8/v8_050_upscale2_e2e_dser_004_vs_005_20261112.json` |
| Keyword literal, 8 PDF | 3 occurrence đổi, cả 3 khớp text layer (3 sửa / 0 sai) | `scratch/v8/v8_050_upscale2_keyword_changes_20261112.json` |
| Bất biến (ô số không truy được, số đổi bởi hậu xử lý) | không đổi (2 → 2; 0 → 0) | `scratch/v8/v8_050_upscale2_invariants_004_vs_005_20261112.json` |
| Vận hành (GPU RTX 2050 4 GB) | AAA lỗi 3/3 lần ở đúng trang 21: ONNX BFC arena của detector hết chỗ. Baseline lỗi ở trang 56 rồi qua khi retry | `scratch/v8_005_upscale2_batch_20261112.log` |

Kết luận lượt 1: ở dạng này candidate là `REJECT` (không chạy được trong giới hạn vận hành). Người dùng chọn nâng giới hạn arena trong manifest (commit `4274a49`, 1024 → 1536 MB). Lượt 2 chạy lại cả hai bên.

### Lượt 2 (13/11): giới hạn arena 1536 MB

| | Baseline | Candidate |
| --- | --- | --- |
| Output | `output/v8_006_arena1536_20261112` | `output/v8_007_arena1536_upscale2_20261112` |
| Khóa | `BASELINE-V8-20261113-001`, 9/9 MATCH | `BASELINE-V8-20261113-002`, 9/9 MATCH |
| Chạy | 9/9 lần đầu, audit exit 0 | 9/9 lần đầu, audit exit 0 (AAA qua) |

Nâng giới hạn không đổi kết quả của baseline. So 004 với 006: pha A trùng hệt, `result.md` trùng ở 8/9 PDF, keyword không đổi, DSER khóa v7 13.751 = 13.751. Chỉ khác ở các trang Docling crash trong lần chạy 004 (`scratch/v8/v8_050_arena_dispositions_004_vs_006_20261112.json`).

| Thước đo (dev, tham chiếu là text layer, không phải GT) | Kết quả | Hiện vật |
| --- | --- | --- |
| DSER khóa v7, 7 PDF đã sàng lọc | 13.751 → 11.647 / 345.300; đơn vị cần phân xử 6.307 → 5.032 | `scratch/v8/v8_011_measurement_dev_00{6,7}_v7_20261113.json` |
| DSER theo đơn vị, 7 PDF | 1.781 sửa / 306 sai; 403 đơn vị không ghép được (báo riêng) | `scratch/v8/v8_050_upscale2_e2e_dser_006_vs_007_20261113.json` |
| Keyword literal, 9 PDF | 3 sửa / 0 sai (khớp text layer) | `scratch/v8/v8_050_upscale2_keyword_changes_006_vs_007_20261113.json` |
| Bất biến | ô số không truy được 2 → 2; dòng bị loại vì confidence thấp 3.005 → 2.939 | `scratch/v8/v8_050_upscale2_invariants_006_vs_007_20261113.json` |

Đề xuất của operator: chất lượng `INCONCLUSIVE`, vì chỉ có dev và chưa có holdout. Candidate cải thiện rõ trên dev và chạy được trong giới hạn vận hành, nên đáng đo trên holdout trước tiên. Chưa phải PROMOTE. Người duyệt quyết.

## Candidate 3: VLM Vintern-1B-v3.5 cho trang khó (V8-090, 12/11)

- Mô hình: revision `b98f263e`, sha weights khớp pin; mã tùy biến đã rà. Model đọc 137/137 trang được chọn trên output 004, 0 trang thiếu (`EXP-V8-VLM-20261112-002`). Bản ghi `review_required`, không thay chữ production.
- 2 trang lặp lại prompt. Trên 90 trang có text layer đã sàng lọc: DSER của VLM 4.647, của production 1.606; VLM tốt hơn ở 33 trang, kém hơn ở 43, ngang ở 14 (`scratch/v8/v8_090_vintern_pages_004_20261112.json`). Thang đo cấp trang chịu ảnh hưởng thứ tự đọc nên chỉ là chẩn đoán.
- Đề xuất của operator: `KEEP BASELINE` (không cải thiện, có harm). Người duyệt quyết.

## Candidate 4: VietOCR `vgg_transformer` (V8-065, 15/11)

| | Baseline (`006`) | Candidate (`V8-065`) |
| --- | --- | --- |
| Dev (9 PDF, 938p) | `output/v8_006_arena1536_20261112` | `output/v8_065_vgg_transformer_dev_20261114` (audit 9/9 `SUCCEEDED`) |
| Holdout `h03` (6 PDF, 468p) | `output/v8_h01_baseline_pairs6_20261113` | `output/v8_h03_vgg_transformer_pairs6_20261115` (`v8_h03_vgg_transformer_audit_20261115.json`) |
| Mã & cấu hình | `c681e87`, `config/profiles.yaml` | Merge `480285b->1a6864c`, `v8_065_vgg_transformer.yaml`, `runtime-models-v8-065-vgg-transformer.json` |
| Khóa & identity | `BASELINE-V8-20261113-001` | `BASELINE-V8-20261115-002` (LOCKED); dev 9/9 & `h03` 6/6 `MATCH` (`v8_065_vgg_transformer_dev_identity_20261115.json`, `v8_h03_vgg_transformer_identity_20261115.json`) |

| Thước đo (dev, chưa phải GT; chất lượng `NOT_EVALUATED`) | `006` | `V8-065` | Hiện vật (`scratch/v8/…`) |
| --- | ---: | ---: | --- |
| `V8-011` `DSER_strict` (khóa `v8`, 7 PDF, `346.393` slot) | `13.777` | `5.158` | `v8_011_measurement_dev_065_vgg_transformer_v8_20261115.json` |
| `V8-011` `der_vn_v1` / đơn vị phân xử / `rho` | `18.426` / `6.306` / `0,0222` | `9.937` / `4.009` / `0,0139` | như trên |
| `V8-030` Acronym challenger | — | `5.158 -> 4.800` (`271` sửa / `2` sai) | `v8_030_acronym_textlayer_v8_065_vgg_transformer_20261115.json` |
| `V8-080` Phiếu 72 số (`in_table`/`visible`/`absent`) | `6 / 52 / 0` | `24 / 22 / 12` | `v8_080_table_numbers_065_vgg_transformer_20261115.json` |
| `V8-140` `EXTRACTED` / `LOW_CONF` / `HALLUCINATION` | `10.497 / 3.005 / 647` | `27.017 / 849 / 867` | `v8_065_vgg_transformer_invariants_006_vs_dev_20261115.json` |
| `V8-140` Thiếu bảng / ô thiếu số / `untraced` / kw | `67 / 620 / 2 / 156` | `207 / 992 / 4 / 170` | như trên (`14` keyword đổi) |
| `V8-071` Thứ tự đọc (938p, tất định, 0 vi phạm) | `mean 0,951` | `mean 0,951247` (`150`p `<0,9`) | `v8_071_reading_order_065_vgg_transformer_20261115.json` |
| `V8-032` & `V8-100` Policy / `--analysis-from` CPU | `156` | `v1=170` vs `v2=159`; `9/9` | `v8_032_keyword_policy_diff_065_vgg_transformer_20261115.json`, `v8_100_065_analysis_pending_audit_20261115.json` |

Đề xuất: `INCONCLUSIVE` / `NOT_EVALUATED` (`065` giảm `dser_errors` dev và tăng `in_table`, nhưng tăng `absent=12` và `numbers_missing_from_table=207`). Chờ seal 6 phiếu holdout `ACCEPTED` để đo `h03`.

## Còn thiếu cho V8-140

- **Phân xử dấu dev `v8` (16/11):** đã seal đủ `9.485/9.485` (7/7 PDF `fully_adjudicated`, `41905355…`): `TEXT_LAYER=9.172`, `OCR=107`, `BOTH_WRONG=205`, `UNRESOLVED=1` (`gt_error_items=312`); `006` `DSER_strict=13.802/346.465` (`0,039837`, `rho=0,023166`); tạo phiếu kiểm lại mù `949` mục từ `23/11`.
- Còn thiếu: seal 6 phiếu holdout (`pairs6`), khóa đo holdout và đo cặp `h01`/`h02`/`h03`; kiểm lại mù (`V8-011`) và GT bảng/RO/keyword (`V8-071`, `V8-080`, `V8-100`).
- Chốt chính sách dòng confidence thấp có chữ thật (VD `VIC` tr.95 `"số hóa tài liệu đào tạo…"`, conf `0,535`, `v8_100_retained_line_keywords_004_20261112.json`).
