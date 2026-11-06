# Đo retry trên ảnh nguồn v7.0

`retry_effects.summarize_retry_effects` đối chiếu bản đọc trước/sau với cụm đích có nhãn, kiểm coverage/hash ảnh và việc giữ raw/bbox/source ID. Báo riêng mẫu số dòng vốn sai, dòng vốn đúng, dòng sửa đúng, sửa hỏng và chưa sửa. Mẫu số thiếu giữ null. Dấu, số và công thức không được suy độ đúng từ confidence hoặc tổng test.

Phép đo phát triển ngày 05/11/2026 nằm tại [phiên recognition-gaps](../../scratch/dev_sessions/20261105-recognition-gaps/session.md): 38 crop thật, gồm sáu O2O và 32 dòng dấu, so crop 180/300/400 DPI và replay retry trên bản primary đã lưu. Đây là replay từng crop, chưa đo budget toàn trang. Hai crop mờ không có nhãn chắc chắn; 36 nhãn còn lại là AI sơ bộ, không blind và chỉ chấm cụm từ đích. Độ đúng toàn dòng và GT độc lập giữ `NOT_EVALUATED`.

Ở các nhãn sơ bộ đủ rõ, 300 DPI sửa 6/15 dòng sai, 400 DPI sửa 5/15; 15/15 dòng vốn đúng giữ cụm đích. Sáu O2O vẫn không được model đọc đúng ở hai DPI; đề xuất ngữ cảnh chỉ chuyển review, không thay số. Đối chứng số `020` đứng riêng trên PDF thật còn thiếu. Không công bố đây là accuracy nghiệm thu hoặc khuyến nghị đổi mặc định sang 400 DPI.

`rotation-probe-results.jsonl` trong phiên giữ 152 cặp dự đoán trên cùng pixel từ 38 crop x bốn góc. Góc 180° có 0→7/36 crop đủ nhãn khớp cụm đích với ngưỡng 0,90; các góc khác không tăng ở phép đo này. Đây là chỉ số cụm từ trong mẫu chọn có chủ đích, không chứng nhận hướng/toàn trang/ownership ô. Pipeline 36 trang dẫn xuất từ chín PDF đã hoàn tất, audit có coverage đầy đủ và `NEEDS_REVIEW`; độ đúng trên GT độc lập vẫn chưa đánh giá.

Worker diagnostic dùng `.venv-v62/text`, detector/recognizer khóa từ profile chuẩn, bắt buộc CUDA và audit forward/operator placement. Nó không tạo publication giả cho crop. Output sản phẩm chỉ qua `ocr_pipeline.cli.main`, profile chuẩn, mọi trang, A/B/export tuần tự. Đầu ra cũ giữ nguyên; input/model/runtime/code được ghim trong request và bản lưu của lượt chạy.

Nhãn người A/B độc lập và C phân xử tiếp tục là điều kiện nghiệm thu theo [hướng dẫn nhãn](../ground_truth_tools/ANNOTATION_V6.md). Không gán vai trò người cho AI, không biến nhãn sơ bộ thành GT hoặc tự điền chữ ký/duyệt protocol.
