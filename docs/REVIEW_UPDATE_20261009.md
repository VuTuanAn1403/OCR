# Review bản cập nhật V5 — 09/10/2026

**Kết luận: chưa nghiệm thu để nghiên cứu khoa học.** Bộ chỉ số có cải tiến được kiểm chứng, nhưng pipeline không import được; runner hồi quy còn có thể báo số liệu hoàn hảo khi không có dữ liệu. Chưa chứng minh độ chính xác và thời gian đạt đồng thời trên nhiều loại PDF.

Phạm vi: working tree hiện tại so với HEAD `bc187a1f90aadcc5d3448211f380fd21c6e75cf8`, gồm cả mã mới chưa được Git theo dõi. Đối chiếu `PROPOSAL_FIX_ACCURACY_RELIABILITY_PERFORMANCE.md` và yêu cầu PDF → Markdown đa loại. Review không sửa production code, không chạy lại toàn bộ batch. Các số liệu fixture bên dưới chỉ tái hiện lỗi logic, không phải độ chính xác hay tốc độ trên PDF thực.

## Kiểm chứng

- Nhóm scientific + unit metrics + regression runner: **26 passed**.
- Mở rộng `tests/unit tests/scientific`: **132 passed, 6 collection errors**, exit code 1. Cả sáu lỗi do `NameError: name 'Tuple' is not defined` trong `process_page.py`. Lần chạy hoàn chỉnh đã khắc phục quyền thư mục tạm của Windows; không tính lỗi sandbox vào lỗi sản phẩm.
- Import trực tiếp `ProcessPageUseCase` thất bại cùng nguyên nhân.
- Cả 9 ca supervisor acceptance trước đây thất bại nay đạt. Ghép GT đúng tài liệu, trang thiếu prediction, mẫu số trang chạy một phần, Markdown cuối, DER, reading order và TEDS đã vượt qua các ca đó. Đây là kiểm chứng logic, chưa phải nghiệm thu pipeline thực.
- Ablation đã bỏ các hệ số tự tạo, chỉ xuất hàng dữ liệu được cung cấp. Chưa có thực nghiệm chạy từng biến thể để kết luận đóng góp của từng thành phần.

## Các lỗi cần sửa

### 1. [P1] Pipeline không khởi động được

`src/ocr/application/process_page.py:692` dùng `Tuple[bool, Optional[str]]`, nhưng dòng 7 không import `Tuple` và module không trì hoãn đánh giá annotation. Python lỗi khi định nghĩa class. CLI phụ thuộc module này và sáu module test không nạp được.

Sửa import/annotation; kiểm chứng import và các test đang bị chặn, sau đó chạy một PDF thật. Kết quả kiểm thử riêng metric không thay thế kiểm chứng khởi động.

### 2. [P1] Nhánh loại OCR confidence thấp tạo EvidenceBlock sai schema

`process_page.py:339` truyền `source="primary_ocr"`; dòng 1260 truyền `source="image_ocr"`. `src/ocr/domain/models/evidence_block.py:22` chỉ chấp nhận `native`, `ocr`, `vector`, `image`. Cả hai constructor probe đều trả Pydantic ValidationError.

Sau khi sửa lỗi import, chỉ cần gặp dòng bị loại là nhánh lưu bằng chứng có thể làm hỏng xử lý trang. Dùng giá trị nguồn hợp lệ hoặc cập nhật schema và các consumer nhất quán. Kiểm chứng một trang có cả dòng được giữ và dòng bị loại: vẫn xuất Markdown, JSON giữ bằng chứng cùng lý do.

### 3. [P1] Không có GT và prediction vẫn nhận chỉ số hoàn hảo

`scripts/run_regression.py:153–162` tự tạo GT và prediction giống nhau, rồi đưa vào aggregate và lịch sử benchmark. Probe với cả hai thư mục không tồn tại trả `evaluated_count=1`, CER/WER/DER = 0, Numeric Accuracy = 1, `has_regression=false`.

Dù console ghi synthetic verification, schema kết quả không cách ly self-test khỏi benchmark thật; nó còn có thể trở thành baseline. Khi thiếu dữ liệu phải báo NOT_MEASURED/NO_GROUND_TRUTH, không đưa self-test vào lịch sử thực nghiệm. Self-test nên là unit test riêng.

### 4. [P1] Runner hồi quy không tìm thấy Markdown do pipeline xuất

`scripts/run_regression.py:116` chỉ tìm `page_01.md`, `page_0001.md`, `page_1.md`. Export thực tại `src/ocr/application/export_document.py:52` dùng `pages/page-0001.md`. Fixture `pred/doc/pages/page-0001.md` và GT stem `doc_page_0001` trả `None`, nên runner áp phạt 100% dù có đúng prediction.

Dùng hợp đồng tên file chung và khóa tài liệu/trang chính xác. Bỏ ghép bằng substring toàn đường dẫn để tránh nhầm tài liệu có tên gần nhau. Kiểm thử bằng cấu trúc thư mục export thực.

### 5. [P1] Lượt hồi quy thất bại trở thành baseline lần sau

`scripts/run_regression.py:239` lấy lần chạy cuối làm baseline, và dòng 274 ghi thêm kết quả kể cả khi đã phát hiện regression. Fixture GT `abc`: prediction `abc` tạo mốc; đổi thành `axc` báo regression; chạy lại nguyên prediction sai thì hết regression.

Tách lịch sử quan sát khỏi baseline đã chọn. Không tự thay baseline bằng lượt thất bại; giữ cùng manifest dữ liệu, profile và quy tắc đo. Đề xuất A3 yêu cầu ngưỡng **0,5 điểm phần trăm theo loại trang**, trong khi script mặc định 2 điểm và chỉ tổng hợp toàn tập.

### 6. [P2] Cắt prediction khiến chỉ số không đo toàn bộ đầu ra

`scripts/run_regression.py:78–84` bỏ phần prediction vượt `max(3 × len(GT), 5000)` trước mọi metric. GT `abc`, prediction `abc` + 6.000 ký tự `x`: CER toàn bộ = 2000, runner báo 1665,6667. Nội dung rác dài hơn giới hạn không còn bị tính lỗi.

Giữ toàn bộ prediction khi tính metric; nếu vượt giới hạn tài nguyên, báo không chấm được hoặc dùng thuật toán phù hợp. Không âm thầm thay dữ liệu được đánh giá.

### 7. [P2] Xét mục tiêu CPU có thể PASS sai

`scripts/run_scientific_benchmark.py:113–115` làm tròn trước khi so ngưỡng: fixture MIXED 1,8004 s/trang thành 1,8 và PASS. Dòng 101–108 bỏ qua bộ đếm mixed khi phân loại: một trang scan + một trang mixed bị gán SCANNED, nhận ngưỡng 2,5 s/trang; fixture 2 s/trang PASS dù tài liệu có trang mixed.

So thời gian chưa làm tròn; báo theo nhóm trang với mẫu số đúng và xử lý mixed rõ ràng. Giữ mục tiêu CPU đã chốt: native 0,05–0,15; mixed 0,8–1,8; scan 1,5–2,5 s/trang. Chưa có lượt chạy bản cập nhật chứng minh đạt đồng thời các mục tiêu này và độ chính xác độc lập.

### 8. [P2] GT một phần bị so với toàn bộ Markdown

`scripts/run_scientific_benchmark.py:183–185` nối tất cả GT có sẵn rồi so với cả `result.md`, không kiểm tra phủ đủ trang. Fixture có hai trang đúng, GT chỉ có trang 1: page CER = 0 nhưng final Markdown CER = 1,1875 do chữ đúng trang 2 bị tính là chèn thêm.

Chỉ chấm phạm vi có GT tương ứng, hoặc yêu cầu GT đầy đủ để chấm toàn tài liệu; báo tỷ lệ bao phủ. Vẫn phải giữ kiểm chứng riêng về mất nội dung trong Markdown cuối.

### 9. [P2] Header/footer lặp vẫn được in, phát hiện tần suất còn sai

`src/ocr/infrastructure/export/markdown_exporter.py:70–78` và 355–359 vẫn in mọi running header/footer; thay nhãn không đáp ứng A2 về giảm dòng lặp ≥ 90% và ẩn mặc định. Detector `export_document.py:116–126` đếm block thay vì số trang và lấy phần nguyên ngưỡng. Probe ba block trùng trên một trang của tài liệu 10 trang vẫn bị gán running header.

Đếm số trang riêng biệt, dùng ngưỡng làm tròn lên và kiểm tra vị trí; ẩn running header/footer mặc định, JSON giữ nội dung, có tùy chọn hiện lại. Đo mất nội dung trước khi bật lọc.

### 10. [P2] Queue chưa thu được rủi ro tại vùng

`src/ocr/cli/batch_runner.py:451–499` chỉ đọc page reports; mọi mục có `region_id=None`, chỉ giữ ba suspicious snippets. Nó không đọc các region mang `needs_fallback` và `failure_reason` do bất đồng số/hướng ở `process_page.py:1180–1203`. Các tín hiệu vùng này cũng không được cộng trực tiếp vào `review_required_count` tại dòng 547, nên có thể bị bỏ qua.

Xây queue từ evidence và region, giữ khóa file/page/region cùng lý do. Không đếm trùng snippet và aggregate như các vùng độc lập. Kiểm chứng ba vùng rủi ro khác nhau, gồm numeric disagreement.

### 11. [P2] Kiểm tra số trong vùng ảnh chưa bật cho balanced

Balanced đã có `fallback_only_on_review: true`, nên fallback toàn trang có đường chạy; không được kết luận toàn bộ fallback đã tắt. Tuy nhiên balanced vẫn thiếu `regional_retry_enabled`, còn nhánh đối chiếu OCR DPI cao của vùng ảnh tại `process_page.py:1159` mặc định false. `numeric_retry_threshold` chưa được đọc; toàn trang dùng 0,85 gán cứng.

Bật đối chiếu có điều kiện cho vùng có số confidence thấp theo A4, dùng cấu hình ngưỡng thực sự. Đo Numeric Accuracy cùng chi phí thời gian; không bật retry rộng mà chưa đo ảnh hưởng.

### 12. [P2] Timeout không ngắt được OCR đang treo

`process_page.py:198–225` chỉ kiểm tra thời gian trước khi gọi OCR vùng. Khi OCR đã bắt đầu rồi treo, kiểm tra này không được chạy lại để dừng nó; nhánh OCR toàn trang cũng không có deadline được cưỡng chế. Thêm giá trị 120/180 giây vào profile chưa đáp ứng R6.

Cần deadline có khả năng chấm dứt worker hoặc cơ chế timeout thực của engine; giữ bằng chứng lỗi và cho batch tiếp tục. Kiểm chứng bằng worker giả lập không trả kết quả, không chỉ kiểm tra elapsed trước lời gọi.

## Dữ liệu và bước nghiệm thu còn thiếu

Trong `benchmark/ground_truth` quan sát được bốn TXT CLW và một sample layout JSON; chưa có bộ regression_v1 đa loại được mô tả ở A3. Chưa có manifest chứng minh GT độc lập, khớp hash PDF/trang và phủ dữ liệu dùng để đo bản cập nhật. Không suy ra accuracy từ confidence hay quality_score. Không dùng số thời gian của bản chạy cũ để nghiệm thu code mới.

Ưu tiên sửa 1–2 để pipeline chạy được; 3–8 để số đo đúng; sau đó kiểm chứng 9–12 trên GT đa loại và benchmark CPU có cùng máy/profile/cache/phạm vi thời gian. Chỉ kết luận đạt khi chất lượng Markdown cuối, bảng, số, thứ tự đọc và thời gian đều có bằng chứng đo phù hợp.

## Hash mã đã kiểm tra

Các hash dưới đây định danh các file trọng yếu tại lúc chốt review, không phải manifest đầy đủ toàn repository.

```text
src/ocr/application/process_page.py
5742bfa167f90d9084de726ad628a1f9890989aee2a93f1b5c52b6968b8e6204
src/ocr/domain/models/evidence_block.py
be9dfb32f0c4ab182347588f53375a886c0e035ecf5f80ed0380dd1c768070cd
scripts/run_regression.py
98c716d039cb7d33c7e233c0c9eee75d46fc345915c9f5aa3d6699c0d6cb16ef
src/ocr/application/export_document.py
460c3a7823259f5f34395bbe2bed129d8ff9ade97a8af3976cbd1e94e5228191
scripts/run_scientific_benchmark.py
1d654ee079e488a46be24432bb71d83b1145c6d9fe20345e87e3db9c7e29c05d
src/ocr/infrastructure/export/markdown_exporter.py
4034c4a7cf6fdecfecce10803ddeb54efa2efa4b7dfca272e473d494022ed718
config/profiles.yaml
60ba443bf78b5aaf9b3dd1e946e922c62ce98e721901f24d8f544b9d99f5e977
```
