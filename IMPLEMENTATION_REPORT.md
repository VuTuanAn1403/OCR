# Kiểm chứng kiến trúc hợp nhất OCR PDF

Ngày 23 tháng 10 năm 2026. Đã cập nhật working tree của dự án theo bản thiết kế được viết trước khi sửa mã. Chưa tạo commit. Bản Word cuối giữ thiết kế và bổ sung kết quả kiểm chứng này để người đọc có một tài liệu sử dụng thống nhất.

## Thay đổi đã triển khai

Chỉ một pipeline sản phẩm: OCR GPU toàn trang, Docling nhận bridge từ OCR, export CPU, một keyword finalizer, Excel riêng và SQLite cùng ma trận. Root CLI, console entry point, launcher tương thích và notebook chuẩn cùng dùng ocr_pipeline.cli. Profile cũ và backend legacy bị từ chối, không tự chuyển thuật toán theo tên file hoặc thiết bị.

config/profiles.yaml là nguồn cấu hình chuẩn với unified_gpu_full_ocr. Hai tên YAML theo phiên bản chỉ trỏ về cùng tệp; alias có vòng lặp, override hoặc khai báo mâu thuẫn bị từ chối. Worker không còn nhánh nhập ProcessPageUseCase hoặc hook export đếm từ khóa cũ; ngoại lệ import tương ứng đã được bỏ.

Hai môi trường text và Docling vẫn được giữ để tránh xung đột dependency của cùng pipeline. Baseline và helper lịch sử được chuyển vào benchmark/baselines, tách khỏi lệnh vận hành. ConvertDocumentUseCase lịch sử từ chối cấu hình sản phẩm mặc định. Tiện ích đếm riêng dùng recount hoặc analysis có xác minh, cùng quy trình công bố.

## Kết quả kiểm thử

| Kiểm chứng | Kết quả | Phạm vi thực tế |
|---|---|---|
| Unit scientific và tương thích | 1316 đạt và 1 bỏ qua | Không có failure hoặc error |
| Kiểm bị bỏ qua | Symlink venv Linux | Không áp dụng trên Windows |
| Thời gian pytest | Khoảng 318 giây | Một lượt toàn bộ sau sửa |
| Import contracts | Đạt | Nằm trong bộ kiểm toàn bộ |
| Packaging | Đạt kiểm layout cài đặt mô phỏng | Không phát hành wheel mới |
| Preflight CUDA | CAPABILITY_READY | Hai runtime model hiện có |
| Model hash | Đạt 34 tệp registry | Kiểm trong prepare_backend thật |
| Smoke GPU | SUCCEEDED | PDF tổng hợp một trang |
| Audit extraction | GPU source PASS và completion hợp lệ | Đủ một trang và không lỗi validation |
| Resume | Không OCR lại | Giữ revision 1 và mọi artifact tài liệu |
| Analysis từ khóa mới | SUCCEEDED | Nguồn giữ nguyên và count 1 1 0 |

Lệnh kiểm hồi quy đã chạy:

```powershell
.\.venv\Scripts\python.exe scripts/run_pytest_scratch.py `
  tests/unit tests/scientific tests/legacy_compat `
  -q --capture=fd --tb=short
```

Evidence pytest nằm tại scratch/runs/20261023-213124-716eef08, gồm run.json, log và JUnit. Một cảnh báo deprecation của dependency gdown không làm lỗi kiểm thử. Các bài kiểm dùng double hoặc fixture chỉ chứng minh hợp đồng và hành vi phần mềm; chúng không được tính là inference GPU thật.

## Lượt chạy GPU thật

Máy kiểm thử dùng NVIDIA GeForce RTX 2050, 4096 MiB VRAM và driver 592.00. PDF được tạo bởi scripts/smoke_unified.py, có tiêu đề tiếng Việt, câu chứa từ khóa và bảng hai năm. Đây là dữ liệu tổng hợp để kiểm đường thực thi, không phải corpus ground truth độc lập.

Detector ONNX, VietOCR và Heron ghi VERIFIED_INFERENCE trên CUDA. Pha B ghi VERIFIED_INFERENCE cho layout và bảng Docling; bridge không sao chép text layer native. Có một bảng được xuất sang Markdown. Mẫu không có công thức nên model công thức chưa được thực thi trong lượt smoke này.

Cả ba cây process text, structure và export được xác nhận đã thoát. Sau export, document owner tạo report và Excel riêng; batch công bố MA_TRAN_DEM_TU_KHOA_1_FILES.xlsx ở revision 1. Hai keyword canonical được đếm trong Markdown. Validation là NEEDS_REVIEW, không có error và có năm cảnh báo orientation chưa xác định ở vùng; đây không phải chứng nhận chất lượng nghiệp vụ.

Chạy lại với resume giữ nguyên 20 artifact của tài liệu, không phát sinh document request mới và không tăng revision. Analysis riêng với ba keyword chuyển đổi số, doanh thu và không có cho count tương ứng 1, 1, 0; kiểm hash xác nhận 20 artifact nguồn không đổi.

Lệnh smoke có thể tái sử dụng với output mới:

```powershell
.\.venv\Scripts\python.exe scripts/smoke_unified.py `
  --output output/unified_smoke
.\.venv\Scripts\python.exe scripts/smoke_unified.py `
  --output output/unified_smoke --resume
```

Evidence tổng hợp có thể kiểm bằng máy nằm tại benchmark/evidence/unified_architecture_20261023.json, gồm code fingerprint, lệnh pytest, thông tin GPU và kết quả. Chi tiết smoke, resume, audit và analysis ở scratch/unified_architecture_20261023. Các đường dẫn này là bằng chứng của máy kiểm thử hiện tại; không đóng gói model hoặc dữ liệu cache vào tài liệu Word.

## Giới hạn nghiệm thu

Đã xác nhận kiến trúc hợp nhất chạy qua các bước chính trên một PDF mẫu thật trên GPU. Chưa đo CER/WER, độ chính xác số, TEDS, reading order trên ground truth độc lập, chưa nghiệm thu corpus PDF thực dài hoặc tải 500 PDF. Model công thức cần một mẫu có công thức để kiểm inference riêng. Các trạng thái SUCCEEDED, PASS receipt và số bài kiểm đạt không thay thế những bước nghiệm thu đó.
