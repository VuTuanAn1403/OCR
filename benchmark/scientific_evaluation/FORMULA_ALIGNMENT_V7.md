# Căn công thức theo trang và vị trí

`formula_alignment.py` tạo bằng chứng vị trí từ batch CUDA canonical đã công bố. Có thể kiểm kê prediction trước khi nhận phiếu. Căn vị trí là bước chuẩn bị cho CDM và rà lỗi critical. Kết quả ở mức chẩn đoán, gate nghiệm thu giữ `NOT_EVALUATED`.

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
.venv/Scripts/python.exe -B -m benchmark.scientific_evaluation.formula_alignment `
  --batch output/operations_4pdf_warm_1_20261104 `
  --iou-threshold .5 `
  --output scratch/formula-alignment-moi
```

Thêm `--annotations <file.json>` khi có annotation đã hoàn tất. `.5` là ngưỡng thử trên development. Output dùng đường dẫn mới ngoài batch. `alignment.json` ghi batch/revision, PDF hash, receipt, completion, extraction và hash annotation. Nếu có biểu thức tham chiếu, `cdm-pairs.json` chứa cả các công thức không có prediction, mỗi cặp nối lại qua `references[].pair_id`. Adapter CDM dùng venv CPU riêng. [Lệnh render CDM](FORMULA_CDM_V7.md#cài-và-chạy-lại-bộ-mẫu-phát-triển).

Annotation dùng `schema_version: ocr-formula-page-annotations-v1`. `documents` là danh sách gồm `document_id`, `pdf_sha256`, `total_pages` và `pages`. Mỗi trang cần `page` vật lý từ 1, `coordinate_space`, `transforms`, `width`, `height` và `formulas`. Trang chưa gán nhãn dùng `null` hoặc bỏ hẳn khỏi danh sách. Trang đã rà hết và xác nhận âm tính dùng `[]`. Mỗi công thức có `id`, `bbox` trong khung trang, `placement` (`inline` hoặc `display`), `format` (`LATEX`, `TEXT`, `MATHML`), `content_raw` và `equation_label` có thể null. Vùng không chấm cần `ignore_regions` với `id`, `bbox` và `reason`.

Các dự đoán gồm item `kind=f` và text block có role công thức, theo trạng thái extraction. Tập ứng viên vẫn giữ block suppressed trong báo cáo để truy nguồn. Candidate không có bbox hợp lệ tính dư trên trang đã gán nhãn. Căn một-một tối đa số cặp rồi tối đa tổng IoU. Sau khi căn, prediction trùng vùng GT được tính FP kể cả khi vùng ignore chồng lên đó. Một prediction còn lại được ignore nếu IoU với vùng ignore đạt ngưỡng. Các tổng TP/FP/FN chỉ tính trên những trang đã gán nhãn. Hộp trùng vị trí chỉ cho biết đã định vị, còn `reference_placement` phân tầng theo nhãn nguồn.

Text formula giữ nội dung raw và bản corrected, xuất `TEXT` cho bộ chấm cặp. Công thức trong đoạn thường hay ô bảng có thể đi qua hồ sơ span ở dưới. `equation_label` giữ riêng và cần kiểm critical cùng nội dung, dấu, quan hệ, phân số, số và chỉ số. [Phạm vi v7.0](../../cai%20tien%20v2/09_LUU_TRU_CAI_TIEN_V7.md#ct-11).

## Truy xuất biểu thức nằm trong block hoặc ô bảng

Thêm `--embedded-spans <file.json>` để lấy nguyên văn các khoảng đã khoanh trên extraction. Schema `ocr-formula-embedded-spans-v1` yêu cầu `annotation_sha256` khớp file annotation đang đọc, hoặc `null` khi chỉ kiểm kê. Mỗi phần tử `documents` gồm `document_id`, `pdf_sha256`, `completion_sha256`, `extraction_sha256` và `pages`. Khai báo đủ khung trang như annotation và danh sách `spans`.

Mỗi span có `id`, `locator`, `start`, `end`, `reason` và tùy chọn `reference_id`. Locator của block chứa `item_id`. Locator của ô chứa `item_id` bảng và `row`, `col` từ 0. Offset là chỉ số ký tự Unicode trong `text_raw`, tính từ 0 và loại trừ `end`. Báo cáo lấy text trực tiếp từ byte extraction đã ghim và ghi hash cả chuỗi raw của block/ô. Span cần nằm trong một block hoặc ô. Các khoảng trên cùng nguồn phải rời nhau. Hai mảnh thuộc cùng biểu thức qua nhiều nguồn có thể được lưu riêng để rà tiếp.

`reference_id` chỉ dùng sau khi rà quan hệ với một tham chiếu đã khóa hash trên cùng trang. Block hoặc ô cần có bbox riêng hợp lệ và giao với vùng tham chiếu. `table_fallback` chỉ đủ để lưu dấu vết. Một liên kết không được thay prediction đã căn tự động. Báo cáo giữ bbox ở cấp block/ô và `formula_bbox: null`. Liên kết có thể cung cấp nội dung `TEXT` cho cặp công thức. Các số TP/FP/FN định vị vẫn tính riêng cho output công thức tự động. [Bộ chấm TEXT và critical](FORMULA_CONTENT_V7.md) · [Replay bốn span thực tế](../../scratch/dev_sessions/20261104-formula-embedded/replay/alignment.json) · [Manifest quan sát](../../scratch/dev_sessions/20261104-formula-embedded/pilot-embedded-observations.json).

Pilot phát triển có ba ảnh trang vật lý AGR 2022 trang 38, 43 và ASM 2022 trang 67. Hai người nhận riêng gói A/B, điền từ ảnh rồi chuyển điều phối viên giữ hai bản gốc. Người C đọc ảnh sau khi niêm phong A/B. Dùng `formula_annotations export` để xuất tham chiếu có hồ sơ A/B/C. Các gói hiện để trống. [Gói A](../../scratch/dev_sessions/20261104-formula-human-custody/pilot-cong-thuc-A.zip) · [Gói B](../../scratch/dev_sessions/20261104-formula-human-custody/pilot-cong-thuc-B.zip) · [Hướng dẫn](../ground_truth_tools/FORMULA_ANNOTATION_V7.md).
