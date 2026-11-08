# Kế hoạch benchmark, regression và báo cáo QA

Ngày 07/11/2026. **DRAFT phương pháp**, chưa có phép đo accuracy corpus hoặc paired baseline/candidate mới. Dùng cùng [GT protocol](GROUND_TRUTH_PROTOCOL.md) và [taxonomy](ERROR_TAXONOMY.md); evaluator hiện có là nguồn implementation, không viết lại công thức trong dashboard.

## 1. Ba lớp kết quả phải tách biệt

1. **Kiểm hợp đồng phần mềm:** fixture/counterexample, raw/source/bbox/numeric guard, completeness, receipt/identity/cache/publication. Chứng minh hành vi phần mềm trong ca test, không là OCR accuracy.
2. **Diagnostic development:** lỗi từ ảnh/output lịch sử, model replay, paired target hoặc cấu trúc. Có thể phát hiện/sửa lỗi kỹ thuật; nhãn AI hoặc sample chọn để debug không thành nghiệm thu độc lập.
3. **Nghiệm thu:** input/GT/split/protocol/ngưỡng/model/code/runtime được khóa, paired scope đúng, coverage/mẫu số và decision gate đầy đủ. Chỉ lớp này mới hỗ trợ mệnh đề chất lượng trong population được khai báo.

Không cộng số test hoặc số lần cảnh báo vào số lỗi corpus. Không dùng confidence, validation PASS, `SUCCEEDED` hoặc `INPUTS_VERIFIED` làm điểm accuracy.

## 2. Tái dùng evaluator và định nghĩa mẫu số

**Chữ và dấu:** [`ocr_metric`](../../benchmark/scientific_evaluation/ocr_metric.py) và [`evaluation_protocol`](../../benchmark/scientific_evaluation/evaluation_protocol.py). CER là `(S+D+I)/N_ký_tự_GT`; WER_ws tương tự với token whitespace theo policy; DER dùng slot/mark tiếng Việt đúng implementation. Rate có thể vượt 1 do insertion, không clamp. Micro cộng tử/mẫu số; mean theo trang là statistic khác, phải gắn nhãn riêng. Trang GT rỗng có insertion vẫn đóng góp lỗi khi tổng corpus có mẫu số; cả scope không có mẫu số thì rate null.

**Detection chữ:** [`text_detection_metric`](../../benchmark/scientific_evaluation/text_detection_metric.py), snapshot primary detector trong pha A và nhãn vùng. Recall `TP/(TP+FN)`, precision `TP/(TP+FP)`, kèm counts, ignore rules và matching settings khóa trước đo. Không dùng số dòng sau recognition hoặc layout recall thay thế. Snapshot không tồn tại trên output cũ thì metric đó chưa đánh giá; không tạo prediction detector từ bbox dòng nhận dạng.

**Layout và reading order:** [`canonical_layout`](../../benchmark/scientific_evaluation/canonical_layout.py), [`reading_order_v6_2`](../../benchmark/scientific_evaluation/reading_order_v6_2.py), [`structured_scoreboard`](../../benchmark/scientific_evaluation/structured_scoreboard.py). Layout có recall/errors theo vùng GT thường và counts theo class; reading order dùng cặp precedence GT, phạt missing/duplicate theo evaluator. Giữ hash alignment split/merge và identity prediction; không chỉ so chuỗi chữ đầy đủ.

**Bảng và số:** [`teds_metric`](../../benchmark/scientific_evaluation/teds_metric.py), [`numeric_metric`](../../benchmark/scientific_evaluation/numeric_metric.py), structured scoreboard. Báo TEDS content và structure riêng; numeric cell exact phải đúng giá trị/đơn vị **và địa chỉ ô**. Giữ TP/FP/FN/extra cells, GT table count, missing/spurious tables và span/header/continuation scope. Không gọi CER tốt là bảng tốt; không gộp tất cả thành một “Table Accuracy” không định nghĩa.

**Ownership:** kiểm proof/disposition/source coverage bằng validator hiện có và registry trace; geometry integrity không thay semantic ownership trên ảnh. Metric mới như owner exact cần protocol/GT/matching rõ trước implementation. Thiếu GT owner giữ `NOT_EVALUATED`, không tính mọi mapping heuristic là correct.

**Keyword:** [`keyword_acceptance.evaluate`](../../benchmark/scientific_evaluation/keyword_acceptance.py). Từ correct/missing/extra theo occurrence: recall `correct/(correct+missing)`, precision `correct/(correct+extra)` khi scope đầy đủ và mẫu số dương. Còn unannotated/unattributed thì không công bố rate toàn scope; giữ partial counts và coverage. Release gate hiện có kiểm occurrence misses/extras riêng, không chỉ vector tổng hay recall. Giữ literal_v1; alias/rules/decisions có identity và outcome riêng, không hòa vào literal để tăng metric.

**Công thức:** bộ [formula scorecard](../../benchmark/scientific_evaluation/formula_scorecard.py), alignment/content/critical/CDM theo [formula policy](../../benchmark/scientific_evaluation/formula_policy.py). Không loại khỏi scope, không chuyển renderer lỗi thành score 0 hoặc dùng một metric render thay mọi nội dung.

**Review:** [`review_calibration`](../../benchmark/scientific_evaluation/review_calibration.py). Review precision là đơn vị thực có lỗi trong số đơn vị được routed-to-review đủ nhãn; báo cả missed-error rate, coverage và denominators theo implementation. Calibration/holdout phải dùng ngưỡng đã khóa và cùng definition. Thời gian/cost người rà chỉ có giá trị khi được ghi thực; không dùng số ô template làm người đã review.

**Runtime/export:** [`audit_batch_outputs`](../../scripts/audit_batch_outputs.py), operation plan/traces/SLO trong [`release_gate`](../../benchmark/scientific_evaluation/release_gate.py). Báo expected/observed/accepted documents/pages/artifacts; fail/timeout/OOM/retry, process-tree exit, revision/ack consistency; cold/warm/cache và latency/throughput/RSS/VRAM theo workload. Ngưỡng SLO/đơn giá chưa có không được tự điền.

## 3. Fix rate và harm rate sau một thay đổi

Đơn vị paired phải được kê trước: document/page/region/line/cell/occurrence theo lỗi. Baseline và candidate có cùng PDF, GT version, matching/normalization, sample scope, metric definition và eligibility. Khóa code/config/model/runtime riêng mỗi bên; căn GT với từng prediction bằng alignment riêng. Không ghép record chỉ vì text giống nhau.

Trên tập unit có nhãn độc lập đủ điều kiện, phân bốn chuyển trạng thái:

- Sai → đúng: `fixed`.
- Đúng → sai: `harmed`.
- Sai → sai: `still_wrong`, cần giữ mức độ/nội dung thay đổi để biết có làm lỗi nặng hơn.
- Đúng → đúng: `preserved_correct`.

`fix_rate = fixed / baseline_wrong`; `harm_rate = harmed / baseline_correct`. Hai mẫu số khác nhau; nếu một mẫu số bằng 0 thì rate null cùng reason, không suy population risk bằng 0. Báo raw counts, tổng declared/eligible/paired/unlabelled/missing và phân nhóm, không chỉ rate hoặc net change. Tập case “đã biết sai” chỉ đo được fix trong scope đó, không đủ đo harm trên nội dung vốn đúng.

Thiếu prediction baseline hoặc candidate trên unit có GT phải giữ là output missing và sai theo oracle đã khai báo; không loại khỏi denominator để cải thiện rate. Thiếu run manifest/identity hoặc sai identity thì không tạo bảng chuyển trạng thái hợp lệ. Unit sai→sai nhưng giảm CER có thể là cải thiện metric, không phải `fixed`; trình bày cả hai kết quả.

[`retry_effects`](../../benchmark/scientific_evaluation/retry_effects.py) đã có hai rate cho target phrase nhưng nhãn AI sơ bộ, không được dùng làm GT nghiệm thu. [`review_calibration._actual_review`](../../benchmark/scientific_evaluation/review_calibration.py) đã có fixed/introduced cho review; adapter sau này tái dùng counts và provenance, không viết evaluator OCR mới. Adapter paired tổng quát vẫn là phần cần triển khai, không được báo đã có chỉ từ kế hoạch này.

So sánh statistical/CI theo company cluster và multiple comparisons dùng [`stratified_scorecard`](../../benchmark/scientific_evaluation/stratified_scorecard.py), [`cluster_statistics`](../../benchmark/scientific_evaluation/cluster_statistics.py) cùng protocol đã khóa. Khóa precision/sample plan và margins trước holdout; không tự ấn định threshold hoặc chọn subgroup sau khi xem kết quả.

## 4. Trình tự chạy một benchmark hợp lệ

1. Xác minh sources/splits-v2/audit/GT/alignments/custody; chạy preflight. DRAFT hoặc hash đổi phải dừng phần nghiệm thu, vẫn có thể chạy diagnostic được ghi nhãn riêng.
2. Khóa baseline/candidate/protocol, khai báo mọi subgroup và unit/matching; tạo thư mục output mới cho identity mới. Artifact cũ chỉ dùng nếu đúng identity và process-tree/receipt còn kiểm được.
3. Nếu chỉ đổi downstream/QA analysis, tái dùng extraction đã xác minh và export/analysis ra nơi mới khi hợp đồng cho phép; không OCR lại chỉ để có run ID mới. Đổi engine/model thì cần inference mới với CUDA/mọi trang, không chạy GPU lớn trong phase audit.
4. Audit từng batch ngoài thư mục batch; kiểm canonical predictions, input/output coverage và GT scope. Stage hash valid vẫn chưa là GT.
5. Dùng [`scorecard_counts`](../../benchmark/scientific_evaluation/scorecard_counts.py) xuất counts baseline/candidate từ artifact có identity; nó giữ acceptance `NOT_EVALUATED`. Đọc cấu trúc `--help` và chỉ định protocol/artifact-index/sample/prediction-inventory/side/output, alignment keyword/order nếu scope cần.
6. Chạy scorecard/evaluator chuyên biệt, paired transition adapter khi được triển khai, review/operation checks và release gate đúng scope. Không làm dashboard tự sửa trạng thái gate.
7. Lưu command/exit/log, input hashes, code dirty diff, source locators, các exclusions/unknown và output. Bất kỳ loại trừ nào phải có reason theo protocol, không hậu kiểm loại khó.

Điểm vào CLI sẵn có để tra giao diện, chưa phải lượt benchmark accuracy đã chạy:

```powershell
.\.venv\Scripts\python.exe -B -m benchmark.scientific_evaluation.scorecard_counts --help
.\.venv\Scripts\python.exe -B -m benchmark.scientific_evaluation.stratified_scorecard --help
.\.venv\Scripts\python.exe -B -m benchmark.scientific_evaluation.release_gate --help
```

## 5. Regression và mức bằng chứng cần cho sửa lỗi

Mỗi patch phải có counterexample trước sửa và test sau sửa ở đúng module, đối chứng tương tự và preservation raw/ID/bbox/số. Dẫn tới Error Registry record khi đã triển khai; trước đó dùng issue/artifact có hash. Root cause chưa xác minh thì vẫn là hypothesis. Benchmark bị thiếu GT phải ghi `NOT_EVALUATED`; có thể xác nhận fix kỹ thuật trong fixture mà chưa đóng nghiệm thu chất lượng.

Chạy test sát thay đổi trước. Khi đổi hợp đồng/liên module, dùng lệnh dự án:

```powershell
.\.venv\Scripts\python.exe -B scripts/run_pytest_scratch.py tests/unit tests/scientific tests/legacy_compat -q --capture=fd
```

Chỉ chạy smoke/audit GPU khi sửa đổi cần chứng minh inference thật, output mới và đủ trang. Không stress/fault batch đang sử dụng. Trên Windows lỗi pytest mode-0700 xử lý bằng quyền phù hợp và run mới, không sửa ACL. Không thêm test chỉ sao chép implementation; chọn phản ví dụ có khả năng phát hiện regression thực.

Audit này chỉ chạy 11 file/152 test được liệt kê trong [run.json](../../scratch/runs/20261107-qa-audit-governance/run.json), không chạy lệnh full regression bên trên hoặc holdout. 152 passed không phải metric chất lượng.

## 6. Đặc tả báo cáo/dashboard QA sau audit

Adapter CPU đọc report đã xác minh, không gọi OCR trong lúc hiển thị. Mỗi metric cần tên/version/scope/partition, tử số, mẫu số, coverage, status/reason, input/GT/run/code identity, link tới error unit và source crop. Layout/detection, raw/final, literal/alias, baseline/candidate và before/after-review được trình bày riêng.

Chỉ hiển thị documents/pages evaluated từ unit thực được chấm và deduplicate theo identity; số planned/available/failed/unannotated đặt riêng. Với metric thiếu dữ liệu, hiện `NOT_EVALUATED` cùng phần thiếu; không chèn 80/2.500 hoặc biểu đồ số lỗi minh họa. Không có điểm overall accuracy trung bình từ CER, TEDS, keyword và runtime. Các tỷ lệ không cùng mẫu số không được trộn.

Drill-down phải tới error ID, document/page/region/bbox/frame, raw/prediction/GT có đủ quyền, crop và replay command; chưa có root cause ghi chưa xác minh. Với holdout, viewer tuân custody, không làm lộ nội dung cho người đang tune. Số liệu vận hành/chi phí thiếu giữ null. Dashboard chưa được triển khai trong phase báo cáo này.
