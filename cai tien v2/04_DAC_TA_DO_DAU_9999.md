# Đặc tả đo bảo toàn dấu tiếng Việt 99,99%

Kế thừa [Cai Tien/09](09_LUU_TRU_CAI_TIEN_V7.md#ct-09). Cơ chế cổng đang chạy vẫn ở [NATIVE_DIACRITIC_RELEASE_V7](../benchmark/scientific_evaluation/NATIVE_DIACRITIC_RELEASE_V7.md). Tài liệu này khóa **định nghĩa, cỡ mẫu và cách công bố** trước khi đo.

**Trạng thái:** `NOT_EVALUATED`. Chưa có phép đo nào trên GT độc lập.

## 1. Mệnh đề được phép công bố

Chỉ công bố theo đúng mẫu sau:

> Trên corpus `<id + sha manifest>` gồm N slot dấu thuộc phạm vi `<loại PDF, luồng OCR/native>`, hệ thống `<identity code/model/runtime>` có k lỗi slot. Cận trên một phía 95% (Clopper-Pearson) của tỷ lệ lỗi là p_U ≤ 0,0001. Vì vậy tỷ lệ bảo toàn dấu ≥ 99,99%.

Ba điều kiện kèm theo:
- Không được viết "đạt 99,99%" khi chỉ có ước lượng điểm.
- Không được dùng GT do chính pipeline hay một AI khác tạo ra.
- Không ngoại suy sang PDF ngoài phạm vi đã khai báo.

## 2. Đơn vị đo: slot dấu

Văn bản GT và văn bản dự đoán đều chuẩn hóa NFC trước, rồi tách NFD từng chữ để đọc dấu. Cách tách này đúng với `benchmark/scientific_evaluation/ocr_metric.py::_extract_vietnamese_diacritic_slots`.

| Loại slot | Ký tự | Ví dụ |
| --- | --- | --- |
| Thanh (tone) | U+0300 huyền, U+0301 sắc, U+0303 ngã, U+0309 hỏi, U+0323 nặng | à á ã ả ạ |
| Dấu phụ (shape) | U+0302 mũ, U+0306 trăng, U+031B móc | â ê ô ă ơ ư |
| Nét gạch (stroke) | đ, Đ | đồng |

Mỗi chữ có thể mang tới ba slot. Chữ "ộ" mang 2 slot: mũ và nặng. Ngoài ba loại slot, đếm riêng hai loại lỗi:
- **dấu thừa**: dự đoán có dấu trên vị trí GT không có;
- **dấu chưa tổ hợp**: combining mark còn trơ sau NFC (`benchmark/scientific_evaluation/diacritic_acceptance.py::uncomposed_vietnamese_marks`).

Byte raw khác NFC nhưng cùng nội dung thì **không phải lỗi**.

## 3. Metric

| Metric | Định nghĩa | Ghi chú |
| --- | --- | --- |
| `DER_VN_v1` (hiện có) | Lỗi slot sau căn Levenshtein ký tự, chia cho số slot GT | Một slot cũng bị tính lỗi khi chữ cơ sở khác (`r_base != p_base`). Vì vậy lỗi nhận sai chữ bị đếm thành lỗi dấu và DER bị thổi phồng |
| `DSER_strict` (V8-020, `ocr_metric.py::compute_dser_strict_detailed`) | Như v1, nhưng cặp có chữ cơ sở khác đi vào `base_mismatch_slots` và CER, không vào lỗi dấu. Ký tự GT bị xóa vẫn tính lỗi slot | Là metric chính cho mệnh đề 99,99% |
| `base_mismatch_slots` | Số slot nằm trên chữ bị nhận sai cơ sở | Báo cạnh DSER; bắt buộc tính vào cổng keyword |
| CER, WER | Như `compute_cer_detailed`, `compute_wer_detailed` | Báo theo nhóm khó: chữ nhỏ, bảng, scan mờ |

Báo song song v1 và DSER_strict trên cùng một căn chỉnh để giữ liên tục với lịch sử. Mọi metric phải kèm tử số, mẫu số, phạm vi, partition và identity. Không gộp các metric thành một điểm "overall".

## 4. Cỡ mẫu và cận thống kê

Cận trên một phía dùng Clopper-Pearson chính xác. Với 0 lỗi, công thức là p_U = 1 − α^(1/N) ≈ −ln α / N. Các con số dưới đây tính ngày 08/11 bằng nhị phân chính xác:

| Số lỗi k cho phép | N tối thiểu (95%) | N tối thiểu (99%) |
| --- | ---: | ---: |
| 0 | 29.956 | 46.050 |
| 1 | 47.437 | 66.381 |
| 2 | 62.956 | 84.057 |
| 3 | 77.535 | 100.448 |

**Hiệu ứng cụm.** Slot cùng trang, cùng công ty không độc lập với nhau. Dùng N_eff = N / DEFF với DEFF = 1 + (m − 1)ρ, trong đó ρ ước lượng trên tập development. Nếu chưa ước lượng được ρ, chỉ công bố mệnh đề **trong mẫu** và giữ mệnh đề tổng quát ở `NOT_EVALUATED`.

**GT hiện có.** Chỉ có 4 trang CLW trong `benchmark/ground_truth/`, tổng 1.788 slot (788 phụ, 867 thanh, 133 đ). Số này đếm ngày 08/11 theo định nghĩa v1. CLW không thuộc 9 PDF đầu vào, và custody của GT này chưa rõ. Nếu 0 lỗi trên 1.788 slot thì cận 95% là 0,167%, nghĩa là chỉ khẳng định được ≥ 99,83%. Lượng GT này mới bằng khoảng 6% mức cần cho 99,99%.

**Điểm chặn trong mã: đã sửa ngày 09/11** (V8-021, V8-022):
- Trước đây `stratified_scorecard.py::_adequate_interval` đòi `0 < upper − lower`, nên kết quả hoàn hảo ra `NOT_EVALUATED`. Nay, khi 0 lỗi, `_error_rate_interval` thay khoảng bootstrap suy biến bằng cận Clopper-Pearson trên N_eff. Điều kiện là `design_effect` đã khóa trong plan.
- Trước đây luồng OCR của cổng chỉ so ước lượng điểm `(lỗi + dấu trơ) × 10000 ≤ slot`. Nay `release_gate.py::_ocr_diacritic_bound_gate` gọi `exact_bounds.py::upper_bound_gate`. Kết quả FAIL khi ước lượng điểm đã vượt 10⁻⁴, PASS chỉ khi p_U ≤ 10⁻⁴. Mọi trường hợp khác là `NOT_EVALUATED`, kèm số slot cần có.
- `exact_bounds.py::minimum_trials` tái tạo đúng bảng cỡ mẫu ở trên (test `tests/scientific/test_exact_bounds.py`).
- Chưa làm: ước lượng ρ trên development. Thiếu ρ thì chỉ có mệnh đề trong mẫu.

## 5. Nguồn Ground Truth

Người dùng đã xác nhận không có người gán nhãn A/B. Mỗi lựa chọn dưới đây được ghi rõ giới hạn; protocol phải chọn và khóa trước khi đo (V8-013).

| Lựa chọn | Hợp lệ cho | Giới hạn bắt buộc công bố |
| --- | --- | --- |
| (a) Tổng hợp theo cấu tạo: render văn bản đã biết thành ảnh hoặc PDF với font, DPI, nhiễu có kiểm soát (V8-010) | Stress test recognizer và retry dấu | Lệch phân phối so với báo cáo thường niên thật; không đại diện cho bố cục |
| (b) PDF born-digital có text layer đã xác minh (V8-011) | Tham chiếu cho luồng OCR trên ảnh render của chính trang đó | Text layer có thể sai theo phần mềm tạo PDF (ToUnicode, font nhúng); phải xác minh độc lập trước, `native_diacritic_replay.py` là điểm vào |
| (c) Một chuyên gia gán nhãn, kèm kiểm tra lại mù trên mẫu ngẫu nhiên | GT trang thật | Không có chỉ số đồng thuận giữa người gán; ghi rõ là single-annotator |
| (d) Bộ dữ liệu công khai | So sánh ngoài | Phải kiểm licence và miền; bộ chữ cảnh (scene text) không thay được tài liệu in ([01](01_RADAR_CONG_NGHE_THEO_TANG.md)) |
| (e) **Cấm** | — | Output model, đồng thuận giữa engine, output của pipeline, nhãn AI sơ bộ (38 crop hiện có) |

Chênh lệch giữa các engine chỉ được dùng để **chọn vùng cần soát**, và trọng số lấy mẫu phải công bố.

**Quyết định ngày 09/11 (V8-013):** người dùng chọn (b). Kiểm kê có 720/938 trang ứng viên với 345.687 slot. Đây là ứng viên chưa xác minh, chưa phải GT. Quy trình xác minh đã LOCKED v1. Người dùng là người duyệt kiêm custodian. Cả 9 PDF là development, còn holdout sẽ là PDF mới. Chi tiết ở [GROUND_TRUTH_PROTOCOL §7](../docs/quality_assurance/GROUND_TRUTH_PROTOCOL.md#7-nguồn-gt-cho-cổng-dấu-v8-v8-013-v8-011).

## 6. Tác động lên đếm keyword

Với tỷ lệ lỗi slot p và keyword có d slot, xác suất một occurrence đọc đúng xấp xỉ (1 − p)^d. Ví dụ p = 10⁻⁴, d = 10 cho khoảng 0,999. Nhưng lỗi dấu thường **có hệ thống**: một từ có thể luôn bị đọc sai. Vì vậy phải báo theo từng keyword, không chỉ báo tỷ lệ chung.

Ba lỗ hổng đã xác minh trong mã ([02](02_KIEM_TOAN_KHOANG_TRONG.md)):
1. Retry dấu chỉ kích hoạt theo 21 cụm cố định (`DEFAULT_PHRASES`). `diacritic_suspicions` đã nhận `extra_phrases`, nhưng `retry_diacritic_blocks` không truyền từ điển keyword vào (V8-030).
2. Keyword một từ bị sai dấu thì mất mà không có cảnh báo, vì alias chỉ xét cụm ≥ 2 từ (V8-031). Từ 09/11, companion `keyword_two_tier.json` có `single_word_variants`: danh sách để review, không cộng vào số đếm, vì từ đơn gấp dấu rất dễ trùng một từ khác.
3. `literal_v1` khớp chuỗi con, không xét ranh giới từ, nên keyword chồng lấn bị đếm trùng (V8-032). Challenger `literal_v2` (ranh giới từ, chồng lấn chọn trái nhất rồi dài nhất) đã có trong `counter.py`. `scripts/compare_keyword_policies.py` báo chênh lệch theo từng nguyên nhân. Sản phẩm vẫn dùng v1 cho tới khi có GT occurrence (V8-100).

**Cổng keyword:** trong phạm vi đã gán nhãn, 0 occurrence thiếu và 0 occurrence thừa, dùng `benchmark/scientific_evaluation/keyword_acceptance.py::evaluate`. Hai kết quả có cùng tổng nhưng khác vị trí là khác nhau. Không sửa alias rules để làm đẹp kết quả.

## 7. Trình tự đo

1. Khóa các định nghĩa trong tài liệu này, ngưỡng, α, k, kế hoạch cỡ mẫu và split theo công ty. Holdout không được chạm.
2. Sửa điểm chặn thống kê V8-021/022 và metric V8-020, có test.
3. Dựng GT theo lựa chọn đã khóa (§5), đủ N_eff.
4. Đo baseline trên development, ghi theo [hợp đồng 05](05_HOP_DONG_BENCHMARK_ADAPTER.md).
5. Thử các sửa đổi V8-030..033 trên development. Sửa trong closure extraction (`src/ocr_text`, `src/ocr_recognition`) tạo OCR identity mới, nên phải chạy output mới. Sửa ở `src/ocr_keywords` chỉ đổi fingerprint analysis.
6. Chọn ngưỡng kích hoạt trên calibration, rồi khóa.
7. Đo holdout **một lần**. Báo k, N, N_eff, p_U, CER kèm theo, cổng keyword và fix/harm.

## 8. Mẫu báo cáo cho bài báo

| Trường | Bắt buộc |
| --- | --- |
| Corpus, sha manifest, split, số công ty, trang, slot | Có |
| Luồng (OCR / native) và loại PDF | Có |
| Identity: commit, `code_fingerprints()`, sha model, lock, GPU/CUDA | Có |
| k, N, N_eff, DEFF, α, p_U, phương pháp cận | Có |
| DSER_strict, DER_VN_v1, `base_mismatch_slots`, CER/WER theo nhóm | Có |
| Keyword: thiếu, thừa, không gán nguồn theo từng keyword | Có |
| Giới hạn GT theo §5 | Có |
