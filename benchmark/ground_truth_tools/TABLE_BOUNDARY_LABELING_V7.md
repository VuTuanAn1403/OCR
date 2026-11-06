# Phiếu L5 cho vùng ngắt giữa hai trang

Mỗi người chỉ mở gói dành cho vai trò của mình. Gói chứa ảnh cắt nguồn, trang vật lý của ảnh và phiếu trống. Hai người A/B đọc ảnh riêng, giữ phiếu riêng đến khi nộp. Người C được xem phiếu A/B đã khóa và đọc lại ảnh. Mọi vai trò giữ nguyên dấu, số 0 đầu, dấu âm, phần trăm và đơn vị khi chép.

Với mỗi `pair_id`, mở ảnh có `side: previous` và `side: next` theo `source_manifest.json`. Ghi `source_reason` mô tả dấu hiệu nhìn thấy ở vùng ngắt. Các lựa chọn cho `relationship` gồm `SAME_TABLE`, `DIFFERENT_TABLES`, `NOT_A_TABLE` và `UNCERTAIN`. Nếu khác bảng, ảnh chỉ là đoạn văn hoặc chưa rõ quan hệ, để `boundary`, `column_count`, `repeated_header_rows`, `cell_links` là null.

Nếu cùng bảng, ghi `boundary` là `BETWEEN_ROWS` khi ngắt giữa hai hàng, `SPLIT_ROW` khi hai trang chứa cùng một hàng hoặc `SPANNING_CELL` khi một ô gộp kéo qua điểm ngắt. Nếu chưa rõ, ghi `UNCERTAIN` và giữ ba trường còn lại null. Khi xác định được ranh giới, đếm số cột logic và số hàng tiêu đề in lại ở đầu mảnh sau. Ghi số 0 chỉ khi xác nhận không có hàng tiêu đề in lại.

`cell_links` là danh sách liên kết từng ô có mảnh quan sát ở cả hai trang. Với `BETWEEN_ROWS`, ghi `[]`. Với `SPLIT_ROW`, ghi `[]` nếu hai mảnh thuộc cùng hàng nhưng không có ô chia đôi. Với `SPANNING_CELL`, phải xác định được ít nhất một liên kết hoặc chọn `UNCERTAIN`. Ví dụ dưới đây chỉ minh họa lược đồ. Tọa độ và chữ lấy trực tiếp từ ảnh cần gán nhãn.

```json
{
  "column": 2,
  "column_span": 1,
  "previous": {"image_id": "previous-1", "bbox_xyxy_px": [40, 25, 230, 80], "state": "OBSERVED_TEXT", "text_raw": "mảnh đầu"},
  "next": {"image_id": "next-0", "bbox_xyxy_px": [40, 60, 230, 96], "state": "OBSERVED_TEXT", "text_raw": "mảnh sau"}
}
```

Cột bắt đầu từ 0. Bbox là `[trái, trên, phải, dưới]` theo pixel ảnh PNG được chọn, gốc ở góc trái trên. Mở ảnh ở kích thước gốc khi đo. Ghi `OBSERVED_EMPTY` và `text_raw: ""` khi nhìn thấy ô thực sự rỗng. Nếu thiếu ảnh để đọc chính xác mảnh ô thì giữ ranh giới `UNCERTAIN` và ghi lý do. Không điền dựa vào dữ liệu OCR hoặc bảng ghép thử.

Khi nộp, điền `actor_type: "HUMAN"`, `annotator_id`, `submitted_at` có múi giờ, `source_images_checked: true`, `no_predictions: true` và đổi `status` thành `SUBMITTED`. A/B chỉ điền `no_peer_before_submission: true` khi đúng với cách đã làm. Vai trò C giữ trường đó null vì đã đọc hai phiếu sau khi khóa. C ghi lý do cho từng quyết định, kể cả khi giữ nguyên nhãn A/B.
