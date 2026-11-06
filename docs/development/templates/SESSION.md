# Nhật ký phiên <id>

Mẫu chưa có kết quả. Lưu bản điền tại `scratch/dev_sessions/<id>/session.md`; HANDOFF chỉ giữ tóm tắt hiện hành. Không dùng placeholder như bằng chứng.

- Thời điểm và múi giờ: <...>
- Mục tiêu / điều kiện hoàn tất: <...>
- Phạm vi / ràng buộc: <...>
- HEAD và snapshot đầu/cuối: <đường dẫn start.json, end.json>
- File có thay đổi trước phiên cần bảo toàn: <...>

## Kết quả và bằng chứng

| Mệnh đề cụ thể | Trạng thái | Nguồn / lệnh / exit code / artifact | Phạm vi và giới hạn |
| --- | --- | --- | --- |
| <...> | NOT_EVALUATED | <chưa chạy hoặc thiếu gì> | <...> |

Kết quả đo dữ liệu cần input hash/manifest, trang/block/ô và config/code/model/runtime hoặc receipt nhận dạng chúng. Ghi phạm vi focus hash; không gọi đó là fingerprint toàn pipeline. Bằng chứng bị ignore phải ghi vị trí lưu/bàn giao; không còn artifact thì đánh dấu cần kiểm lại.

## Thay đổi và quyết định

- File/ký hiệu thay đổi và tác dụng: <...>
- Quyết định, lý do và nơi cập nhật thiết kế chuẩn nếu có: <...>
- Điều kiện nghiệm thu đạt/tổng và phần chưa đạt: <...>
- Giới hạn chưa kiểm, lỗi còn mở và cách tái hiện: <...>
- Bước kế tiếp: <việc cụ thể + file + cách kiểm>

## Số đo phiên

| Chỉ số | Giá trị | Nguồn |
| --- | --- | --- |
| Điều kiện nghiệm thu đạt/tổng | NOT_MEASURED | <tiêu chí được kiểm> |
| Phút dựng lại ngữ cảnh | NOT_MEASURED | <thời điểm bắt đầu/kết thúc> |
| Việc phải mở lại vì thiếu bằng chứng | NOT_MEASURED | <liên kết việc> |
| Token input / output thực | NOT_MEASURED | <thống kê công cụ, đúng phạm vi phiên> |
| Kích thước tài liệu khởi đầu | NOT_MEASURED | <suggested_startup_bytes trong snapshot; không phải token> |

Thiếu số đo giữ `NOT_MEASURED`. Không suy số token hoặc tỷ lệ tiết kiệm từ byte/ký tự; không dùng test đạt làm accuracy. Đối chiếu HANDOFF với trạng thái cuối trước khi rời phiên.
