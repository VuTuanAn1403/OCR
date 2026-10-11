# ĐỀ XUẤT SỬA LỖI: ĐỘ CHÍNH XÁC, ĐỘ TIN CẬY VÀ HIỆU NĂNG

**Phạm vi:** pipeline hiện tại (V5.0.0, profile `balanced`), dựa trên mã nguồn trong `src/` và đầu ra batch 5 PDF / 387 trang trong `output/`.
**Ngày quét:** 08–09/10/2026.
**Mục tiêu:** liệt kê những gì cần sửa để kết quả **đúng hơn**, các chỉ số tự báo cáo **đáng tin hơn** và hệ thống **chạy nhanh, ổn định hơn**. Tài liệu này chưa bàn đến chuyện công bố bài báo.

Mỗi vấn đề gồm: **bằng chứng** (số liệu hoặc vị trí trong code), **tác động**, **cách sửa** và **cách kiểm chứng**.

---

## 0. Tóm tắt

| # | Vấn đề | Nhóm | Mức | Công sức |
|---|---|---|---|---|
| A1 | Chữ "ảo" sinh ra khi OCR ảnh chụp lọt vào Markdown | Chính xác | **Nghiêm trọng** | S |
| A2 | Header/footer lặp lại ở mọi trang làm bẩn Markdown (khoảng 1.300 dòng) | Chính xác | Cao | M |
| A3 | Không có ground truth nên không biết hệ thống đúng bao nhiêu | Chính xác | **Nghiêm trọng** | M–L |
| A4 | Profile `balanced` tắt fallback và tắt kiểm tra số khi OCR lại ở DPI cao | Chính xác | Cao | S |
| A5 | Tự xoay ảnh dựa trên tỷ lệ từ tiếng Việt, có thể chọn nhầm hướng | Chính xác | Trung bình | M |
| R1 | `quality_score` bị thổi phồng: block native bị gán cứng 1.0 | Tin cậy | **Nghiêm trọng** | S |
| R2 | `review_queue.json` rỗng dù có 1.036 dòng cần review | Tin cậy | Cao | S |
| R3 | Thời gian theo bước bị tính sai: OCR ảnh bị tính vào `postprocess` | Tin cậy | Cao | S |
| R4 | Số liệu benchmark gán cứng hoặc tạo bằng hệ số tự đặt | Tin cậy | **Nghiêm trọng** | S |
| R5 | 34 khối `except Exception`, trong đó 15 khối nuốt lỗi bằng `pass` | Tin cậy | Trung bình | M |
| R6 | Không có giới hạn thời gian cho mỗi trang; một trang treo làm treo cả batch | Tin cậy | Trung bình | M |
| R7 | Phân loại tài liệu không phân biệt được: cả 5 file đều bị gán MIXED + TABLE_HEAVY + DIAGRAM_HEAVY | Tin cậy | Thấp | S |
| P1 | OCR mọi ảnh trên trang MIXED, kèm thử 4 hướng xoay: **18% số trang chiếm 51% thời gian** | Hiệu năng | **Nghiêm trọng** | M |
| P2 | Trang hai trang ghép (TWO_UP) luôn OCR đủ 4 hướng | Hiệu năng | Trung bình | S |
| P3 | Batch chạy tuần tự, một tiến trình | Hiệu năng | Trung bình | M |
| P4 | Trang native tốt nhưng có ảnh lớn bị chậm, có trang tới 33,7 s | Hiệu năng | Trung bình | S (sửa cùng P1) |

Công sức: S ≤ 1 ngày, M = 2–4 ngày, L ≥ 1 tuần.

---

## 1. Số liệu nền (trước khi sửa)

| Loại trang | Số trang | Tổng thời gian | Tỷ lệ thời gian | Trung vị s/trang |
|---|---:|---:|---:|---:|
| NATIVE_TEXT | 227 | 624 s | 20% | 0,46 |
| MIXED | 69 | 1.575 s | **51%** | **19,0** (tối đa 86 s) |
| NATIVE_TEXT_LOW_QUALITY | 43 | 452 s | 15% | 10,2 |
| SCANNED_IMAGE | 46 | 421 s | 14% | 9,6 |
| PRODUCT_SHOWCASE_COLLAGE | 2 | 24 s | 1% | 11,8 |
| **Tổng** | **387** | **3.094 s** | | trung bình 8,26 |

Các số liệu khác:
- Bộ nhớ đỉnh: khoảng 1,9 GB (KHP).
- Nguồn của các block chữ: 11.799 `native`, 3.406 `primary_ocr`, 2.307 `image_ocr`.
- Trong 2.307 block `image_ocr`, **292 block có confidence < 0,6**.
- Test: 153 passed, 3 skipped.

---

## 2. ĐỘ CHÍNH XÁC

### A1. Chữ "ảo" từ ảnh chụp lọt vào Markdown (nghiêm trọng)

**Bằng chứng:**
- Trong `result.json` có 292 block `image_ocr` với confidence < 0,6. Ví dụ: `DINTHORESSIONALISTICALLY` (0,37), `INTERTENTIONALIZED` (0,40), `Shoodoodories` (0,31), `PILLER` (0,33).
- Các chữ này **xuất hiện trong `result.md`**. Ví dụ `output/KHP_Baocaothuongnien_2020/result.md:186` có dòng `> *Footer*: DINTHORESSIONALISTICALLY`.

**Nguyên nhân:**
- `process_page.py::_extract_image_regions` (dòng 908–1087) OCR **mọi** vùng IMAGE/VECTOR có kích thước ≥ 60×40 pt trên trang MIXED, kể cả ảnh chân dung, phong cảnh, sản phẩm.
- Block tạo ra được thêm thẳng vào đầu ra, **không có ngưỡng confidence nào**.
- Hàm `evaluate_ocr_result` có trả về `needs_fallback`, nhưng giá trị này bị bỏ qua (`q_score, _, _ = ...`).

**Cách sửa:**
1. Thêm một cổng lọc trước khi OCR: chỉ OCR ảnh khi detector RapidOCR tìm được ít nhất N khung chữ, và mật độ khung chữ trên diện tích ảnh vượt một ngưỡng. Bước này chỉ cần chạy detector (~0,3 s), không cần chạy recognizer.
2. Thêm một cổng lọc sau khi OCR, áp dụng cho từng dòng:
   - Bỏ dòng có `confidence < image_ocr_min_conf` (đề xuất 0,6, tinh chỉnh trên dữ liệu kiểm tra ở mục A3).
   - Bỏ dòng thỏa **cả hai** điều kiện: không có dấu tiếng Việt, và không nằm trong từ điển Việt hoặc từ điển tiếng Anh thông dụng.
3. Các dòng bị loại không mất đi: chuyển sang `evidence_blocks` trong JSON với trạng thái `REJECTED_LOW_CONFIDENCE` để còn truy vết, nhưng không đưa vào Markdown.
4. Dòng nằm giữa ngưỡng (ví dụ confidence 0,6–0,8) vẫn được giữ nhưng đánh dấu `needs_review`, và được đếm vào R2.

**Kiểm chứng:**
- Unit test: một ảnh chụp không có chữ phải cho ra 0 block.
- Trên 5 PDF: số block `image_ocr` có confidence < 0,6 trong Markdown phải bằng 0.
- Recall chữ trong ảnh có chữ thật (sơ đồ tổ chức, bảng dạng ảnh) không được giảm, đo trên tập ground truth ở A3.

### A2. Header/footer lặp lại làm bẩn Markdown

**Bằng chứng:**
- Số dòng `> *Footer*` / `> **Header**` trong các file Markdown: KHP 248/300, KSB 40/219, LBM 22/22, LEC 83/61, LHG 185/140.
- Riêng chuỗi `BÁO CÁO THƯỜNG NIÊN 2020` lặp lại 111 lần.

**Nguyên nhân:**
- `reading_order.py` gán nhãn header/footer theo dải tọa độ 10% / 90% chiều cao trang, xét **từng trang riêng lẻ**.
- `markdown_exporter.py` (dòng 77, 357) in header/footer ở mọi trang.
- Không có bước nào loại bỏ chuỗi lặp lại giữa các trang.

**Cách sửa:**
1. Sau khi xử lý xong mọi trang, thêm bước **phát hiện chuỗi lặp giữa các trang**: chuẩn hóa văn bản (bỏ số trang, chuẩn hóa NFC và khoảng trắng); chuỗi nào xuất hiện ở ≥ 30% số trang, ở vị trí tương tự, thì gán `running_header` / `running_footer`.
2. Markdown mặc định **ẩn** running header/footer (thêm tùy chọn `--keep-running-headers` để hiện lại); JSON vẫn giữ đầy đủ.
3. Bỏ điều kiện chỉ dựa vào tọa độ khi block có nội dung dài, ví dụ > 80 ký tự, hoặc là tiêu đề mục. Tránh trường hợp đẩy nội dung thật xuống cuối trang thành footer.

**Kiểm chứng:**
- Số dòng header/footer lặp lại trong Markdown giảm ≥ 90%.
- Không mất dòng nội dung nào: so sánh tập dòng trong Markdown trước và sau khi sửa, phần chênh lệch chỉ được là các chuỗi lặp.

### A3. Chưa đo được độ chính xác: cần một bộ ground truth hồi quy nhỏ

**Bằng chứng:**
- Mọi báo cáo đều ghi `accuracy_status: NOT_AVAILABLE_NO_GROUND_TRUTH`.
- Các PDF mà ground truth hiện có tham chiếu tới (CLW, BBC, BFC, BRC, C47, CDC) không có trong `inputs/`, nên 3 test bị skip.

**Cách sửa** (mức tối thiểu đủ dùng cho kỹ thuật, chưa phải bộ dữ liệu nghiên cứu):
1. Chọn khoảng **60 trang** từ 5 PDF đang có, phân tầng theo loại trang:

   | Loại trang | Số trang |
   |---|---:|
   | NATIVE_TEXT | 15 |
   | MIXED | 15 |
   | SCANNED_IMAGE | 10 |
   | NATIVE_TEXT_LOW_QUALITY | 10 |
   | Trang có bảng tài chính | 10 |

2. Chép ground truth văn bản (NFC) và ground truth bảng (HTML) cho các trang này. Lưu tại `benchmark/ground_truth/regression_v1/` kèm SHA-256 của từng PDF.
3. Đưa 5 PDF vào một thư mục cố định, ví dụ `benchmark/pdfs/`. Không commit PDF nếu repo công khai; thay vào đó dùng script kiểm hash.
4. Viết `scripts/run_regression.py`:
   - Chạy pipeline trên 60 trang này.
   - Xuất CER, WER, DER, NumAcc (độ chính xác số: tỷ lệ con số khớp tuyệt đối), TEDS, và tỷ lệ dòng rác (từ A1).
   - Báo theo từng loại trang.
5. Đưa vào CI hoặc pre-commit dưới dạng **ngưỡng không được tụt**: CER và NumAcc của mỗi loại trang không được xấu đi quá 0,5 điểm phần trăm so với lần chạy được chọn làm mốc (baseline).

**Kiểm chứng:**
- `run_regression.py` chạy được trong khoảng 10 phút và cho ra bảng chỉ số cho mỗi loại trang.
- 3 test đang bị skip được thay bằng test dùng bộ dữ liệu mới.

> Mọi thay đổi ở A1, A2, A4, A5 và P1 đều phải đo trên bộ này, cả trước và sau khi sửa. Thiếu bộ này thì không chứng minh được thay đổi nào là cải tiến.

### A4. Fallback và kiểm tra số đang tắt ở profile mặc định

**Bằng chứng:**
- `config/profiles.yaml`: profile `balanced` có `fallback_enabled: false` và không có `regional_retry_enabled`.
- Báo cáo batch ghi fallback **0,0%** ở cả 5 file.
- Cơ chế đánh dấu cần review khi lượt OCR ở DPI cao cho **con số khác** với lượt đầu (`process_page.py` dòng ~985–995) chỉ chạy ở profile `accuracy`.
- README lại mô tả đây là tính năng mặc định.

**Tác động:** với báo cáo tài chính, sai một con số là lỗi nặng nhất, nhưng profile mặc định không có lớp bảo vệ nào cho trường hợp này.

**Cách sửa:**
1. Bật kiểm tra chéo số trong `balanced`, nhưng chỉ với vùng thỏa cả hai điều kiện: có ≥ 1 token số, và confidence < 0,85. Như vậy chi phí bị giới hạn.
2. Đo trên A3 để chọn giữa `fallback_enabled: true` và `false` cho `balanced`, dựa vào NumAcc và thời gian. Ghi kết quả vào `profiles.yaml` dưới dạng chú thích.
3. Sửa README cho khớp với hành vi thực tế.

**Kiểm chứng:** NumAcc trên các trang SCANNED và LOW_QUALITY của A3 tăng, hoặc không đổi; thời gian tăng < 15%.

### A5. Quyết định xoay ảnh dựa trên tỷ lệ từ tiếng Việt

**Bằng chứng:**
- `_predict_with_orientation_fallback` (dòng 599–690) chọn hướng xoay theo `vn_lexicon_ratio` và `_orientation_candidate_score`.
- Với ảnh không có chữ, cả 4 hướng đều cho ra chữ rác. Hướng nào có điểm cao nhất sẽ thắng và sinh ra rác (liên quan A1).

**Cách sửa:**
1. Áp cổng lọc ở A1 trước khi thử xoay: không có khung chữ thì không thử xoay.
2. Ước lượng hướng bằng **góc của các khung chữ từ detector**, tức tỷ lệ khung đứng so với khung ngang, thay vì OCR đủ 4 hướng rồi so điểm ngôn ngữ. Chỉ khi không quyết định được mới chạy OCR để so.
3. Nếu kết quả là `orientation_uncertain` thì **không đưa chữ vào Markdown**, chỉ giữ ảnh và đánh dấu cần review.

**Kiểm chứng:** tạo một bộ test gồm 20 ảnh crop đã biết hướng (0°, 90°, 180°, 270°). Độ chính xác chọn hướng phải ≥ 95%.

---

## 3. ĐỘ TIN CẬY (của chỉ số tự báo cáo và của quá trình chạy)

### R1. `quality_score` bị thổi phồng

**Bằng chứng:**
- `process_page.py` dòng 139–141: mọi block native bị gán `quality_score = 1.0` và `confidence = 1.0`.
- `quality_score` của trang là trung bình các block (dòng 433). Trang MIXED có nhiều block native thì điểm luôn gần 1, dù phần OCR ảnh rất tệ.
- Ví dụ: KHP trang 2 có `ocr_confidence = 0,16` nhưng `quality_score = 0,99`. Có 85 trang có confidence < 0,75; phần lớn vẫn có quality ≥ 0,9 và `review_required_count = 0`.

**Cách sửa:**
1. Block native lấy điểm từ `native_quality` của trang (đã được tính trong `native_quality.py`), không gán 1.0.
2. Tách hai chỉ số: `native_quality` và `ocr_quality`, mỗi chỉ số kèm số dòng của nó.
   - `quality_score` của trang = trung bình có trọng số theo số ký tự.
   - Bổ sung thêm `min_region_quality`.
3. Thêm trường `low_confidence_line_count`: số dòng OCR có confidence < 0,6.

**Kiểm chứng:**
- Trên A3, tương quan Spearman giữa `quality_score` và (1 − CER) theo trang phải ≥ 0,5.
- Hiện tại không đo được tương quan này, và dự đoán là rất thấp.

### R2. Hàng chờ review rỗng dù có nhiều dòng cần kiểm tra

**Bằng chứng:**
- Tổng `review_required_count` của các trang là **1.036**, có **544** dòng `suspicious_lines`.
- Nhưng `output/review_queue.json` là `[]`.
- `batch_runner.py` dòng 430–446 chỉ xét điểm trung bình **theo file** (`q_score < 0.85`), mà điểm này đã bị thổi phồng ở R1.
- Markdown không chứa đánh dấu cần review nào.

**Cách sửa:**
1. Hàng chờ review lấy theo **trang hoặc vùng**. Mỗi mục gồm: file, trang, region_id, lý do (`low_confidence`, `numeric_disagreement`, `orientation_uncertain`, `rejected_hallucination`), số dòng bị ảnh hưởng.
2. Sắp xếp theo mức độ, ưu tiên vùng có số liệu và confidence thấp.
3. Tùy chọn: Markdown chèn chú thích `<!-- NEEDS_REVIEW: region r12 -->` để người đọc biết chỗ nào chưa chắc.

**Kiểm chứng:** số mục trong `review_queue.json` bằng số vùng có `needs_review`. Unit test với một trang giả lập có 3 vùng cần review.

### R3. Thời gian theo bước bị tính sai

**Bằng chứng:**
- Trang MIXED có `primary_ocr = 0` nhưng `postprocess` lên tới 86 s (LHG trang 8).
- `stage_seconds.postprocess` được tính bằng "phần còn lại" (dòng 463). `_extract_image_regions` (OCR ảnh) không được bấm giờ riêng nên rơi vào phần còn lại này.
- Báo cáo batch vì vậy kết luận sai rằng **postprocess là nút cổ chai (67%)**. Thực tế nút cổ chai là OCR vùng ảnh.

**Cách sửa:**
1. Bấm giờ riêng các bước `image_region_ocr`, `orientation_retry`, `reading_order`, `export`.
2. Thêm `other` (phần không được bấm giờ) và cảnh báo khi `other` > 10% tổng thời gian.
3. Đếm số lần gọi `ocr_engine.predict_image` cho mỗi trang (`ocr_calls`), giúp phát hiện các vòng thử xoay.
4. Dùng `time.perf_counter()` thay cho `time.time()`.

**Kiểm chứng:** trên 5 PDF, `other` < 5% ở mọi trang; tổng các bước khớp với `time_taken_seconds` (sai lệch ±2%).

### R4. Số liệu benchmark gán cứng hoặc tự tạo

**Bằng chứng:**
- `benchmark/scientific_evaluation/ablation_runner.py::run_synthetic_ablation_comparison` nhân các giá trị mặc định với hệ số tự đặt.
- `scripts/run_scientific_benchmark.py:269-275` gán cứng TEDS `0.892`, và dùng mAP `0.945`, CER `0.021` làm giá trị mặc định khi không đo được.
- Các file `benchmark/results/**/*_ablation_table.tex` chứa những số này.

**Cách sửa:**
1. Xóa hàm tạo số liệu và các giá trị mặc định. Không có ground truth thì xuất `N/A`.
2. Chuyển các file `.tex` hiện có vào `benchmark/results/_invalid/`, kèm README giải thích lý do.
3. Thêm test quét thư mục `benchmark/` để chặn các hằng số chỉ số.
4. Đổi tên `DLAEngine` thành `HeuristicLayoutClassifier`, vì không có model ONNX nào được nạp.

**Kiểm chứng:** chạy `run_scientific_benchmark.py --generate-latex` khi không có ground truth thì không sinh ra bảng nào.

### R5. Lỗi bị nuốt im lặng

**Bằng chứng:** trong `src/` có 34 khối `except Exception`, trong đó 15 khối chỉ có `pass`. Ví dụ phần phân loại block native ở `process_page.py` khoảng dòng 157.

**Cách sửa:**
1. Thay `pass` bằng ghi log có cấu trúc (module `logging`, mức WARNING, kèm trang và vùng), và tăng bộ đếm `errors` trong `quality.json` của trang.
2. Thay `print` bằng `logging` trong toàn bộ `src/`, để batch có thể ghi log ra file.
3. Trang có lỗi thì `content_status = PARTIAL`, không được là `EXTRACTED`.

**Kiểm chứng:** test cố tình gây exception trong `_classify_text_block`; trang phải có `errors ≥ 1` và log ghi được lỗi.

### R6. Không có giới hạn thời gian cho mỗi trang

**Bằng chứng:**
- Trang chậm nhất mất 86 s.
- Không có cơ chế timeout hay watchdog. Nếu VietOCR hoặc PyMuPDF bị treo ở một trang, cả batch dừng theo.

**Cách sửa:**
1. Đặt `page_timeout_seconds` trong profile, đề xuất 120 s. Hết giờ thì đánh dấu trang `TIMEOUT`, giữ ảnh trang và chuyển sang trang tiếp theo.
2. Thực hiện bằng cách chạy mỗi trang trong process worker (kết hợp với P3). Không nên dùng thread, vì thread không ngắt được giữa chừng.
3. Batch phải tiếp tục được (resume) theo từng trang, không chỉ theo từng file. Kiểm tra lại `artifact_cache.py`.

**Kiểm chứng:** test với một engine giả bị "treo" 200 s; trang đó phải có trạng thái TIMEOUT và batch vẫn chạy xong.

### R7. Phân loại tài liệu không phân biệt được

**Bằng chứng:** cả 5/5 file đều bị gán đồng thời MIXED, TABLE_HEAVY và DIAGRAM_HEAVY.

**Cách sửa:** định nghĩa lại theo tỷ lệ:
- TABLE_HEAVY khi ≥ 30% số trang có bảng.
- DIAGRAM_HEAVY khi ≥ 10% số trang có sơ đồ.
- MIXED khi tỷ lệ trang OCR nằm trong khoảng 10–90%.

Ghi các ngưỡng vào cấu hình.

### R8. Khả năng tái lập

- Mọi lần chạy batch đều có `git is_clean: false`. Nên thêm cảnh báo rõ ràng, và lưu `git diff` (hoặc hash của diff) vào `manifest.json`.
- Có 11 file đang sửa dở chưa commit. Nên commit theo từng nhóm thay đổi trước khi bắt đầu sửa theo đề xuất này.

---

## 4. HIỆU NĂNG

### P1. OCR vùng ảnh trên trang MIXED là nút cổ chai thật

**Bằng chứng:**
- Trang MIXED chiếm 18% số trang nhưng **51% thời gian**, trung vị 19 s/trang so với 0,46 s ở trang native.
- Các trang chậm nhất (KHP 70–84, LHG 6/8/10, KSB 12) đều là MIXED, chỉ có 2–22 vùng IMAGE và **không có OCR toàn trang**.

**Nguyên nhân:**
- Với mỗi ảnh, `_predict_with_orientation_fallback` chạy OCR một lần. Nếu ảnh không chứa chữ tiếng Việt (vn_ratio < 0,12), mà ảnh chụp thì luôn như vậy, hàm sẽ **chạy thêm 3 lần OCR cho 3 hướng xoay**.
- Tức là mỗi ảnh chụp tốn 4 lần detector và 4 lần recognizer, chỉ để sinh ra chữ rác như đã nêu ở A1.

**Cách sửa** (cùng hướng với A1 và A5):
1. Bước tiền lọc rẻ, chạy trước khi OCR:
   - Dùng phương sai Laplacian hoặc mật độ cạnh để loại ảnh chụp mịn.
   - Dùng tỷ lệ pixel gần hai màu (trắng và đen) để nhận ra ảnh có chữ.
2. Chạy **chỉ detector** (khoảng 0,1–0,3 s). Nếu có dưới N khung chữ thì bỏ qua vùng đó.
3. Ước lượng hướng từ khung chữ (A5), thay vì OCR đủ 4 hướng.
4. Lưu cache kết quả theo hash của ảnh nhúng (`xref` trong PyMuPDF). Logo hoặc ảnh lặp lại ở nhiều trang chỉ cần OCR một lần.

**Ước tính hiệu quả** (cần đo lại sau khi sửa R3):
- Nếu 70–80% ảnh trên trang MIXED là ảnh không có chữ, thời gian trang MIXED có thể giảm từ khoảng 19 s xuống khoảng 3–5 s.
- Tổng thời gian batch giảm khoảng 35–45%, trung bình từ 8,3 s/trang xuống khoảng **4,5–5,5 s/trang**.

**Kiểm chứng:**
- Đo trên cùng 5 PDF, cùng máy, trước và sau khi sửa: báo thời gian trung vị và P95 theo loại trang, cùng số `ocr_calls` mỗi trang.
- Recall chữ trong ảnh có chữ thật trên A3 không được giảm.

### P2. Trang ghép hai trang (TWO_UP/MULTI_REGION) luôn OCR 4 hướng

**Bằng chứng:** khi `evaluate_all_orientations=True` (dòng 197, 619), hàm bỏ qua lối thoát sớm và luôn chạy thêm 3 lần OCR xoay.

**Cách sửa:** chỉ thử xoay khi tỷ lệ khung chữ đứng ≥ 30%, hoặc khi lượt đầu có confidence < 0,7.

**Kiểm chứng:** test trang ghép hiện có (`test_two_up_mixed_orientation_v321.py`) vẫn pass, và `ocr_calls` giảm.

### P3. Batch chạy tuần tự trên một tiến trình

**Bằng chứng:**
- Máy có 6 nhân / 12 luồng, nhưng `batch_runner.py` xử lý tuần tự từng file và từng trang.
- `rapidocr_engine.predict_batch` thực chất là một vòng lặp tuần tự.

**Cách sửa:**
1. Dùng `ProcessPoolExecutor` theo **trang**, với số worker bằng `min(physical_cores − 1, 4)`. Mỗi worker nạp model một lần lúc khởi động. Có thể giới hạn `torch.set_num_threads` và số luồng của ONNX Runtime (`intra_op_num_threads`) để tránh tranh chấp CPU.
2. Đưa số worker vào profile. Với máy 16 GB RAM, dự kiến mỗi worker dùng khoảng 1,2–1,9 GB, nên tối đa 3–4 worker.
3. Kết quả phải **giống hệt** khi chạy tuần tự. Thêm test so sánh JSON đầu ra của 1 worker và N worker.

**Ước tính:** throughput tăng 2–3 lần trên máy 6 nhân, nhưng độ trễ của từng trang không giảm.

**Kiểm chứng:** đo số trang/phút và bộ nhớ đỉnh với 1, 2, 3, 4 worker; chọn cấu hình mặc định theo kết quả.

### P4. Trang NATIVE_TEXT có ảnh lớn bị chậm

**Bằng chứng:** trung vị trang native là 0,46 s, nhưng `postprocess` tối đa 33,7 s. Nguyên nhân giống P1: OCR ảnh chiếm ≥ 20% diện tích trang.

**Cách sửa:** áp dụng cùng cổng lọc ở P1.

### Các tối ưu khác (làm sau)

- Bật VietOCR `predict_batch` cho các dòng trên **nhiều vùng gộp lại** thay vì gọi riêng từng vùng.
- Thử chạy VietOCR qua ONNX hoặc lượng tử hóa INT8. Chỉ làm khi đã có A3 để đo CER trước và sau.
- Tận dụng `artifact_cache.py` khi chạy lại cùng PDF với cấu hình khác, chỉ OCR lại những gì thay đổi.

---

## 5. Lộ trình đề xuất

| Đợt | Nội dung | Lý do làm trước | Thời gian ước tính |
|---|---|---|---|
| **Đợt 0** | Commit các thay đổi đang dở; R4 (xóa số liệu giả); R3 (bấm giờ đúng) | Cần số đo đúng trước khi tối ưu | 1–2 ngày |
| **Đợt 1** | A3 (bộ ground truth hồi quy 60 trang và `run_regression.py`); chụp số liệu mốc | Không có A3 thì không chứng minh được sửa đổi nào là tốt hơn | 4–6 ngày (phần lớn là chép ground truth) |
| **Đợt 2** | A1 và P1, P4 (cổng lọc ảnh, ngưỡng confidence); A5 (hướng từ khung chữ); P2 | Sửa được cả lỗi chính xác nặng nhất lẫn nút cổ chai lớn nhất | 3–5 ngày |
| **Đợt 3** | R1, R2 (điểm chất lượng thật, hàng chờ review theo vùng); A4 (kiểm tra số trong `balanced`) | Hệ thống tự báo đúng chỗ nào cần người kiểm tra | 2–3 ngày |
| **Đợt 4** | A2 (running header/footer); R5, R6, R7, R8 | Làm sạch đầu ra và tăng độ bền | 3–4 ngày |
| **Đợt 5** | P3 (song song theo trang) và các tối ưu khác | Tăng throughput sau khi luồng xử lý đã đúng | 3–5 ngày |

Sau mỗi đợt: chạy `pytest` và `run_regression.py`, đồng thời chạy lại batch 5 PDF, rồi ghi bảng "trước/sau" vào `docs/CHANGELOG_METRICS.md`.

---

## 6. Chỉ tiêu nghiệm thu

| Chỉ tiêu | Hiện tại | Mục tiêu sau đợt 5 |
|---|---|---|
| Dòng `image_ocr` có confidence < 0,6 trong Markdown | 292 | **0** |
| Dòng running header/footer lặp lại trong Markdown | khoảng 1.300 | giảm ≥ 90% |
| CER / NumAcc theo loại trang (trên A3) | chưa đo | có số; không tụt so với mốc ở đợt 1 |
| Tương quan `quality_score` với (1 − CER) | chưa đo | Spearman ≥ 0,5 |
| Vùng cần review có trong `review_queue.json` | 0 / 1.036 | 100% |
| Thời gian không được bấm giờ (`other`) | ~67% bị gán nhầm là "postprocess" | < 5% |
| Trung vị s/trang, trang MIXED | 19,0 | ≤ 5 |
| Trung bình s/trang, toàn batch (1 worker) | 8,26 | ≤ 5,5 |
| Throughput (3–4 worker) | 7,2 trang/phút | ≥ 20 trang/phút |
| Trang bị treo làm dừng batch | có thể xảy ra | không: có trạng thái TIMEOUT |
| Số liệu gán cứng trong `benchmark/` | có | không (có test chặn) |
| Test | 153 pass / 3 skip | toàn bộ pass, 0 skip vì thiếu PDF |

> Các con số mục tiêu về thời gian là **ước tính**, vì nguyên nhân gốc chỉ được xác nhận chính xác sau khi sửa R3. Cần điều chỉnh mục tiêu sau đợt 0.

---

## 7. Câu hỏi cần bạn chốt

1. Ngưỡng ưu tiên khi phải chọn giữa **bỏ sót chữ thật trong ảnh** và **lọt chữ rác**: đề xuất ưu tiên không lọt rác, phần nghi ngờ đưa vào hàng chờ review.
2. Markdown có nên **ẩn** running header/footer theo mặc định không?
3. Máy nào dùng làm **máy chuẩn** để đo thời gian? Kết quả trên các máy cá nhân sẽ khác nhau.
4. Ai sẽ chép ground truth cho 60 trang ở A3, và có cần người thứ hai kiểm tra lại không?
