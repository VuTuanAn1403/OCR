# Khoảng trống QA sau repository audit

Ngày 07/11/2026; identity/phạm vi/test tại [CURRENT_ARCHITECTURE](CURRENT_ARCHITECTURE.md). Các mục dưới là phát hiện trong phạm vi audit, không phải kết quả accuracy. `P0` chỉ mức ưu tiên đề nghị; không phê duyệt ngưỡng, GT hoặc release.

## QA-G01 — GT và protocol chưa đủ điều kiện nghiệm thu — P0

**Đã có:** inventory/split lock, pilot/source-use audit, annotation tools, protocol preflight và release gate. Công cụ yêu cầu bốn partition `train/development/calibration/holdout`, nhóm theo công ty/tài liệu và kiểm template/near-duplicate/exposure. Đây là điều kiện chặt hơn mẫu manifest ba partition trong bài nguồn.

**Khoảng trống dữ liệu:** chưa cung cấp bộ GT độc lập, nguồn holdout/custody và approval đầy đủ để audit này thực hiện nghiệm thu. Tình trạng không có người A/B đã được bàn giao; không hỏi lại, không dùng nhãn AI thay thế. Probe mẫu DRAFT thật bị preflight từ chối, nhưng probe chỉ chứng minh mẫu đó chưa sẵn sàng, không chứng minh không tồn tại mọi protocol khác trên máy.

**Hành động:** làm theo [GROUND_TRUTH_PROTOCOL](GROUND_TRUTH_PROTOCOL.md); lập hồ sơ thiếu và nhận dạng input ở output mới khi có corpus hợp lệ. Tài liệu đã dùng debug như AGR/ASM không được tự nâng thành holdout. **Hoàn tất phương pháp** khác **hoàn tất dữ liệu** và **được nghiệm thu**; hai trạng thái sau vẫn `NOT_EVALUATED`.

## QA-G02 — Thiếu registry lỗi thống nhất — P0

**Cập nhật triển khai sau audit:** [registry v1](../../benchmark/qa/README.md) đã có schema/version, import operator review, kiểm evidence root/hash, append-only revision và CLI. Đây là lát cắt QA-02; adapter mọi evaluator/backlog và tích hợp decision chất lượng còn thiếu. Phát hiện audit dưới đây phản ánh thời điểm trước đợt code đó.

**Đã có:** [`03_BACKLOG_CAI_TIEN.csv`](../../Cai%20Tien/03_BACKLOG_CAI_TIEN.csv), [trace kiểm thử](../../Cai%20Tien/05_TRACE_KIEM_THU.csv), review queue, các JSON diagnostic và evaluator có source ID/hash riêng. Backlog cũ có mốc lịch sử; trạng thái “OPEN” trong CSV không có nghĩa mọi fix vẫn thiếu ở checkout hiện tại.

**Khoảng trống chức năng:** tra `error_registry`, `error.registry`, `root_cause`, `taxonomy` trong source/benchmark/scripts/config chưa tìm thấy schema/CLI registry thống nhất nối symptom → evidence → reproduction → cause → fix → regression → benchmark. Đây là phạm vi tìm kiếm, không khẳng định mọi hồ sơ hiện có vô dụng.

**Hành động:** dùng [ERROR_TAXONOMY](ERROR_TAXONOMY.md) làm đặc tả metadata offline. Adapter nối tới record hiện có, không sao chép/sửa extraction hay tự dựng lỗi từ review flag. **Hoàn tất implementation sau này:** import có provenance và hash, ID ổn định, duplicate/source coverage kiểm được, root cause chưa biết giữ null; không có trạng thái “fixed” chỉ từ test pass.

## QA-G03 — Chưa có báo cáo hợp nhất đầy đủ dữ liệu và phạm vi — P0/P1

**Đã có:** text/structure/detection report, scorecard/release, operation evidence, review calibration và bản đối chiếu tương tác tĩnh từ phiên trước. Không cần thêm evaluator tính lại tất cả metric.

**Khoảng trống chức năng:** chưa thấy adapter/view QA thống nhất trong vùng đã tra để đọc các báo cáo, chỉ ra scope/mẫu số/coverage, dẫn tới error record và phân biệt diagnostic/acceptance. Canvas đối chiếu kiến trúc không phải dashboard chất lượng tự nạp report. Số minh họa 80 tài liệu/2.500 trang trong bài không phải dữ liệu dự án.

**Hành động:** hợp nhất bằng tham chiếu artifact/hash, không trung bình các metric không cùng mẫu số. Detection recall phải lấy snapshot detector; layout recall trong scorecard không được đổi nhãn thành text detection recall. **Hoàn tất:** hiển thị đủ metric bắt buộc hoặc `NOT_EVALUATED` cùng lý do, không có điểm overall accuracy tổng hợp và không biến missing thành 0. Đặc tả hiển thị tại [BENCHMARK_PLAN](BENCHMARK_PLAN.md).

## QA-G04 — Fix/harm đã có cục bộ, còn thiếu đối chiếu tổng quát — P1

**Đã có:** [`retry_effects.summarize_retry_effects`](../../benchmark/scientific_evaluation/retry_effects.py) đếm fixed/harmed với hai mẫu số khác nhau, nhưng nhãn là `AI_PRELIMINARY_TARGET_ONLY` và chỉ target phrase. [`review_calibration._actual_review`](../../benchmark/scientific_evaluation/review_calibration.py) đếm fixed/introduced trên đơn vị có before/after, giữ thiếu thời gian/cost là null. Scorecard có paired comparison theo company, không thay thế bảng chuyển trạng thái đúng/sai từng unit.

**Khoảng trống:** chưa thấy báo cáo chuyển trạng thái dùng chung cho mọi loại lỗi, ràng buộc cùng input/GT/unit scope và đủ artifact baseline/candidate. Không được gọi metric target-only là cải thiện toàn dòng hoặc corpus.

**Hành động:** thêm adapter counts/lineage có kiểm identity trên evaluator hiện hữu; chỉ chấm độc lập khi có nhãn đủ điều kiện. Báo cả sai→đúng, đúng→sai, sai→sai và đúng→đúng, missing/unlabelled/partial. **Hoàn tất:** công thức/mẫu số của [BENCHMARK_PLAN](BENCHMARK_PLAN.md), có counterexample thay scope/GT/thiếu candidate và phép kiểm giữ raw/ID/bbox/số.

## QA-G05 — Triệu chứng chưa đủ xác minh nguyên nhân — P1

Detection snapshot, raw/evidence, layout/source dispositions và review crops đã giúp truy vết. Các diagnostic AGR/ASM/GAP-03/DC-01/DC-02 là đầu mối lịch sử có identity riêng, không phải phép đo lại trong audit.

**Cần làm:** một occurrence keyword thiếu có thể do detector, recognizer, ownership, order hoặc counting; không gán E03 chỉ vì Markdown thiếu dòng. Sai ô có thể do hình học, bridge placement, table model hoặc reconciliation. Chỉ nâng `root_cause` từ null khi có trace và counterexample cô lập đúng biên. Tái dùng frozen bridge fix và auto stitch đã có; không tạo patch theo tên công ty/trang.

Đầu mối: [phiên bridge](../../scratch/dev_sessions/20261106-bridge-frozen-sources/session.md), [rotation/retry](../../scratch/dev_sessions/20261106-retry-alias-rotation/session.md), [bản đối chiếu](../../Cai%20Tien/15_DOI_CHIEU_KIEN_TRUC_OCR_20261107.md). Những bằng chứng này chưa được phát lại và không được gán identity code/runtime mới.

## QA-G06 — Review/revision chưa thành vòng sửa đã được nghiệm thu — P1

**Đã có:** packet, template, proposal, literal/alias decisions với identity, review calibration và kiểm publication. Không xem mọi loại quyết định là chưa được hỗ trợ.

**Khoảng trống:** trong đường đã khảo sát chưa có UI/text-edit revision tổng quát nối quyết định sửa chữ/bảng với replay export/keyword, đọc kiểm và rollback. Hiệu quả review trên người thật và chi phí vẫn thiếu dữ liệu. Numeric guard không cho phép suy số mới chỉ để giảm warning.

**Hành động:** thiết kế overlay/revision mới tham chiếu source ID/crop/actor/evidence. Giữ raw và publication gốc. Đo lỗi lọt/precision/seconds/cost riêng, không làm mất gate protected/orientation/source khi sửa dấu. Chỉ triển khai QA-07 sau khi hợp đồng registry và phương pháp đo đã rõ.

## QA-G07 — Chưa đánh giá toàn diện vận hành thực — P2

**Đã có:** scheduler/checkpoint/process receipts, SQLite revision/ack và fixture crash/recovery; release gate nhận evidence cold/warm/cache, workload, SLO và drift. Không cần thay scheduler để có “QA runtime”.

**Khoảng trống dữ liệu:** audit này không có run soak/fault mới, peak RSS/VRAM hay p50/p95 theo workload đã khóa. Test pass không chứng minh tải 100–1.000 PDF. Kết quả cũ có thể dùng trong phạm vi identity của chính nó, không chuyển thành SLO hiện hành.

**Hành động:** output/plan riêng, không gây lỗi batch đang dùng. Ghi tất cả timeout/OOM/retry/missing, cây tiến trình, identity và publication readback. Đơn giá hoặc thời gian review thiếu giữ null.

## QA-G08 — Engine/tiền xử lý và tính năng xuất là backlog có điều kiện — P2/P3

Crop/CLAHE/DPI retry đã có; chưa thấy deskew/dewarp toàn trang trong luồng chuẩn. Có JSON/MD/TXT/Excel keyword; searchable PDF công bố và Excel mọi bảng đầy đủ là nhu cầu sản phẩm riêng. Chưa cần triển khai chúng để chuẩn hóa Error Registry.

Không có benchmark paired trong audit này chứng minh Paddle/VLM tốt hơn VietOCR/Docling. Chỉ thử QA-09 sau khi có bộ đo đủ điều kiện, weights/config/runtime được nhận dạng và output mới. Chưa đổi profile, model, lock hoặc dependency.

## Điều chưa thể kết luận

Không có line/branch coverage mới, accuracy corpus, tỷ lệ lỗi từng E-code, fix/harm độc lập, review capacity hoặc soak trong phiên này. 152 test mới chỉ kiểm các hợp đồng kỹ thuật được chọn. Danh mục lỗi trong taxonomy là coverage dự kiến, không có nghĩa cả 14 loại đã quan sát lỗi thật. Việc hoàn tất sáu báo cáo không đóng QA-01/02 implementation hay nghiệm thu chất lượng; trạng thái từng phase ở [roadmap](IMPLEMENTATION_ROADMAP.md).
