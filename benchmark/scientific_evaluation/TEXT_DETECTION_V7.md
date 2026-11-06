# Chấm detector chữ ở pha A

Phần này phục vụ BQ-04(b), tách detector chữ khỏi recognizer và layout. `text_detection_metric` chấm bbox của **mọi detection trên ảnh toàn trang trước retry**, kể cả detection không tạo được dòng chữ. Nó không dùng `blocks`, vùng layout, confidence hay số dòng sau nhận dạng làm GT hoặc làm tập prediction detector.

## Bằng chứng được lưu

Pha A ghi `metadata.primary_text_detection` trong JSON trang. Metadata được giữ qua pha B/export, nằm trong tập file mà receipt và completion nhận dạng. `primary-text-detections-v1` chứa:

- Adapter method thực tế, toàn bộ polygon/bbox/score trong thứ tự trả về và ID `d000000`… riêng từng trang.
- Kích thước ảnh HWC, kiểu uint8 BGR, SHA256 của **giá trị pixel theo thứ tự C** và phép đổi pixel sang điểm trang.
- `CAPTURED` với mảng rỗng khi detector thật trả rỗng; `UNAVAILABLE` với lý do khi không có telemetry hợp lệ. Hai trường hợp có ý nghĩa khác nhau.

Hash pixel không phải hash PDF hoặc byte file PNG. Để kiểm ảnh nguồn lưu PNG, đọc lại bằng BGR uint8 rồi dùng `ocr_recognition.detection_evidence.input_image_identity`. Ảnh strided được băm theo từng hàng, không cấp phát thêm cả trang. Hash input được lấy trước inference; bản chép polygon được lấy sau lần primary và trước regional retry. Thời gian lưu vết có trường riêng `primary_detector_evidence` trong durations.

Không điền bổ sung metadata này vào receipt cũ. Batch lịch sử thiếu snapshot giữ `NOT_EVALUATED` cho detector. Cần lượt OCR mới, được người dùng cho phép, để có snapshot của model thật trên các input đó. Việc lưu vết mới không đổi model, threshold detector, DPI hoặc quyết định chọn chữ.

## Chuẩn bị GT

Dùng cùng `structured-page-gt-v1` như scoreboard bảng/layout. Hai người A/B gán vùng chữ độc lập trên ảnh toàn trang rồi phân xử. Giữ polygon/bbox ban đầu, ảnh nguồn và lịch sử quyết định. Không dùng overlay prediction để tự sinh GT. Khóa định nghĩa đơn vị dòng/từ, trang được chọn, vùng ignore, matching và ngưỡng trước khi mở prediction nghiệm thu.

Thêm `text_detection_matching` ở cấp tài liệu:

```json
{
  "protocol": "primary-text-detection-bbox-v1",
  "iou_threshold": 0.5,
  "ignore_overlap": 0.5
}
```

Hai giá trị 0,5 ở ví dụ là lựa chọn cho phép chẩn đoán, chưa là ngưỡng nghiệm thu đã được duyệt. Đây là metric **bbox hull**, không phải polygon IoU, COCO AP hoặc kết quả ICDAR chính thức. Polygon nguồn vẫn được giữ cho adapter khác khi protocol yêu cầu.

Mỗi trang cần `coordinate_space: pdf_points_top_left`, `transforms: []` khớp extraction, cùng trường `text_detection`:

```json
{
  "input_image_sha256": "<SHA256 pixel BGR thực>",
  "regions": [
    {"id": "line-1", "bbox": [20, 30, 320, 45]},
    {"id": "ambiguous-1", "bbox": [400, 30, 450, 45], "ignore": true}
  ]
}
```

Đây là mô tả cấu trúc; thay ID/hash/bbox bằng nhãn thật. Bbox dùng điểm trang, được đổi từ ảnh gán nhãn bằng đúng phép `pixel_to_page`. Metric kiểm hash ảnh, số trang và kích thước, từ chối box GT ngoài trang. Frame sau xoay bổ sung chưa hỗ trợ được báo rõ, không tự bỏ qua phép biến đổi để chấm.

`regions: []` xác nhận không có vùng chữ cần chấm. `{"input_image_sha256": null, "regions": null}` nghĩa chưa gán nhãn. Vùng ignore phải có quyết định độc lập; không mở rộng ignore sau khi xem lỗi để nâng điểm.

## Chạy scoreboard

```powershell
.\.venv\Scripts\python.exe -B scripts/run_scientific_benchmark.py `
  --prediction output/BATCH/DOC --canonical-batch output/BATCH `
  --structured-gt benchmark/GT/DOC.structure.json `
  --output-dir scratch/detection-report-new
```

Thay đường dẫn bằng bundle đã khóa. Runner chỉ đọc/chấm đầu ra có sẵn; không chạy model. `--canonical-batch` kiểm PDF/receipt/SQLite/workbook/CUDA coverage và danh tính publication. Scoreboard detector ghim hash JSON trang, GT và extraction; kiểm lại trước khi trả báo cáo. Kết quả nằm trong `structured_scoreboard.text_detection` và từng `pages[].text_detection`.

Ghép một-một tối đa số cặp đạt IoU trước, sau đó tối đa tổng IoU. GT/prediction trùng nội dung hoặc trùng box vẫn có ID riêng. Prediction dư trùng một GT regular được tính FP. Chỉ prediction chưa ghép, không trùng regular và đạt tỷ lệ giao/diện tích prediction với vùng ignore mới được loại khỏi mẫu số. Box detector suy biến vẫn được giữ và tính FP.

TP là số cặp ghép; FP là prediction còn dư; FN là GT regular chưa ghép. Precision = TP/(TP+FP), recall = TP/(TP+FN), Hmean = 2TP/(2TP+FP+FN), theo mẫu số có nghĩa. Khi toàn bộ GT regular rỗng, báo counts spurious và giữ rate null. Nếu thiếu snapshot hoặc nhãn trên một trang đã khai báo, counts tổng hợp và rate giữ null; `observed_counts` chỉ mô tả phần đã chấm được.

## Giới hạn nghiệm thu

Đây mới là một phần của BQ-04. Recognizer trên GT crop, spotting, CER toàn pha A và CER artifact cuối cần các tập dự đoán/nhãn đúng công đoạn. Không coi detection tốt là chữ đúng. Fixture, hash khớp hoặc `MEASURED` không cấp accuracy; `quality_acceptance_status` luôn `NOT_EVALUATED`. Số điểm thật cần protocol/GT độc lập, paired theo cùng input và thống kê đã duyệt. Các cổng phát hành hiện hành chưa tự nhận metric này làm ngưỡng được phê duyệt.
