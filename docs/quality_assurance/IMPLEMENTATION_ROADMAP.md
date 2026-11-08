# Lộ trình triển khai QA theo phase

Ngày 07/11/2026. Căn cứ [audit hiện tại](CURRENT_ARCHITECTURE.md), [khoảng trống](QUALITY_GAP_ANALYSIS.md), [taxonomy](ERROR_TAXONOMY.md), [GT protocol](GROUND_TRUTH_PROTOCOL.md) và [benchmark plan](BENCHMARK_PLAN.md). Ưu tiên là đề nghị kỹ thuật, chưa phải cam kết thời gian/chi phí hoặc tuyên bố hoàn thành implementation.

## Kết quả phase audit hiện tại

Đã tạo đủ sáu báo cáo yêu cầu, kiểm caller/code và chạy 152 test chọn lọc; probe protocol DRAFT bị từ chối đúng hợp đồng. Không đổi engine/profile/dependency/lock, GT, extraction/receipt hoặc output lịch sử. Không chạy OCR GPU, holdout, stress hay full regression. [Nhật ký](../../scratch/dev_sessions/20261107-qa-repository-audit/session.md), [kiểm cuối](../../scratch/dev_sessions/20261107-qa-repository-audit/verification.json).

Trạng thái QA-01: **phương pháp DRAFT đã viết, dữ liệu/phê duyệt/khóa chưa hoàn tất**. QA-02 sau audit đã triển khai **lát cắt registry v1**: schema/version, adapter operator review, validate và append CLI; [hướng dẫn](../../benchmark/qa/README.md), [phiên triển khai](../../scratch/dev_sessions/20261107-qa-registry/session.md). Chưa có adapter mọi evaluator/backlog hoặc tích hợp approval chất lượng. Hoàn tất code hợp đồng không đồng nghĩa đã nghiệm thu OCR.

## Phase tiếp theo — QA-01 và QA-02, ưu tiên P0

**QA-01: chuẩn bị gói dữ liệu bằng công cụ hiện hữu.** Dùng catalog/splits-v2/source-use audit, annotation và preflight; không xây dataset manager khác. Hành động độc lập với việc có người gán nhãn là kiểm danh sách artifact còn thiếu, schema compatibility, nguồn đã exposure và quy trình lưu version mới. Chỉ tạo inventory từ corpus được xác định và metadata có bằng chứng; không tự gán company/rights/role.

Điều kiện hoàn tất dữ liệu: tất cả artifact/nhãn độc lập/custody/phê duyệt thật, preflight xác minh input và phạm vi formula/release phù hợp. Hiện chưa đủ điều kiện đó; giữ `NOT_EVALUATED`, không yêu cầu lại người A/B và không dùng AI để lấp nhãn.

**QA-02: Error Registry offline.** Đã tạo package `benchmark.qa` và CLI CPU riêng ngoài production trong đợt triển khai sau audit. Registry chỉ tham chiếu/back-reference artifact hiện có, không nhập ngược benchmark vào workers hoặc core pipeline. Thiết kế ở [ERROR_TAXONOMY](ERROR_TAXONOMY.md).

Đợt code đầu nên giới hạn vào schema/version, record identity và adapter một loại nguồn đã có scope rõ. Không cần đồng thời sửa OCR. Giữ cause null khi chưa có chứng cứ, phân biệt proposed category/review signal/observed defect và legacy finding. Hash đúng là toàn vẹn file, không xác minh GT độc lập.

Nghiệm thu kỹ thuật: test duplicate ID, hash mismatch, path thoát evidence root, missing crop/GT, source locator, record lịch sử và trạng thái fix/quality tách biệt; round-trip không mất raw/bbox/source ID. Dữ liệu fixture phải được ghi rõ contract test. Chưa có GT không được tạo quality pass.

## QA-03 — Báo cáo hợp nhất/dashboard, ưu tiên P0

Sau khi mapping artifact/registry rõ, viết adapter CPU đọc output text/detection/structure/keyword/review/operation và scorecard hiện có. Không sao chép phép tính CER/WER/TEDS hoặc gọi model khi mở báo cáo. Định nghĩa dashboard ở [BENCHMARK_PLAN](BENCHMARK_PLAN.md).

Một lát cắt nhỏ có thể bắt đầu bằng report text + detection, nhưng phải giữ schema mở rộng và tình trạng metric khác là chưa đánh giá. Chỉ hiện số documents/pages đã chấm có nguồn thật. Không biến planned/failed thành evaluated, hoặc layout recall thành detector recall.

Nghiệm thu: source/hash/scope/mẫu số truy được, missing/annotated-empty/output-missing phân biệt đúng; không gộp overall accuracy; không leak holdout qua viewer; link error/crop/replay hợp lệ. Test bất đồng identity và report partial phải ngăn kết luận toàn scope. Dashboard UI chưa được viết trong phase audit.

## QA-04 — Detection/recognition/dấu, ưu tiên P1

Chọn từng record E03/E04/E02 có ảnh/snapshot và expected đủ điều kiện, tạo counterexample trước sửa. Tách detector bỏ vùng, recognizer đọc sai, transform ảnh và postprocess; không bắt đầu bằng tăng DPI hay đổi engine toàn cục.

Tái dùng detection snapshot, diacritic/short-token retry, numeric guard và bộ đo hiện có. Phạm vi sửa đầu tiên chỉ một biên có nguyên nhân xác minh. Không suy O2O từ 020 để đổi bằng chứng số. So paired whole-line/numeric/keyword và target scope riêng.

Hoàn tất kỹ thuật cần counterexample, regression/đối chứng, output mới và proof giữ raw/ID/bbox/số; fix/harm độc lập chưa đo được thì giữ `NOT_EVALUATED`, không đóng nghiệm thu OCR chỉ vì diagnostic cải thiện.

## QA-05 — Bảng và source ownership, ưu tiên P1

Truy trước từ artifact AGR/ASM/GAP-03/TAB_05 và các ca năm/đơn vị/header/địa chỉ ô. Xác nhận lại code/input identity và expected/actual, không gán kết luận lịch sử cho checkout mới. Tận dụng replay từ extraction/response đã kiểm nếu đủ; inference mới chỉ khi câu hỏi thật sự đòi hỏi.

Frozen source bridge fix và auto stitch đã tồn tại. Không viết lại hoặc ngoại lệ theo công ty/trang. Tập trung nguồn còn chưa map, geometry/proof token, header role và điều kiện continuation; giữ cả physical cell và logical projection.

Nghiệm thu gồm TEDS/content/span, numeric value **và location**, source multiplicity/disposition, bảng thiếu/thừa và nhãn L5 độc lập. Test hợp đồng/replay model lưu sẵn không thay GT. Bảng tự nối tiếp tục review khi chưa đủ điều kiện chất lượng.

## QA-06 — Reading order và keyword, ưu tiên P1

Tái dùng region graph, furniture, continuation, `keyword_acceptance` và source alignment. Ca ưu tiên là trích dẫn/cột/bảng làm mất hoặc lặp occurrence; giữ literal_v1 và tách alias/rules/decisions. Không đổi ngữ nghĩa đếm để làm workbook khớp tổng.

Nghiệm thu kỹ thuật có counterexample cùng tổng nhưng sai vị trí, block split/merge, header ẩn và duplicate source; giữ raw/order nguồn, đối soát export/keyword. Nghiệm thu chất lượng cần GT precedence/occurrence và mẫu số/coverage rõ.

## QA-07 — Review và revision, ưu tiên P1

Mở rộng packet/calibration hiện hữu thay vì tạo queue song song. Khi cần sửa chữ/bảng, thiết kế overlay/revision có actor/time/reason/source/crop, giữ origin chỉ đọc, replay export/keyword trong output mới và đọc kiểm publication. Quyết định alias hiện có không phải UI sửa text tổng quát nhưng cũng không bị thay thế.

Nghiệm thu: số/đơn vị không bị tự suy, rollback/replay determinism, không mất gate protected/orientation/source, root cause chưa biết giữ nguyên; đo review precision/lỗi lọt/thời gian/cost và before/after paired. Không điền annotation/time giả khi chưa có người rà.

## QA-08 — Resume, fault và tải dài, ưu tiên P2

Lập workload/operation plan/SLO và scope cold/warm/cache bằng hợp đồng release hiện có. Chạy output/cây tiến trình riêng, không tác động batch/model/lock đang dùng. Ghi mọi timeout/OOM/retry, peak resource, receipt, process exit, ledger prepare/reconcile/readback/ack.

Nghiệm thu có đủ tình huống và raw trace đúng identity; dữ liệu failed/pending không giữ số cũ hoặc 0 giả. p50/p95/throughput có workload/đơn vị; thiếu giá/peak giữ null. Fixture recovery pass không chứng minh soak 100–1.000 PDF. Audit này chưa chạy phase này.

## QA-09 — So model và preprocessing, ưu tiên P3

Chỉ khi có tập đo hữu ích và protocol phù hợp, so VietOCR/Docling với candidate Paddle/VLM hoặc tiền xử lý chọn lọc trên cùng input/GT/scope. Khóa weights/config/dependency/runtime riêng, giữ output riêng, placement/process contracts và control baseline. Không cài đè model/runtime đang hoạt động.

Nghiệm thu gồm lợi ích và harm theo subgroup, số/ownership/keyword, latency/resource và protocol thống kê. Native-first là thay đổi policy sản phẩm riêng; không dùng test baseline lịch sử làm backend mới. Chưa có phép đo trong audit cho phép đổi engine.

## Quy tắc chuyển phase và đóng lỗi

Mỗi đợt triển khai phải chốt input/code identity, một câu hỏi có thể bác bỏ, tiêu chí kỹ thuật và scope benchmark trước sửa. Sau counterexample và patch nhỏ, chạy test sát thay đổi; mở rộng hồi quy khi hợp đồng/liên module đổi. Lưu lệnh, exit/log/JUnit/output mới, preservation proof và paired fix/harm hoặc lý do `NOT_EVALUATED`.

Chỉ ghi `FIX_VERIFIED_TECHNICAL` khi có bằng chứng tái hiện trước/sau và không làm mất source; chỉ ghi quality accepted khi benchmark/gate/phê duyệt đúng scope thực sự đủ. Không đổi receipt/hash/GT hoặc hạ gate để chuyển phase. Không cần triển khai cả chín gói trong một lượt; sau lát cắt registry v1, bước code tiếp theo là adapter paired counts QA-03/QA-G04 và báo cáo hợp nhất. Trạng thái QA-01 dữ liệu vẫn trung thực theo nguồn lực thực tế.
