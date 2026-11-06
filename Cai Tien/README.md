# Cải tiến OCR PDF

Cập nhật 03/11/2026, Asia/Bangkok. Tổng hợp từ các đợt kiểm chứng trong `Test case`; đây là hồ sơ vấn đề và kế hoạch, không phải biên bản đã sửa xong phần mềm.

Mốc tiếp nối 04/11: [9 PDF, số đo được tận dụng, nhãn pilot và thứ tự hoàn thiện](10_TONG_HOP_9PDF_VA_NHAN_PILOT.md). Người dùng yêu cầu chưa chạy thêm OCR; SLO và GT nghiệm thu vẫn còn thiếu bằng chứng.

Đọc [bản tổng hợp điểm yếu và thứ tự cải tiến](01_TONG_HOP_DIEM_YEU_VA_LO_TRINH.md) trước. Bản này phân biệt lỗi tái hiện được, lỗi đã quan sát trên tài liệu, việc còn thiếu bằng chứng và sửa đổi lịch sử đã có kiểm thử.

- [Phương pháp làm việc với dự án lớn, nhiều dữ liệu](02_PHUONG_PHAP_LAM_VIEC_DU_AN_LON.md): chống kết luận thiếu nguồn, kết thúc phiên có kết quả kiểm được và nạp ngữ cảnh vừa đủ.
- [Hoàn thiện kế hoạch triển khai](04_HOAN_THIEN_KE_HOACH_TRIEN_KHAI.md): bốn điểm về trace kiểm thử, phụ thuộc GT/review, phiếu giao việc và phục hồi CSV. Đây là phần tổ chức thực hiện 23 việc hiện có; phần sửa lỗi và nghiệm thu vẫn còn mở.
- [Danh sách cải tiến có thể lọc](03_BACKLOG_CAI_TIEN.csv): đã phục hồi UTF-8 có BOM, 23 ID; byte/hash khớp bản gốc `0c3bddab…551d`. Trạng thái trong CSV là mốc lập backlog; cập nhật triển khai đọc tại báo cáo 06, không sửa trạng thái lịch sử để giả nghiệm thu.
- [Trace 65 ca kiểm](05_TRACE_KIEM_THU.csv): nối hai ma trận với test hiện có, loại kiểm, bằng chứng và phần nghiệm thu còn thiếu; test fixture đạt không đồng nghĩa TC khoa học đã đạt.
- Bổ sung v7.0 cho [tiếp nhận PDF](evidence/intake_trace_v70_20261104.json), [preflight CUDA](evidence/preflight_trace_v70_20261104.json) và các ca tiếp theo. Mốc [tách trích dẫn](evidence/pull_quote_trace_v70_20261104.json) có 61/65 ca kiểm kỹ thuật. Bộ chấm biến dạng và lưu detector chưa đóng các ca còn thiếu; chất lượng vẫn `NOT_EVALUATED`. CSV gốc giữ mốc lịch sử.
- [Detector trước retry](../benchmark/scientific_evaluation/TEXT_DETECTION_V7.md) đã có đường lưu/chấm bbox riêng; [kiểm kê chín PDF](../scratch/dev_sessions/20261104-primary-detection-evidence/saved-inventory.json) xác nhận cả 938 trang cũ thiếu snapshot gốc. Không lấy dòng nhận dạng làm prediction detector. [Nhật ký và wheel mới](../scratch/dev_sessions/20261104-primary-detection-evidence/session.md).
- [Kết quả triển khai và phần còn mở](06_KET_QUA_TRIEN_KHAI.md): trạng thái hiện hành của 23 việc, sửa mã, kiểm thử, chẩn đoán năm trang và điều kiện tiếp tục. Các mô tả “chưa sửa/CSV hỏng” trong bản 01/04 phản ánh thời điểm trước đợt triển khai này.
- [Bộ tiêu chí benchmark OCR và khoảng cách nghiệm thu](07_BO_TIEU_CHI_BENCHMARK_OCR.md): đối chiếu nguồn benchmark gốc, phân biệt đặc tả/mã chấm/kết quả GT; 14 tiêu chí, tám gói việc gắn backlog cũ và [mẫu protocol DRAFT](templates/benchmark_acceptance_protocol.example.yaml). Chưa đủ bằng chứng nghiệm thu tương đương các hệ thống lớn; 159 test evaluator đạt không là accuracy.
- [Cải tiến trực tiếp số đếm keyword trong Markdown](08_CAI_TIEN_MARKDOWN_KEYWORD.md): tiếp tục DC-03/04 bằng nối cột có trace và giữ cấu trúc nguyên tử. Có đối chiếu CPU trước/sau trên extraction đã kiểm integrity; không sửa batch cũ, không đổi phép đếm literal. Đây là trạng thái mã mới hơn báo cáo 06.
- [Đặc tả bảo toàn dấu 99,99%](09_DAC_TA_BAO_TOAN_DAU_9999.md) đặt gate riêng cho Markdown OCR và chữ sao chép native, kèm kiểm keyword theo vị trí nguồn.
- [Nghiệm thu công thức v7.0](11_NGHIEM_THU_CONG_THUC_V70.md) ghi phạm vi bắt buộc, CDM, căn vị trí, span block/ô, bộ đo TEXT và hồ sơ critical. Còn thiếu nhãn độc lập, rà critical thật và ngưỡng đã khóa.
- [GAP-03/DC-01/DC-02/TAB_05](12_GAP03_DC01_DC02_TAB05_V70.md): lượt GPU 36 trang xoay, đo retry trên 38 crop, tích hợp phép chiếu bảng tự động và các giới hạn còn mở; nhãn AI không thay GT người.
- [Kiến trúc đếm keyword 2 tầng và quy trình tự động hóa](13_KIEN_TRUC_DEM_KEYWORD_VA_QUY_TRINH_TU_DONG_HOA.md): phân tách OCR và từ điển đếm từ khóa, kiểm soát dấu tiếng Việt, chống ảo giác AI, quy trình Human-in-the-loop và hướng dẫn đổi/thêm từ khóa mới bằng CPU mà không cần OCR lại.
- [Chuẩn bị corpus và chấm cấu trúc](../benchmark/ground_truth_tools/ANNOTATION_V6.md#quy-trình-chuẩn-bị-corpus-nghiệm-thu-mới) hướng dẫn khóa bốn partition theo BK-02 và dùng `--structured-gt` để chấm bảng, ô số và thứ tự đọc theo BK-03. Kết quả nghiệm thu còn phụ thuộc GT độc lập và protocol đã khóa.
- [Nguồn tại mốc tổng hợp](evidence/source_snapshot.json), [kết quả kiểm lịch sử](evidence/verification.json). CSV và các Markdown được cập nhật sau mốc đó cần kiểm bằng chứng mới; xem [kiểm phần bổ sung](evidence/verification_plan_addendum_20261103.json).
- [Kiểm triển khai cuối](evidence/verification_implementation_final_20261103.json): hash code focus, 23 ID, trace 65 TC và JUnit hồi quy; không cấp nghiệm thu accuracy.
- [Kiểm đối chiếu benchmark](evidence/benchmark_quality_audit_20261103.json): nhận dạng nguồn, bằng chứng mã/test và bảo toàn trong phiên chỉ bổ sung tài liệu benchmark.

Lượt xử lý được tổng hợp là **4 PDF/511 trang** tại `output/batch_inputs_20261103`, đã hoàn tất kỹ thuật nhưng còn `NEEDS_REVIEW`; chất lượng toàn corpus theo GT độc lập là `NOT_EVALUATED`. Kiểm kê 7 PDF/787 trang trong báo cáo 30/10 chỉ thuộc lịch sử.

Phương pháp vận hành chuẩn vẫn nằm tại [AGENTS.md](../AGENTS.md) và [docs/development](../docs/development/README.md). Không cần nạp cả thư mục này ở đầu mỗi phiên: đọc chỉ mục, chọn đúng ID công việc rồi mở nguồn tương ứng. Các tài liệu và bằng chứng trong `Test case`, file chuẩn và output cũ được giữ nguyên.
