# Lấy mẫu giám sát drift cho BK-08

`drift_sampling` tạo danh sách trang để hai người đọc ảnh nguồn độc lập. Công cụ chỉ đọc các batch canonical đã acknowledge, kiểm lại danh tính PDF và phạm vi trang. Việc chọn mẫu dùng SHA-256 PDF, tầng khai báo từ nguồn và số trang vật lý. Điểm OCR, từ khóa, confidence và kết quả người rà không tham gia chọn.

## Chốt kỳ lấy mẫu

- Kế hoạch `ocr-drift-sampling-plan-v1` ghi `owner`, `interval_days`, `minimum_documents`, danh sách `strata` duy nhất, nội dung `escalation_trigger` và `independent_annotation_required: true`. Khi đã được duyệt, dùng `status: LOCKED`, `approved_by` và `locked_at` có múi giờ. Giữ nguyên byte bản nháp và lập file mới khi duyệt.
- Khung `ocr-drift-sampling-frame-v1` ghi `plan_sha256`, `purpose`, `curator`, `period_start` có múi giờ, `pages_per_document`, `minimum_new_documents` và danh sách `previous_pdf_sha256`. Với `MONITORING`, kế hoạch phải được khóa trước hoặc đúng đầu kỳ. Với `DEVELOPMENT_DRY_RUN`, có thể dùng kế hoạch nháp. Kỳ này và danh sách trước đó do curator cung cấp. Bộ đo không suy thời điểm nhập hệ thống hoặc tính đầy đủ lịch sử từ biên nhận OCR.
- `documents` ánh xạ đủ từng ID trong các batch sang `pdf_sha256`, `stratum` và `exclusion_reason`. Mỗi PDF thuộc một tầng trong plan, với lý do loại để `null`. Khi loại, để `stratum: null` và ghi lý do. Chốt phân tầng dựa trên nguồn đã được phép sử dụng trước khi xem dự đoán. PDF mới được hiểu là hash chưa có trong lịch sử đã cung cấp.

Bộ lấy mẫu xếp theo hash chứa phiên bản thuật toán, hash plan, đầu kỳ UTC và hash PDF. Nó lấy trước một PDF mỗi tầng, bổ sung theo mức tối thiểu PDF mới rồi bổ sung đến mức tối thiểu tổng. Số mẫu thực tế có thể vượt mức tối thiểu tổng để đủ các điều kiện. Mỗi PDF lấy đến `pages_per_document` trang, xếp theo hash có thêm số trang. Tài liệu ngắn lấy tất cả trang nếu có ít trang hơn yêu cầu.

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
.venv/Scripts/python.exe -B -m benchmark.scientific_evaluation.drift_sampling `
  --plan scratch/drift-plan.json --plan-sha256 <sha256-plan> `
  --frame scratch/drift-frame.json --frame-sha256 <sha256-frame> `
  --batch output/canonical-published --output scratch/drift-sample-new
```

Exit 0 báo `SAMPLE_PREPARED` và tạo hai phiếu trống. Exit 1 báo `INSUFFICIENT_FRAME`, ghi số thiếu theo tài liệu mới, tổng số và tầng, chỉ xuất báo cáo. Exit 2 báo hồ sơ sai hợp đồng. Dùng output mới nằm ngoài các batch. [Plan nháp](../../scratch/dev_sessions/20261105-drift-sampling/development-plan.json) · [Khung thử](../../scratch/dev_sessions/20261105-drift-sampling/development-frame.json).

## Gán nhãn và đọc kết quả

Gửi riêng từng phiếu cho người A hoặc B. Mở đúng PDF theo SHA-256, xem trang vật lý từ 1 và chép từ ảnh. Giữ nguyên dấu, số, ký hiệu công thức và vị trí cần phân xử. Hai người nộp riêng bản hoàn tất, danh tính, thời điểm và xác nhận độc lập. Người C xem ảnh và hai bản nộp, giải quyết bất đồng và ghi quyết định theo từng trang. Chỉ sau phân xử mới đem dự đoán vào đối chiếu. Lưu byte hai bản nộp và bản phân xử cùng worklist. Phiếu mẫu chưa phải GT và CLI này chưa kiểm hồ sơ nộp hay tính drift.

Lượt thử chọn 4 PDF và 8 trang từ 7 PDF development. Hai PDF chờ curator bị loại. Tầng thử chỉ chia theo năm báo cáo, không chứng minh độ phủ các kiểu scan, bảng hoặc công thức. Trạng thái chất lượng giữ `NOT_EVALUATED`. [Worklist thử](../../scratch/dev_sessions/20261105-drift-sampling/development/worklist.json).
