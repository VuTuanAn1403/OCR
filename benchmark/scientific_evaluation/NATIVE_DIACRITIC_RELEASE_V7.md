# Gate bảo toàn dấu OCR và bản sao native v7.0

Gate phát hành áp đặc tả 09 cho OCR và native NFC. Source counts OCR giữ cả lỗi dấu thừa ở vùng GT không dấu; `diacritic_gate` ghi dấu tổ hợp còn rời sau NFC. GT còn dấu rời giữ `NOT_EVALUATED`. Từ 09/11 (V8-022), gate OCR dùng cận trên Clopper-Pearson một phía của `gate_errors / reference_diacritics` trên số nguyên chưa làm tròn (`exact_bounds.py::upper_bound_gate`, design effect đã khóa trong `plan.ocr_diacritics`). Điều kiện cũ `gate_errors × 10000 <= reference_diacritics` chỉ còn là `point_status` trong `diacritic_acceptance.py`. Từ 10/11, số lỗi của cổng là `dser_errors` của `DSER_strict` trên `ref_slots` (đặc tả 04 §3). DER_VN_v1 chỉ được báo bên cạnh trong `der_vn_v1`. DER có thể lớn hơn 1 khi nhiều dấu được thêm vào mẫu ít dấu; không chặn về 1.

Nhánh native đọc PDF gốc được ghim hash bằng `NativeTextExtractor`, giữ raw và chỉ áp NFC. Prediction native không nhận từ file chữ do người gọi tự khai. Phạm vi hiện hỗ trợ các đơn vị text toàn trang vật lý (`region_id: page`) trong mẫu DER đã khóa. Các ô/bảng trên trang nằm trong bản chép đầy đủ của trang; không dùng phiếu keyword từng vùng để giả thành GT toàn trang.

## Khóa danh tính bộ đọc và phạm vi áp dụng

```powershell
$env:PYTHONPATH = ((Resolve-Path .).Path,(Resolve-Path src).Path -join ';')
.venv/Scripts/python.exe -B -m benchmark.scientific_evaluation.native_diacritic_replay `
  --runtime-report scratch/native-reader-runtime-new.json
```

CLI chỉ ghi danh tính: Python executable/version, file Python và binary của PyMuPDF, mã extractor. Hash không chứng minh accuracy. Ghi `runtime_sha256` vào phạm vi native trước holdout. Thay runtime cần protocol/output mới; không sửa hash để vượt kiểm.

Trong `ocr-scorecard-gt-v1` đã ghim ở `data.gt_manifest_sha256`, thêm `native_diacritics` theo schema `ocr-native-diacritic-scope-v1`. Nội dung cần chuẩn bị:

- `status: LOCKED`, `approved_by` trùng người duyệt protocol, `locked_at` có múi giờ và không sau thời điểm khóa protocol.
- `runtime_sha256` từ manifest bộ đọc đã được rà.
- `units` phủ đúng mọi `unit_id` có metric `der` trong mẫu. Mỗi mục có `unit_id`, `native_applicable` là boolean và `reason` đã kiểm.

Scope là một phần GT manifest nên được ghim trước khi mở holdout. Trang có đối tượng chữ PDF phải được đưa vào nhánh native kể cả lớp chữ lỗi ToUnicode hoặc font mapping. Gate đối chiếu cấu trúc `get_texttrace`, chặn việc khai không áp dụng để bỏ trang native sai. Trang scan không có đối tượng chữ được giữ trong scope với `native_applicable: false`. Corpus native không có mẫu số dấu vẫn chưa đánh giá theo đặc tả 09.

Cảnh báo parser được giữ theo trang và giai đoạn đọc. Trang có cảnh báo không được xác nhận là native hay scan chỉ từ một kết quả parse dở, kể cả khi scope đã khai không áp dụng. Gate giữ `NOT_EVALUATED` cho phần chưa kiểm này. Không sửa PDF hoặc receipt để làm mất cảnh báo.

GT transcript dùng `documents[document_id].text_pages[page]` với `path`, `sha256`, cùng PDF SHA-256 và trang vật lý như mẫu OCR. GT thiếu, dấu GT còn rời hoặc nguồn đổi giữ chưa đo/từ chối, không thành lỗi 0.

## Khóa kế hoạch precision và đọc kết quả

Trong `ocr-sample-precision-plan-v1` đã ghim, thêm `native_diacritics` có cùng cấu trúc một mục precision hiện có: `minimum_companies`, `minimum_documents`, `minimum_denominator`, `maximum_ci_width` và `power` gồm `target`, `pilot_company_influence_sd`, `detectable_gap`, `pilot_sha256`. Có thể khai `zero_event_company_risk_max`. Giá trị cần số đo calibration và người duyệt; không suy từ confidence OCR hoặc tự điền để qua gate.

`native_input_readiness` kiểm metadata và kế hoạch này trước khi gate đọc transcript hoặc tính count holdout của bất kỳ modality nào. Metadata thiếu giữ chất lượng `NOT_EVALUATED`; trạng thái file/hash hợp lệ ở preflight không tự cấp quyền bỏ qua điều kiện này.

Native NFC cần đồng thời đạt điểm quan sát 99,99% và CI lỗi phía trên không quá 0,0001. CI percentile tính theo công ty, báo rõ chưa hiệu chỉnh; không chạy NI giữa native copy và OCR. Kế hoạch power tính số phép đo trong họ đã khóa cộng phép kiểm native. Thiếu plan, thiếu cụm/mẫu số, CI suy biến/quá rộng giữ `NOT_EVALUATED`. Không suy rủi ro tổng thể bằng 0 khi mẫu không có lỗi. Raw là đối chứng chẩn đoán. CER/WER/DER của raw và NFC dùng cùng chính sách NFC nên có cùng số đếm khi chỉ khác biểu diễn Unicode; raw vẫn được giữ riêng cùng bbox/producer ref/hash.

Native dùng CI biên của tỷ lệ lỗi, không dùng CI chênh lệch raw–NFC: hai biểu diễn tương đương Unicode có chênh lệch bằng 0 theo định nghĩa. Báo cáo CI native chỉ xuất số đếm/phân bố cần cho phép kiểm tuyệt đối này.

`quality.diacritic_preservation_gate` ghi điểm OCR; `quality.native_preservation_gate` ghi raw/NFC, CI, counts, scope bị loại theo manifest và provenance. Lỗi native chặn phát hành, kể cả khi các metric OCR và keyword đạt. Gate vẫn kiểm nguồn/count, nhãn độc lập, protocol và vận hành theo các yêu cầu khác.

Đã kiểm bằng PDF/GT tạo bằng chương trình và fixture thống kê. Chưa có phép đo nghiệm thu native hoặc OCR trên GT độc lập của chín PDF. [Đặc tả](../../cai%20tien%20v2/04_DAC_TA_DO_DAU_9999.md) · [Bộ chấm](native_diacritic_replay.py).
