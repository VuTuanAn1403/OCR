# Cải tiến Markdown theo kết quả đếm keyword

Ngày 03/11/2026, Asia/Bangkok. Mục tiêu phiên này là khôi phục keyword nguyên văn bị cách ghép Markdown làm đứt, đồng thời kiểm việc tạo cụm giả và đếm lặp. Phạm vi DC-03/04, không thay model, DPI mặc định, lock hoặc `literal_v1`.

## Thay đổi mã

- [column_continuity](../src/ocr_document/column_continuity.py), được gọi từ `build_structure` trong [section_tree](../src/ocr_document/section_tree.py): nối phần câu ở cuối cột với đầu cột kế tiếp khi cùng trang/article, hình học cột tương thích, câu chưa kết thúc và dòng tiếp viết thường. Không nối qua tiêu đề, bảng/công thức hoặc ảnh trong vùng chữ. Bảng xuất muộn vẫn chặn nối nếu có thể chứa phần câu còn thiếu.
- Ảnh minh họa nằm hoàn toàn phía trên vùng chữ có thể chuyển trước đoạn hoàn chỉnh. Giữ ảnh đúng một lần; [document_contracts](../src/ocr_document/document_contracts.py) ghi `continuations` trong chunk: extraction/source ID, bbox, cột, hình học và ID ảnh chuyển. Chunk giữ `NEEDS_REVIEW`; chữ thô, tọa độ và extraction order giữ nguyên.
- [region_tree](../src/ocr_document/region_tree.py): chỉ dòng chữ bỏ phiếu rãnh cột. Một bảng rộng ở cuối trang không còn ép các cột prose phía trên thành thứ tự xen dòng. Bảng/ảnh/công thức vẫn nguyên tử; không sửa chữ hoặc ô bảng.
- Flow version `region-tree-graph-v1.3`; exporter có sẵn kiểm phiên bản để không tái dùng flow cũ. Quyết định chuẩn cập nhật tại [ARCHITECTURE](../ARCHITECTURE.md). Counter không đổi; không dùng từ sai dấu, từ gần giống, viết tắt hoặc đồng nghĩa để tăng count.

## Kết quả quan sát có phạm vi

So sánh trước/sau trên JSON trang đã lưu, qua supervisor Python 3.11, CPU assembly và cùng từ điển `config/keywords.txt`. Bản trước là working tree đầu phiên, đã có các sửa đổi trong báo cáo 06; không phải HEAD Git sạch hoặc trực tiếp bản Markdown lịch sử.

| Trang | Keyword | Trước → sau | Nguyên nhân |
| --- | --- | --- | --- |
| VIC 37 | Trí tuệ nhân tạo | 2 → 3 | `trí` cuối cột → `tuệ nhân tạo` đầu cột; ảnh minh họa từng chen giữa câu |
| VIC 46 | nhà thông minh | 1 → 2 | Giữ hai cột prose liên tục phía trên bảng cuối trang |
| AAA 125 | An ninh mạng | 1 → 2 | Giữ thứ tự các dòng nguồn khôi phục, tránh xen cột làm đứt `an / ninh mạng` |

Sáu trang diagnostic còn gồm VIC 65, AAA 100, AGR 40, VIC 137: vector keyword của bốn trang này không đổi so đầu phiên. Giữ các ca đã sửa trước: không xuất lại `công nghiệp 4.0` cùng nguồn; không tạo `tài chính số` qua heading/body; không xóa lặp thật `doanh thu`.

Nguồn cục bộ: [sáu trang trước](../scratch/dev_sessions/20261103-keyword-continuity/baseline_v2/report.json), [sáu trang sau](../scratch/dev_sessions/20261103-keyword-continuity/candidate_v3/report.json), [audit extraction gốc](../scratch/dev_sessions/20261103-keyword-continuity/source_audit.json). Audit đọc lại bốn PDF/511 trang: completion hợp lệ, đủ trang, input hash khớp và validation không có error; tài liệu vẫn `NEEDS_REVIEW`. Integrity không chứng minh accuracy.

Đã mở rộng so sánh CPU trên **4 PDF/511 trang**, tái resolve với ngữ cảnh toàn tài liệu ở cả hai phía: [báo cáo](../scratch/dev_sessions/20261103-keyword-continuity/corpus_final/report.json). Tổng 87 keyword canonical là **134 → 137** (AAA 18 → 19, ABT 2 → 2, AGR 2 → 2, VIC 113 → 115); chỉ ba vector trang thay đổi như bảng trên, không có keyword giảm. Đây là baseline working tree đầu phiên → mã mới trên chữ đã lưu, không so trực tiếp tổng lịch sử 131 hoặc nghiệm thu theo bảng chuẩn 166. Bộ đếm được gọi trên Markdown trang đã dựng; không đếm trực tiếp từ chunk/evidence hoặc cộng nhiều biểu diễn xuất.

Toàn bộ 511 trang giữ nguyên frozen text evidence, ô bảng và số lần mỗi extraction item được xuất. 15 phép nối cột ở VIC có record `NEEDS_REVIEW`; chưa gán nhãn độc lập toàn bộ 15. Đã xem ảnh VIC 37, crop VIC 46 và render AAA 125 để xác nhận ba lượt keyword mới; các ảnh trong phiên là kiểm mẫu phát triển, không là GT holdout. AAA 125 còn chữ in/OCR `an minh mạng` ở cột khác; không đổi thành keyword. Hai kiểu nối sai tiềm tàng qua bảng cuối trang hoặc tiêu đề chia mục đã bị chặn trước khi chốt mã.

Bản Markdown chẩn đoán ghép đủ trang ở `corpus_final/<tên PDF>/after/result.md`; phía `before/` giữ bản đối chứng. Đây là CPU diagnostic trên extraction đã kiểm integrity, không có receipt/publication OCR mới. Region tree có thay thứ tự đọc tại các vùng xen cột; riêng phép nối paragraph không sửa extraction order hoặc bbox nguồn.

## Kiểm chứng và phần còn mở

Test sát phần sửa: **38 đạt, exit 0**, [run/log/JUnit](../scratch/runs/20261103-232344-5e744119/run.json). Có đối chứng khác article/page, thiếu cột/vị trí, câu kết thúc, bullet/heading, cột không tương thích, bảng/caption/ảnh chặn, legacy và bảo toàn raw/source/số. Hai nhóm phản ví dụ đã thất bại trước sửa được lưu trong nhật ký phiên.

Hồi quy phần ghép Markdown đạt **1.502 test, bỏ qua 1, exit 0**. DC-01/02, nghiệm thu DC-03/04 trên GT độc lập, hiệu quả review và CER/WER toàn corpus còn `NOT_EVALUATED`. [Evidence hồi quy và hash mã](evidence/keyword_continuity_20261103.json).

## Đối chứng DC-01 từ ảnh nguồn

ASM 2022 trang vật lý 100 in mã `1600169024-020`. Đây là đối chứng cho hậu tố số trong mã. Rà phát triển trên ảnh crop chưa xác nhận được ca `020` đứng riêng. Sáu ảnh crop VIC trên các trang 24, 37, 52, 65 và 66 cho thấy `O2O` tại các vị trí đầu ra đã lưu ghi `020`. [Ảnh mã ASM](../scratch/dev_sessions/20261105-numeric-020/control/source.png) · [Sáu ảnh VIC](../scratch/dev_sessions/20261105-numeric-020/operator-contact.png).

`--review-from` lưu `lookalike_spans` cho từng trường `text_raw` và `text_corrected`. Offset Unicode bắt đầu từ 0, loại trừ vị trí cuối, lấy trực tiếp trên chuỗi của trường tương ứng. `larger_numeric_span` ghi offset của cả mã/số nếu lần xuất hiện thuộc cụm số dài hơn. Sáu ca VIC vẫn ở nhóm ưu tiên cao. ASM có lý do review từ độ tin cậy nhưng hậu tố không kích hoạt cảnh báo O2O. Bộ đếm literal giữ nguyên và chưa sửa chữ dự đoán. Đây là rà development, hai phiếu người còn trống. [Gói operator](../scratch/dev_sessions/20261105-numeric-020/operator-review/review.md) · [Nhật ký](../scratch/dev_sessions/20261105-numeric-020/session.md).

Không chỉnh output/receipt/hash hoặc workbook người dùng. Snapshot, script tái hiện, Markdown chẩn đoán và ảnh render nằm tại `scratch/dev_sessions/20261103-keyword-continuity/`; dữ liệu scratch chỉ có trên máy, phải mang kèm khi bàn giao. Backlog/trace/báo cáo 06/07 giữ mốc lịch sử. Chưa commit/push.
