# Đặc tả nghiệm thu bảo toàn dấu tiếng Việt 99,99%

Ngày 04/11/2026, Asia/Bangkok. Yêu cầu thiết kế là đạt ít nhất 99,99% bảo toàn dấu ở từng luồng, đồng thời đếm đúng keyword nguyên văn. Khóa tiêu chí và chia mẫu trước khi mở holdout. Trạng thái nghiệm thu hiện tại là `NOT_EVALUATED`.

## Phạm vi đầu ra

| Luồng | Đầu ra được chấm | Đối chứng |
| --- | --- | --- |
| OCR | `result.md` từ `unified_gpu_full_ocr`, gồm chữ hiển thị trong bảng | Bản chép từ ảnh, có trang và vùng/ô |
| Native | Bản sao lớp chữ PDF do `NativeTextExtractor` đọc qua PyMuPDF, trước và sau NFC | Cùng bản chép từ ảnh khi áp dụng, kể cả PDF lỗi font mapping |

Native phục vụ chẩn đoán và kiểm bản sao. Pipeline OCR sản phẩm tiếp tục dùng CUDA trên mọi trang. NFC chỉ hợp nhất mã Unicode tương đương. Khi lớp chữ và ảnh bất đồng, lưu chữ thô, ứng viên, bbox và lý do review. Sửa chữ cần chứng cứ từ ảnh hoặc người kiểm. Giữ nguyên số, mã, tên riêng và nguồn.

Kết quả copy/paste bằng trình đọc PDF cụ thể cần một phép kiểm riêng, ghi tên và phiên bản trình đọc cùng nội dung clipboard. Mã trong dự án kiểm bản sao do bộ đọc của dự án tạo.

## Phép đo và điều kiện đạt

1. Đo dấu thanh, dấu tạo chữ và nét `đ/Đ` trên cặp đơn vị nguồn đã căn. Lỗi gate là lỗi `DER_VN_v1` cộng dấu tổ hợp tiếng Việt còn rời sau NFC ở đầu ra. Tính `1 − lỗi / vị trí dấu GT`. Đạt khi `lỗi × 10.000 ≤ vị trí dấu GT`, dùng số nguyên chưa làm tròn. Tính cả dấu thừa ở đơn vị GT không dấu. Thiếu bản chép, thiếu đầu ra, thiếu coverage, GT có dấu rời chưa phân xử hoặc mẫu số 0 cho trạng thái `NOT_EVALUATED`.
2. Báo CER/WER và lỗi dấu theo nhóm riêng. Báo riêng số liệu OCR, native raw, native NFC và sau review. Giữ lỗi theo từng PDF và nhóm khó, gồm sai ToUnicode, tổ hợp Unicode, chữ xoay, nhiều cột, bảng và chữ nhỏ.
3. Đếm trên đúng Markdown đã xuất bằng `literal_v1`. Chấm từng lần xuất hiện theo PDF, trang, vùng/ô và keyword. Báo đúng, thiếu, thừa và sai lệch từng keyword, kể cả khi tổng trước/sau bằng nhau. Gate bộ keyword nghiệm thu yêu cầu không thiếu và không thừa trong phạm vi đã gán nhãn đầy đủ. Đối chứng gồm `O2O`/`020`, cụm sai dấu, lặp thật và cụm bị tách qua cột hoặc ô.
4. Công bố tỷ lệ trên mẫu kèm số tài liệu, số dấu, số lỗi, coverage và khoảng tin cậy có tính đến phụ thuộc trong PDF/công ty. Mốc 10.000 dấu cho phép một lỗi trong tỷ lệ quan sát. Cỡ mẫu để khẳng định độ tin cậy phải tính riêng và khóa trước holdout. Chưa đủ thì chỉ báo kết quả mô tả.

## Thứ tự triển khai

1. Hoàn thiện phép đo và chặn trường hợp thiếu bằng chứng hoặc làm tròn khiến đạt giả. Đo riêng từng luồng trên cùng cấu trúc dữ liệu đầu vào.
2. Chuẩn bị GT từ ảnh với hai người chép độc lập và phân xử. Khóa hash PDF, vùng, quy tắc ký tự, danh sách keyword, train/dev/calibration/holdout theo PDF/công ty và giao thức chọn mẫu. Dùng lỗi đã biết làm tập phát triển.
3. Chạy baseline OCR và native, phân lỗi theo nhận dạng, font mapping, chuẩn hóa và ghép Markdown. Thử thay đổi trên dev/calibration. Chỉ sửa native khi có bằng chứng hình ảnh và giữ bản sao gốc.
4. Khóa candidate, model/config/runtime, chạy holdout ở output mới. Áp cả hai gate dấu và gate keyword, bảo toàn số, bảng và provenance. Phát hành kết quả cùng báo cáo tái lập, review và kiểm vận hành theo các mục còn mở của [bộ tiêu chí benchmark](07_BO_TIEU_CHI_BENCHMARK_OCR.md).

Dùng mẫu nháp để ghi một vùng hoặc ô, hai bản chép độc lập và kết quả phân xử. Mỗi lần xuất hiện keyword cần ID riêng, keyword canonical và vị trí trong vùng. Để `null` khi chưa kiểm. Chỉ ghi danh sách rỗng sau khi đã rà toàn bộ vùng. [Mẫu phiếu gán nhãn](templates/diacritic_annotation.example.json).

## Phần triển khai đã có

Gate điểm quan sát nhận JSON với `expected_ids` là danh sách ID vùng đã khóa, `references` là map ID → bản chép từ ảnh và `predictions` chứa các map cùng ID dưới `ocr_markdown`, `native_raw`, `native_nfc`. Giá trị `null` hoặc ID thiếu biểu thị thiếu dữ liệu. Chuỗi rỗng biểu thị đầu ra được quan sát nhưng không có chữ. Lưu manifest nguồn và cách căn ID cùng JSON đầu vào.

```powershell
.venv/Scripts/python.exe -m benchmark.scientific_evaluation.diacritic_acceptance scratch/diacritic_pairs.json
```

CLI in báo cáo cho ba luồng. Exit 0 khi OCR và native NFC đạt điểm quan sát, exit 1 nếu một trong hai không đạt hoặc thiếu dữ liệu. Native raw là baseline chẩn đoán. CLI này kiểm riêng ngưỡng dấu.

Gate phát hành v7.0 nay nối source count OCR với điểm quan sát 99,99%, gồm dấu thừa ở vùng GT không dấu và dấu còn rời sau NFC. Native được đo lại từ PDF đã ghim và scope áp dụng nằm trong GT manifest đã khóa, kèm kế hoạch precision theo công ty. Thiếu scope/GT/plan giữ `NOT_EVALUATED`; không lấy báo cáo CLI tự khai làm prediction nguồn. Raw, bbox, producer ref và danh tính bộ đọc được giữ. [Cách chuẩn bị và giới hạn](../benchmark/scientific_evaluation/NATIVE_DIACRITIC_RELEASE_V7.md).

Khi corpus có cả trang scan, trường `native_expected_ids` chỉ định tập con vùng có lớp native text theo manifest đã khóa. Nếu bỏ trường này, cả ba luồng dùng chung phạm vi. Phải chọn tập con theo khả năng áp dụng trước khi xem kết quả, kể cả vùng có lớp chữ sai.

Chữ OCR được chuẩn hóa định dạng qua `UnicodeNormalizer.normalize_ocr_text`, bỏ áp dụng bảng suy đoán font và từ. Bản sao native chỉ áp NFC, giữ raw từ span và gắn review nếu nghi sai font mapping. Lớp chữ thực sự mất dấu vẫn cần đối chiếu ảnh để phục hồi. Các phép đo DER dùng NFC nên raw và NFC tương đương khi chỉ khác cách biểu diễn Unicode.

Test gate mã cuối đạt 11 ca. CLI được kiểm thêm trên fixture có vùng scan và vùng native, cùng fixture có native sai dấu. Chẩn đoán PyMuPDF trên VIC 37, VIC 46 và AAA 125 xác minh hash PDF, lưu bản raw/NFC. Hai dòng thay biểu diễn NFC và số đếm ba keyword kiểm giữ nguyên. [Nhật ký và artifact](../scratch/dev_sessions/20261104-diacritic-acceptance/session.md).

## Đối chiếu từng lần xuất hiện keyword

`benchmark.scientific_evaluation.keyword_acceptance` đọc đúng `result.md`, `keyword_counts.json` và snapshot từ điển của một tài liệu đã xuất. Inventory kiểm hash và đếm lại bằng cùng matcher với `literal_v1`. Phạm vi offset là ký tự Unicode trong chuỗi đã chuẩn hóa BOM, xuống dòng, NFC và casefold. Offset bắt đầu từ 0, loại trừ vị trí cuối.

```powershell
.venv/Scripts/python.exe -m benchmark.scientific_evaluation.keyword_acceptance output/RUN/DOC output/RUN/keyword_dictionary.snapshot.json
.venv/Scripts/python.exe -m benchmark.scientific_evaluation.keyword_acceptance output/RUN/DOC output/RUN/keyword_dictionary.snapshot.json --ground-truth scratch/keyword-gt.json --alignment scratch/keyword-alignment.json
```

- File GT dùng schema `keyword-source-gt-v1`. Trường `identity` chứa `document_id`, `pdf_sha256` và `dictionary_sha256` từ inventory. Danh sách `units` ghi `unit_id`, `physical_page`, `coordinate_space`, `bbox`, `table_cell_id` khi áp dụng, `transcription` đã phân xử và `keyword_occurrences`. Mỗi lần xuất hiện có `id`, `keyword_id`, `start`, `end` trong bản chép sau NFC và casefold. Dùng `null` khi chưa rà và `[]` khi đã rà, không có keyword. Lưu hai bản chép độc lập và hồ sơ phân xử kèm GT.
- File căn nguồn dùng schema `keyword-source-occurrences-v1`. Sao chép toàn bộ `identity` từ inventory, ghi SHA-256 nguyên file GT trong `ground_truth_sha256` và ID người rà trong `reviewed_by`. Mỗi dòng `attributions` sao chép `keyword_id`, `start`, `end` của một match Markdown. Ghi `unit_id` của vùng nguồn và `reference_id` của lần GT tương ứng nếu có. Match ngoài phạm vi ghi `unit_id: null` cùng `outside_scope_reason`. Người rà căn nguồn từ ảnh, vị trí Markdown và evidence extraction, gồm các vùng không có match và các bản lặp cùng keyword. Bộ chấm kiểm tính đầy đủ và nhất quán của liên kết đã cung cấp.
- Kết quả chấm phạm vi đã khai báo trả exit 0 nếu mọi lần khớp một-một, exit 1 nếu thiếu hoặc thừa, exit 2 nếu chưa đủ coverage hoặc input không hợp lệ. Chênh lệch tổng bằng 0 vẫn có thể có lần thiếu và lần thừa. Nghiệm thu còn cần kiểm tính độc lập của nhãn, tính đúng của căn nguồn và giao thức holdout.

Cổng phát hành v7.0 bắt buộc khai báo `keywords` và có đơn vị mẫu `keyword_recall`. `quality.keyword_occurrence_gate` chấm riêng lỗi thiếu/thừa từ source count đã tính lại, gồm vùng đã xác nhận không có keyword. Bất kỳ lỗi nào cũng làm gate trượt dù recall đạt ngưỡng hoặc không suy giảm. Thiếu record, thiếu số đếm lỗi hoặc count mâu thuẫn giữ `NOT_EVALUATED` và tổng lỗi chưa biết là null. Các phép đo thành phần vẫn có thể bỏ keyword nếu không công bố nghiệm thu toàn v7.0. [Mã gate](../benchmark/scientific_evaluation/release_gate.py) · [Phản ví dụ và hồi quy](../scratch/dev_sessions/20261105-v70-release-readiness/session.md).

`Doi_Chieu/keyword_counts_filled.xlsx` là chuẩn tổng đếm theo PDF và keyword do người dùng chỉ định. Dùng workbook để khoanh các ô lệch và chọn ca rà. Schema workbook hiện có một sheet với tên PDF và tổng đếm, nên phần vị trí phải bổ sung từ ảnh và lưu riêng. [Kết quả đối chiếu và hồ sơ pilot](../scratch/dev_sessions/20261104-keyword-occurrence/session.md).
