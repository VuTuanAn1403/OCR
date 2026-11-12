# Hồ sơ chọn candidate V8-140 (bản 1, 12/11/2026)

Hồ sơ này so một candidate end-to-end với baseline theo hợp đồng `05_HOP_DONG_BENCHMARK_ADAPTER.md` §5. Operator đề xuất; người duyệt (VuTuanAn1403) quyết. Mọi chất lượng giữ `NOT_EVALUATED`, vì chưa có GT độc lập (holdout).

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

Mã `7097375` thêm tùy chọn với mặc định tắt. Ở giá trị 1, mã chạy y như `5d8cbb5` (test `tests/unit/recognition/test_line_upscale.py`). Baseline 004 không được chạy lại dưới `7097375`.

| Thước đo (dev, tham chiếu là text layer, không phải GT) | Kết quả | Hiện vật |
| --- | --- | --- |
| DSER theo đơn vị, 6 PDF (AGR ×2, ASM, BCE, BHN, VIC) | 1.208 sửa / 258 sai; lỗi 11.046 → 9.743 trên 273.608 slot; 333 đơn vị không ghép được | `scratch/v8/v8_050_upscale2_e2e_dser_004_vs_005_20261112.json` |
| Keyword literal, 8 PDF | 3 occurrence đổi, cả 3 khớp text layer (3 sửa / 0 sai) | `scratch/v8/v8_050_upscale2_keyword_changes_20261112.json` |
| Bất biến (ô số không truy được, số đổi bởi hậu xử lý) | không đổi (2 → 2; 0 → 0) | `scratch/v8/v8_050_upscale2_invariants_004_vs_005_20261112.json` |
| Vận hành (GPU RTX 2050 4 GB) | AAA lỗi 3/3 lần ở đúng trang 21: ONNX BFC arena của detector hết chỗ. Baseline lỗi ở trang 56 rồi qua khi retry | `scratch/v8_005_upscale2_batch_20261112.log` |

Đề xuất của operator: chất lượng `INCONCLUSIVE` (dev). Theo §5 của hợp đồng, candidate **không chạy được trong giới hạn vận hành** trên AAA, nên ở dạng hiện tại thuộc `REJECT`. Lỗi arena đã có sẵn ở baseline (V8-060). Giới hạn đặt ở `models/v62/runtime-models.json` (`gpu_mem_limit_mb: 1024`), là manifest model đã ghim. Nâng giới hạn này hay đổi cách cấp phát là quyết định của người dùng, cần khóa mới và chạy lại cả baseline lẫn candidate. Người duyệt quyết.

## Candidate 3: VLM Vintern-1B-v3.5 cho trang khó (V8-090, 12/11)

- Mô hình: revision `b98f263e`, sha weights khớp pin; mã tùy biến đã rà. Model đọc 137/137 trang được chọn trên output 004, 0 trang thiếu (`EXP-V8-VLM-20261112-002`). Bản ghi `review_required`, không thay chữ production.
- 2 trang lặp lại prompt. Trên 90 trang có text layer đã sàng lọc: DSER của VLM 4.647, của production 1.606; VLM tốt hơn ở 33 trang, kém hơn ở 43, ngang ở 14 (`scratch/v8/v8_090_vintern_pages_004_20261112.json`). Thang đo cấp trang chịu ảnh hưởng thứ tự đọc nên chỉ là chẩn đoán.
- Đề xuất của operator: `KEEP BASELINE` (không cải thiện, có harm). Người duyệt quyết.

## Còn thiếu cho V8-140

- V8-060, V8-065 và V8-080 (GT bảng, phiếu 72 số) chưa xong.
- Chưa có holdout.
- Cần quyết định chính sách cho dòng confidence thấp mà có chữ thật. Ví dụ VIC tr.95 "số hóa tài liệu đào tạo…" (confidence 0,535) chứa keyword "Số hóa" nhưng nằm ngoài `result.md` (`scratch/v8/v8_100_retained_line_keywords_004_20261112.json`).
