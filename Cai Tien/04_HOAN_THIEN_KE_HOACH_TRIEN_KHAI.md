# Hoàn thiện kế hoạch triển khai cải tiến

Cập nhật 03/11/2026, Asia/Bangkok. Tài liệu bổ sung sau đối chiếu `Test case` và `Cai Tien`, theo yêu cầu làm rõ bốn điểm cần xử lý trong kế hoạch.

## 1. Vai trò và phạm vi

Bốn điểm dưới đây giúp tổ chức, thực hiện và nghiệm thu **23 đầu việc hiện có**. Chúng không làm tăng số lỗi OCR đã xác nhận hoặc tự tạo thêm bốn đầu việc phần mềm. Riêng tình trạng CSV là vấn đề toàn vẹn tài liệu cần khắc phục.

| Nguồn | Dùng để làm gì |
| --- | --- |
| [Bản tổng hợp cải tiến](01_TONG_HOP_DIEM_YEU_VA_LO_TRINH.md) | Chọn vấn đề và thứ tự xử lý theo bằng chứng |
| [Đặc tả nâng cấp và nghiệm thu](../Test%20case/02_DAC_TA_NANG_CAP_VA_NGHIEM_THU_20261030.md) | Xác định yêu cầu kỹ thuật, GT, metric, điều kiện nghiệm thu và giới hạn công bố |
| [Ma trận chức năng](../Test%20case/KE_HOACH_VA_DANH_SACH_TEST_CASE.md), [ma trận khoa học](../Test%20case/BO_TEST_CASE_DANH_GIA_DO_CHINH_XAC_KHOA_HOC.md) | Giữ các tình huống cần kiểm; đọc cùng [lớp hiệu đính](../Test%20case/00_DOC_KET_QUA_TRUOC.md) |
| [Phương pháp làm việc](02_PHUONG_PHAP_LAM_VIEC_DU_AN_LON.md) | Chia phiên, nhận dạng nguồn, lưu kết quả và bàn giao |

## 2. Điểm thứ nhất — Gắn công việc cải tiến với ca kiểm và bằng chứng

**Liên quan:** GAP-05. Hai ma trận có 44 ca chức năng và 21 ca khoa học. CSV hiện chưa dẫn trực tiếp mã TC; thiếu liên kết này chưa chứng minh repository thiếu test.

**Cách thực hiện:** kiểm mã/test hiện có trước khi viết thêm. Lập bảng trace cho từng TC, cho phép một TC liên quan nhiều việc và một việc cần nhiều TC. Các hợp đồng đang đúng vẫn phải có ca hồi quy, kể cả khi không có ID lỗi riêng trong backlog.

| Trường cần có trong bảng trace | Nội dung |
| --- | --- |
| TC và ID cải tiến | Giữ nguyên mã gốc; ca hồi quy chung có thể ghi không gắn lỗi mới |
| Mệnh đề cần kiểm | Hành vi hoặc giá trị expected/actual và phần không được suy rộng |
| Loại kiểm | Unit/contract, test double, fault-injection, inference thật hoặc đánh giá GT |
| Test và input/GT | File/ký hiệu test, fixture/manifest/hash, trang/block/cell khi có |
| Identity | HEAD cùng thay đổi chưa commit; config/model/lock/runtime khi phép kiểm cần chúng |
| Lượt chạy và kết quả | Lệnh, exit code, log/JUnit/report; phân biệt đạt, thất bại, chưa chạy, thiếu dữ liệu hoặc môi trường |
| Điều kiện đóng và giới hạn | Phản ví dụ, đối chứng tránh sửa quá tay và phần chưa nghiệm thu |

Các quan hệ sau là **gợi ý để lập trace**, chưa phải chứng nhận test đã chạy:

| Nhóm việc | TC/đặc tả cần đối chiếu |
| --- | --- |
| AG-QA-001–003 | TC_TXT_02/03, TC_SCI_NUM_02/03; đặc tả mục 9–10 |
| AG-QA-004–006 | Đặc tả mục 9–10; các phản ví dụ trong [bộ kiểm AG-QA](../Test%20case/antigravity_review_20261103/test_adversarial_review.py) |
| DC-01/02 | TC_TXT_04–07 và TC_SCI_TXT_01–05; bổ sung đối chứng số `020` thật và từ vốn đúng |
| DC-03/04 | TC_LAY_01, TC_KW_03, TC_SCI_LAY_01; có đối chứng AGR trang 40 để tránh nối thành cụm giả |
| DC-05 | TC_STR_03 và đặc tả mục 10/12; AAA trang 100 cần đối soát lặp, VIC trang 137 phải giữ lặp thật |
| GAP-03/04 | TC_STR_01 và đặc tả mục 8/11–12 về hướng crop, tọa độ và lặp có suffix |
| GAP-06 | TC_BAT_01–07; đặc tả mục 17; tách test double khỏi thử sự cố và tải dài thực |

**Điều kiện hoàn tất:** bảng trace liệt kê đủ 65 mã TC, không trùng hoặc mất mã; mọi ca tuyên bố đạt có bằng chứng đúng phạm vi. Ca chưa chạy hoặc thiếu GT/môi trường giữ trạng thái riêng, không ép thành PASS. Bảng đầy đủ chưa được lập trong lần bổ sung tài liệu này.

### Bằng chứng bổ sung cho TC_STR_01 và GAP-03

v7.0 đặt chữ ẩn cho hướng crop 90°/270° bằng bbox display của pha A và ghi quyết định theo source ID. Fixture kiểm CropBox lệch gốc và bốn góc xoay trang. Replay CPU dùng chữ đã lưu ở AAA trang 195/197 và ABT trang 4. Trường hợp không đặt được giữ nguyên chữ để review. Heuristic bảng không dùng dòng dọc để lấp ô theo tâm; đối soát cuối cần text khớp và một ô chứa toàn bộ bbox. Phạm vi kiểm là hình học và bảo toàn nguồn. Nghiệm thu quyền sở hữu ô trên ảnh thật vẫn giữ `NOT_EVALUATED`. [Lệnh và artifact](../scratch/dev_sessions/20261104-oriented-ocr-bridge/session.md).

### Bằng chứng bổ sung cho GAP-04

v7.0 giữ toàn bộ dòng khi phát hiện lặp. Phương án rút gọn mang `applied: false` và bbox crop để review. Dòng bị bộ lọc loại vẫn giữ chữ thô, bbox và lý do loại. Kiểm 9 PDF/938 trang đã lưu cho thấy ba dòng từng bị rút gọn trong frozen evidence. Replay chữ thô của ba dòng qua mã mới xác nhận cả ba giữ toàn bộ dòng và yêu cầu review. Có hai gói ảnh nguồn và phiếu A/B riêng. Nghiệm thu nội dung giữ `NOT_EVALUATED` đến khi có phiếu người và phân xử. [Lệnh và artifact](../scratch/dev_sessions/20261104-repetition-source-review/session.md).

### Bằng chứng bổ sung cho GAP-06

Đã thử dừng cưỡng bức cây tiến trình analysis CPU khi chuẩn bị tài liệu thứ tư trong chín đầu ra đã xác minh. Ba điểm ngắt gồm giữa giao dịch SQLite, sau commit prepared và sau thay Excel trước acknowledge. Cả ba lượt resume đến revision 9, giữ các hàng chưa công bố trống và số đếm khớp nguồn. Phạm vi này bổ sung bằng chứng thực thi cho phần publication của TC_BAT_02/03/05 và giải phóng cây/lease ở TC_BAT_07. Ca 10 PDF, soak và worker GPU tiếp tục cần phép đo riêng. [Lệnh và artifact](../scratch/dev_sessions/20261104-publication-hardkill/session.md).

## 3. Điểm thứ hai — Đặt dữ liệu chuẩn trước nghiệm thu review

**Liên quan:** GAP-01, GAP-02 và DC-06. Bản đối chiếu trước ghi DC-06 phụ thuộc GAP-02 trong CSV, trong khi mục 6 của lộ trình từng xếp DC-06 ở đợt 3 và GAP-02 ở đợt 4. Mục 6 đã được điều chỉnh để làm rõ thứ tự.

Chuẩn bị vị trí keyword và nhãn độc lập từ sớm. GAP-01 cung cấp các occurrence cần đối soát; GAP-02 quy định tập development/calibration/holdout, guideline, phân xử và giao thức đo. Bộ chấm liên quan phải được sửa/xác minh trước khi dùng kết quả để nghiệm thu.

Có thể xây danh sách review, crop và trace của DC-06 trước khi có đủ GT. Nghiệm thu hiệu quả DC-06 chỉ thực hiện khi phần GT phù hợp thuộc GAP-02 đã đủ và protocol được khóa; nếu chưa đủ thì giữ DC-06 mở, không bỏ phụ thuộc để đóng việc.

v7.0 đã có CLI `--review-from` để tạo gói rà vận hành từ extraction đã kiểm. Mỗi mục giữ chữ thô, source ID/locator, vị trí, nguyên nhân, keyword literal và đề xuất chưa áp dụng. Gói chứa crop và phiếu thời gian để người vận hành điền. Mẫu trên chín PDF đưa sáu ứng viên O2O/020 ở VIC lên đầu, đồng thời giữ hàng đợi đầy đủ ngoài gói ảnh có giới hạn. Bản nhãn GT A/B độc lập tiếp tục dùng gói ảnh nguồn riêng. [Lệnh và bằng chứng](../scratch/dev_sessions/20261104-review-packet/session.md).

**Điều kiện hoàn tất:** danh sách review truy được source ID/bbox/crop/lý do; đánh giá có nhãn độc lập cho lỗi bị bỏ sót, precision và chi phí người kiểm. Đo riêng đầu ra tự động, subset tự chấp nhận và đầu ra sau review theo đặc tả. Confidence hoặc cờ NEEDS_REVIEW chưa thay được các phép đo này.

## 4. Điểm thứ ba — Chuyển backlog thành từng đợt có thể thực hiện

**Liên quan:** WF-01 và các ID được chọn triển khai. Thời lượng trong lộ trình gốc là đề xuất lịch sử; thứ tự trong `Cai Tien` hiện là đề nghị, chưa phải lịch cam kết.

Trước mỗi đợt, điền một phiếu giao việc trong SESSION hoặc hồ sơ đầu việc theo cấu trúc dưới đây. Không tự gán người, ngày hoặc ước lượng công khi chưa có căn cứ.

| Trường | Nội dung cần chốt trước thực hiện |
| --- | --- |
| ID và đầu ra | ID backlog, module/hợp đồng, kết quả cụ thể cần bàn giao |
| Người thực hiện và người kiểm | Tên hoặc vai trò được phân công; chưa phân công ghi rõ chưa xác định |
| Phụ thuộc | Điều kiện bắt đầu và điều kiện nghiệm thu; phần nào được chuẩn bị trước |
| Ước lượng và mốc | Căn cứ ước lượng, công dự kiến, ngày bắt đầu/kết thúc khi đã chốt; thiếu thì ghi chưa ước lượng |
| Phép kiểm và điều kiện đóng | Trace TC, phản ví dụ/đối chứng, lệnh dự kiến, bằng chứng cần lưu |
| Trạng thái và bước kế tiếp | Tách tiến độ triển khai khỏi trạng thái bằng chứng; không đổi trường trạng thái của CSV cũ khi chưa kiểm hợp đồng |


Ngưỡng và hồ sơ nghiệm thu tiếp tục lấy từ **đặc tả mục 15–19**. Các ngưỡng đó còn là đề xuất cần khóa trước holdout; không đổi ngưỡng sau khi xem kết quả. Thiếu GT giữ NOT_EVALUATED, không lấy số test đạt hoặc artifact audit thay cho accuracy.

**Điều kiện hoàn tất:** mỗi ID đã chọn vào đợt có phiếu giao việc, phụ thuộc khả thi, đầu ra và người kiểm rõ ràng; các mốc được phân biệt là dự kiến hay đã cam kết. Đợt chưa chốt người/nguồn lực vẫn ở trạng thái chuẩn bị. Lần bổ sung này chưa lập lịch hoặc giao người cho 23 việc.

## 5. Điểm thứ tư — Khôi phục tính toàn vẹn CSV backlog

**Liên quan:** tài liệu [03_BACKLOG_CAI_TIEN.csv](03_BACKLOG_CAI_TIEN.csv), hỗ trợ GAP-08/WF-01. Đây là lỗi toàn vẹn tài liệu quan sát được, không phải lỗi mới của pipeline OCR.

Bản đầu phiên đối chiếu trước có 18.887 byte, SHA-256 `0c3bddab08a77dc5db521daeb0abc1670766f119375a32b739d6e2dc960d551d`, đọc UTF-8 đúng. Bản hiện tại kiểm lại có 16.564 byte, SHA-256 `d28cd0ed14717758a007784dfd5a2d8e10426051e4bc8a8565dd3fdfd655c3de`, không có BOM, lỗi giải mã UTF-8 và nhiều chữ Việt thành `?`. Không xác định tác nhân thay đổi. Chi tiết ở [nhật ký đối chiếu](../scratch/dev_sessions/20261103-doi-chieu-ke-hoach/session.md).

**Cách thực hiện khi khôi phục:**

1. Giữ bản hỏng và hash làm bằng chứng; tìm bản UTF-8 tin cậy trong bản sao lưu hoặc artifact bàn giao. Chưa tìm được nguồn thì ghi chưa khôi phục.
2. Nếu có bản đúng hash lịch sử, kiểm nguồn và nội dung rồi tạo bản phục hồi riêng. Nếu phải dựng lại từ Markdown/evidence, nhận dạng là bản dựng lại, đối chiếu từng trường; không tuyên bố byte giống bản gốc.
3. Xuất UTF-8 có BOM, dùng parser CSV để giữ dấu phẩy/xuống dòng/quote. Đổi encoding đơn thuần không phục hồi những chữ đã mất thành `?`.
4. Kiểm đúng 23 ID, schema/trường bắt buộc, ưu tiên gốc, dependencies hợp lệ không vòng, liên kết nguồn và khả năng đọc lại tiếng Việt. Sau đó mới dùng bản đã được đối chiếu để thay file chuẩn trong một lượt thay đổi có bằng chứng.
5. Lưu hash mới và báo cáo kiểm mới; giữ nguyên [verification lịch sử](evidence/verification.json), không sửa hash cũ để ép PASS.

**Điều kiện hoàn tất:** có nguồn phục hồi hoặc biên bản dựng lại rõ ràng, đọc UTF-8 thành công, có BOM, đủ nội dung được đối chiếu và kiểm cấu trúc đạt. Trong lần bổ sung này, CSV được giữ nguyên; việc phục hồi **chưa hoàn tất**.

## 6. Trạng thái sau lần bổ sung

| Điểm | Kết quả tài liệu đã bổ sung | Phần thực hiện còn mở |
| --- | --- | --- |
| 1 — Trace kiểm thử | Trường dữ liệu, gợi ý liên kết và điều kiện đóng GAP-05 | Điền, đối chiếu và chạy kiểm cho từng TC |
| 2 — Phụ thuộc review | Sửa thứ tự trong lộ trình, phân biệt chuẩn bị và nghiệm thu DC-06 | Hoàn thiện GT và đánh giá review |
| 3 — Tổ chức triển khai | Phiếu giao việc và điều kiện chốt từng đợt | Chọn ID, người thực hiện, ước lượng và lịch |
| 4 — CSV | Ghi identity, tình trạng và quy trình phục hồi | Tìm nguồn, phục hồi/đối chiếu và nghiệm thu CSV |

Lượt này chỉ cập nhật tài liệu; chưa sửa các lỗi phần mềm, chạy OCR hoặc nghiệm thu chất lượng GT. Kết quả kiểm phần bổ sung lưu tại [verification_plan_addendum_20261103.json](evidence/verification_plan_addendum_20261103.json); phạm vi kiểm tài liệu được tách khỏi tình trạng CSV còn lỗi. Tài liệu/bằng chứng lịch sử cần kiểm lại identity trước khi dùng tiếp.
