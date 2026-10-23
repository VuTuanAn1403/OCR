# Baseline nghiên cứu đã ngừng vận hành

Các YAML ở đây giữ hành vi lịch sử để test thuật toán và đối chiếu nghiên cứu.
Chúng không là profile của CLI sản phẩm. Cấu hình vận hành duy nhất nằm ở
`config/profiles.yaml`; xem `ARCHITECTURE.md` tại gốc repository.

`legacy_cli` giữ helper/parser/report cũ mà kiểm hồi quy còn cần import.
Không dùng các module này để chạy một batch mới. Mọi launcher được hỗ trợ
đều gọi `ocr_pipeline.cli` và báo lỗi khi dùng backend/profile đã ngừng.
