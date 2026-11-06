# Bộ tiêu chí benchmark OCR và khoảng cách nghiệm thu

Đối chiếu ngày **03/11/2026, Asia/Bangkok**. Kết luận: **chưa đủ bằng chứng xác nhận benchmark và chất lượng OCR hiện tại đã đạt mức nghiệm thu tương đương các hệ thống lớn trong cùng phạm vi sử dụng**. Dự án đã có nhiều metric, kiểm thử bộ chấm và đặc tả tốt; còn khoảng cách giữa yêu cầu, khả năng chấm tích hợp và kết quả đo độc lập. Không có cơ sở để kết luận dự án kém hơn mọi hệ thống khác hoặc gán một mức “chuẩn doanh nghiệp” chỉ từ số test đạt.

Trong tài liệu này, mức cần đạt được hiểu là: dữ liệu đại diện và độc lập, giao thức khóa được, đánh giá nhiều tầng, kết quả tái lập, sai số có khoảng tin cậy, có đối chứng và điều kiện phát hành theo rủi ro nghiệp vụ. Đây là khung nghiệm thu đề xuất cho OCR PDF tiếng Việt/tài chính; các nguồn công khai bên dưới là đối chiếu phương pháp, không cấp chứng nhận cho dự án.

Ngày 04/11/2026 đã bổ sung khóa bốn partition và đường chấm cấu trúc chẩn đoán từ `extraction.json`. Các nhận xét về mã ở dưới ghi theo mốc đối chiếu 03/11. Xem [hướng dẫn hiện tại](../benchmark/ground_truth_tools/ANNOTATION_V6.md#quy-trình-chuẩn-bị-corpus-nghiệm-thu-mới) và [bàn giao](../docs/development/HANDOFF.md).

## 1. Nguồn và phạm vi kiểm

- HEAD tại lúc kiểm: `a95c806965118b53b3afc28d2ebbff37dec0cfc7`, working tree có thay đổi chưa commit. Đã đối chiếu lại chín hash code focus của lượt triển khai trước: khớp; không chỉ dựa vào HEAD.
- Đọc mã metric, scientific runner, harness một tài liệu, công cụ splits, matrix runner và đặc tả. Lưu snapshot/hash ở [phiên kiểm](../scratch/dev_sessions/20261103-benchmark-quality/start.json), [biên bản đối chiếu](evidence/benchmark_quality_audit_20261103.json).
- Chạy lại **159 test liên quan benchmark/GT/evaluator: đạt, exit 0**; [run/log/JUnit](../scratch/runs/20261103-224537-3ec2862b/run.json). Đây là kiểm phần mềm và dữ liệu fixture; không chạy OCR/GT holdout mới.
- Kế thừa [đặc tả mục 4–9, 15–19](../Test%20case/02_DAC_TA_NANG_CAP_VA_NGHIEM_THU_20261030.md), [guideline GT](../benchmark/ground_truth_tools/ANNOTATION_V6.md) và [kết quả triển khai 06](06_KET_QUA_TRIEN_KHAI.md). Không sửa backlog 23 ID, ma trận 65 TC, output/GT/model/lock hoặc evidence lịch sử.

Ba loại kết luận phải tách riêng: **đã đặc tả**, **đã có mã và kiểm hợp đồng**, **đã đo thực nghiệm độc lập**. Thiếu loại thứ ba thì chất lượng ngoài phạm vi fixture vẫn `NOT_EVALUATED`.

## 2. Đối chiếu với benchmark công khai

| Nguồn chính | Điểm phương pháp dùng đối chiếu | Giới hạn áp dụng |
| --- | --- | --- |
| [OmniDocBench — OpenDataLab](https://github.com/opendatalab/OmniDocBench) | Phân biệt OCR text và document parsing; chấm text, bảng, công thức, reading order; phân tích theo thuộc tính trang. README lấy trong phiên có các cập nhật phiên bản đến v1.7, cho thấy phải khóa cả dataset lẫn evaluator. | Không lấy điểm từ phiên bản khác để xếp hạng chéo. Không suy hiệu quả trên báo cáo tài chính Việt từ tên benchmark. Chưa chạy adapter này trong dự án. |
| [olmOCR-Bench — AllenAI](https://github.com/allenai/olmocr/tree/main/olmocr/bench) | Kiểm các sự kiện có thể xác nhận trên trang PDF, như nội dung hiện diện/vắng mặt và quan hệ đọc; hữu ích khi một lỗi nhỏ làm đổi nghĩa hoặc thứ tự giữa hai bài độc lập không quan trọng. | Các test này gắn với nội dung PDF, khác unit test hàm của repository. Tỷ lệ test nội dung đạt không tự chuyển thành CER hay accuracy toàn văn. |
| [Table Transformer/PubTables-1M — Microsoft](https://github.com/microsoft/table-transformer) | Tách phát hiện bảng khỏi cấu trúc; GriTS xem topology, nội dung và vị trí ô. | TEDS cao một mình không chứng minh số đúng ô/đúng kỳ. GriTS là metric bổ sung có thể lựa chọn, không bắt buộc phải cài mọi metric để được gọi là hệ thống lớn. |
| [DocLayNet — IBM](https://github.com/DS4SD/DocLayNet) | Dữ liệu bố cục đa dạng, nhãn người, một phần có nhiều lượt gán nhãn và splits tránh rò rỉ kiểu bố cục. | mAP layout không phải accuracy nhận dạng chữ; cần corpus miền sử dụng riêng và taxonomy/mapping đã khóa. |
| [Guo và cộng sự, ICML 2017](https://proceedings.mlr.press/v70/guo17a.html) | Phân biệt confidence dự đoán với xác suất đúng thực nghiệm; cần đánh giá calibration. | Kết quả về mô hình phân loại không chứng minh trực tiếp xác suất chuỗi VietOCR đã được hiệu chuẩn, cũng không tự chỉ định temperature scaling cho pipeline này. |

Chỉ đọc tài liệu nguồn chính, không tái tạo leaderboard. Các bản README `main` lấy trong phiên không phải commit upstream bất biến; snapshot nguồn và hash được lưu để kiểm lại nội dung đã dùng. Đối chiếu bên ngoài khi triển khai thật phải pin revision/commit cụ thể.

## 3. Những gì mã hiện tại thực sự làm

| Quan sát kiểm từ mã | Kết luận có thể dùng | Phần chưa được chứng minh |
| --- | --- | --- |
| [ocr_metric](../benchmark/scientific_evaluation/ocr_metric.py): `compute_cer_detailed`, `compute_wer_detailed`, `compute_der_detailed`; [evaluation_protocol](../benchmark/scientific_evaluation/evaluation_protocol.py): `aggregate_text_metrics` | Có S/D/I, micro theo counts, NFC và policy rõ; không kẹp CER/WER ở 1; DER có mẫu số dấu riêng. WER hiện tokenize bằng whitespace, nên phải gọi là **WER_ws**, không mặc nhiên là tỷ lệ lỗi từ tiếng Việt theo phân đoạn từ vựng. | Chưa có kết quả holdout đại diện chứng minh ngưỡng chữ/dấu. Cần công bố cả số lỗi và số ký tự/token, không chỉ phần trăm. |
| [scientific runner](../scripts/run_scientific_benchmark.py): `_final_markdown_protocol`; [markdown_evaluator](../benchmark/scientific_evaluation/markdown_evaluator.py): `parse_markdown_artifacts` | Có chấm `result.md` cuối, không mượn page text khi final thiếu; đã có projection bỏ markup/thẻ bảng nhưng giữ nội dung để chấm text. `visible_strict_v1` giữ case/dấu/số/space sau projection. | Phải khóa **cả mã projection và normalization**, cùng quy tắc HTML/pipe table, entity, ký tự `*`, `_`, dấu `\|`, link và công thức. Không coi tên policy là đủ nhận dạng phép chấm. Projection benchmark không đổi nguồn đếm `literal_v1` của sản phẩm. |
| [numeric_metric](../benchmark/scientific_evaluation/numeric_metric.py), [teds_metric](../benchmark/scientific_evaluation/teds_metric.py) | Có numeric matching một-một theo location/scope; có TEDS content/structure và detection P/R/F1 riêng, bảng thiếu chịu lỗi. Sửa AG-QA đã được kiểm hợp đồng. | [Harness `evaluate_document`](../Test%20case/scientific_benchmark_harness.py) còn trả `table_metrics=NOT_EVALUATED`, `numeric_location_metrics=NOT_EVALUATED`; không được gọi helper có sẵn là đã chấm end-to-end hai nhóm này. |
| [reading_order_v6_2](../benchmark/scientific_evaluation/reading_order_v6_2.py): `evaluate_reading_order` | Structured scoreboard và gate dùng GT precedence, gồm node ngắn/lặp, có thể nhận căn span đã rà cho khối tách/gộp và chấm cặp liền nhau đã gán nhãn. Runner hiển thị riêng điểm cấu trúc và điểm text legacy. | Chưa có corpus GT độc lập hoặc hồ sơ căn span đã duyệt cho dữ liệu thật. Nhánh text legacy lọc chuỗi dưới năm ký tự và chỉ phục vụ đối chiếu lịch sử. |
| [catalog](../src/ocr/collect/catalog.py): `lock_company_splits` | Khóa SHA/company và ngăn leakage cho **đúng ba tập `train/dev/test`**. | Chưa trực tiếp nhận bốn tập train/development/calibration/holdout mà đặc tả mới yêu cầu. Cần schema/adapter version mới hoặc split lock calibration tách riêng có ràng buộc; không sửa lock cũ. |
| [cluster_statistics](../benchmark/scientific_evaluation/cluster_statistics.py), [matrix_statistics](../benchmark/scientific_evaluation/matrix_statistics.py) | Đã có paired company-cluster bootstrap, counts, margin có trạng thái duyệt, Holm và trạng thái không đủ dữ liệu. | `min_companies=2` là mức tối thiểu kỹ thuật của hàm, không là bảo đảm đủ lực thống kê. Công cụ chủ động giữ `eligible_for_quality_acceptance=false`; chưa thay hội đồng nghiệm thu/GT thực. |
| [matrix_runner](../benchmark/scientific_evaluation/matrix_runner.py) | Có orchestration nghiên cứu và quy tắc một biến ở thiết kế cũ. | Docstring và cấu hình B0 còn gắn CPU/balanced; A1/A2/A4 mang giả định native/layout/bridge lịch sử. Không dùng nguyên runner đó để tuyên bố A/B của `unified_gpu_full_ocr` hiện hành. Baseline lịch sử phải có protocol riêng, ghi khác đường xử lý. |
| [accuracy_first](../benchmark/accuracy_first.py) | Là diagnostic trên span/quan hệ được chỉ định. | `TARGETS.mean_ocr_confidence=0.90`, casefold/chuẩn hóa riêng hoặc kết quả trên vài span không thể là cổng nghiệm thu accuracy toàn tài liệu. Không quy tắc này thành lỗi của mọi runner. |

Đã thấy một số text GT và sample layout trong thư mục GT mặc định; **chưa xác nhận hồ sơ GT độc lập, phân xử, bốn partition và coverage đầy đủ** cho corpus nghiệm thu. Không gọi mọi GT hiện có là rỗng, cũng không tự gắn nhãn `HUMAN_VERIFIED`.

## 4. Bộ tiêu chí nghiệm thu cần áp dụng

Các mã `BQ-*` dưới đây là tiêu chí tổ chức đánh giá, không thêm lỗi OCR đã xác nhận vào backlog cũ. Cột trạng thái mô tả bằng chứng trong phạm vi kiểm này.

| Mã | Tiêu chí và đầu ra bắt buộc | Trạng thái hiện tại / điều kiện bổ sung |
| --- | --- | --- |
| BQ-01 | **Đại diện dữ liệu:** manifest PDF/hash/quyền dùng/company/năm/template; tầng scan/native-render/hidden-layer, tiếng Việt pha Anh, chữ nhỏ, xoay, spread, nhiều cột, bảng/công thức; cả trang trắng và trang khó. Báo phân bố mục tiêu và đơn vị lấy mẫu. | Đã đặc tả/đã có inventory; đại diện corpus và coverage tầng chưa nghiệm thu. Đếm nhiều trang trong cùng vài PDF không thay số tài liệu/công ty độc lập. |
| BQ-02 | **GT độc lập:** transcript, vùng/ô, quan hệ đọc, nhãn critical; hai annotator độc lập và phân xử theo đặc tả nghiệm thu; lưu bản nhãn ban đầu, lý do mơ hồ/ignore, lịch sử và hash. Đo bất đồng theo nhóm. | Chưa có hồ sơ đầy đủ. Guideline cũ kiểm mẫu ít nhất 20% khác mức hai annotator của đặc tả mới: phải khóa một quy trình nghiệm thu thống nhất, không tự lấy mức thấp hơn. |
| BQ-03 | **Splits/chống contamination:** bốn partition có quyền truy cập riêng; company/document/template gần trùng không rò rỉ. Public benchmark khai báo khả năng đã có trong train/pretrain; test bị dùng sửa model phải đổi vai trò thành development. | Preflight yêu cầu audit v2 về lịch sử sử dụng, quyền dùng và tham chiếu quyền truy cập. Đã kiểm khóa từ chối đưa tài liệu pilot ra khỏi development. Corpus thật còn chờ rà nhóm và quyền. |
| BQ-04 | **Đánh giá từng công đoạn:** (a) recognizer trên GT crop để tách lỗi đọc; (b) detector/vùng chữ bằng P/R/Hmean với polygon/bbox và matching đã khóa; (c) pha A trên toàn ảnh; (d) end-to-end sau cấu trúc/ghép/export. | Đã có lưu vết mọi detection trước retry và scoreboard bbox nối vào structured GT. GT crop, spotting và scoreboard đủ các tầng trên cùng corpus còn thiếu. Layout mAP không thay detection chữ. [Hợp đồng BQ-04(b)](../benchmark/scientific_evaluation/TEXT_DETECTION_V7.md). |
| BQ-05 | **Text cuối và lỗi nội dung:** CER strict, WER_ws, DER; S/D/I, lặp/thêm chữ, thiếu block/trang, spurious trên GT annotated-empty; per-page/per-document và micro. Giữ raw final artifact, projection và mapping lỗi về source. | Có code text/projection/missing output; chưa đo corpus. Khi reference trống, rate không xác định phải giữ null và báo insertion counts; không gán 0 hoặc “hoàn hảo”. |
| BQ-06 | **Tiếng Việt và ký hiệu:** phân nhóm lỗi dấu thanh/dấu mũ-móc/đ-Đ/hoa-thường; số có 0 đầu, O2O/020, I/l/1, tên/mã, âm/ngoặc, %, ‰, ngày, tiền tệ/đơn vị. Đo cả sửa đúng và làm sai từ vốn đúng. | Guard/review/test đã có; cần ảnh GT và nhóm đối chứng đủ rộng. Không bỏ dấu/casefold/fuzzy để nâng điểm primary. Metric phụ dùng policy khác phải tách bảng. |
| BQ-07 | **Số đúng giá trị và đúng nghĩa:** numeric P/R/F1 theo occurrence/location và cell exact; đánh giá tuple chỉ tiêu–kỳ–đơn vị–phạm vi hợp nhất/mẹ khi thuộc nghiệp vụ. Critical numeric errors và review misses báo counts. | Đã có adapter ô số vào scoreboard/counts, còn thiếu GT/alignment và nhãn tuple nghiệp vụ. Phương trình kế toán chỉ cảnh báo; tổng cân không chứng minh mọi ô đúng và không được sửa số cho cân. |
| BQ-08 | **Bảng:** detection P/R/F1 cùng TEDS-full/TEDS-struct; merged/header/ô rỗng/nhiều trang; đúng cell ownership. Báo missing/spurious và số bảng GT. Bổ sung GriTS hoặc metric ô theo topology/content/location khi cần chẩn đoán. | TEDS/matcher kiểm hợp đồng; nghiệm thu model/adapter còn thiếu. TEDS conditional trên bảng match phải đứng cạnh score toàn GT và detection F1, không che bảng bỏ sót. |
| BQ-09 | **Reading order/layout:** GT precedence từng article/cột; coverage node/cặp, cặp đúng, missing/duplicate, adjacency; ranh giới caption/header/footnote. Không áp total order giả cho hai article độc lập. | Đã nối thứ tự đọc và bbox layout từ extraction vào báo cáo và scorecard. Có kiểm span tách/gộp, adjacency, vùng thừa/thiếu và lớp GT trên fixture. Chưa nghiệm thu trên corpus có nhãn. |
| BQ-10 | **Công thức và modality đã khai báo:** người dùng đã chọn nghiệm thu độ đúng công thức trong v7.0. Cần GT, metric phù hợp, lỗi ký hiệu có nghĩa và failure/coverage riêng. | Công thức là `IN_SCOPE` bắt buộc cho phát hành v7.0. Guard chặn quyết định mơ hồ và không cho cổng vượt khi thiếu evaluator công thức. CDM/GT/ngưỡng chưa hoàn tất. [Phạm vi và phần phải làm](11_NGHIEM_THU_CONG_THUC_V70.md). |
| BQ-11 | **Calibration và review:** định nghĩa “đúng” ở cấp ký tự/token/dòng/ô trước đo; reliability diagram, ECE hoặc Brier nếu phù hợp đơn vị; risk–coverage/abstention, false accept/reject, recall/precision review và phút/cost người kiểm. Báo trước review, subset tự nhận và sau review riêng. | Có bộ chấm calibration, binding nguồn và packet review; nhãn độc lập, thời gian và report thực còn thiếu. Confidence/quality heuristic không thay nhãn đúng; chọn ngưỡng trên calibration rồi khóa, không trên holdout. |
| BQ-12 | **Thống kê và rủi ro:** counts + micro + macro theo tài liệu, CI 95% theo cụm, paired difference, family kiểm định và noninferiority margin đã duyệt; kế hoạch cỡ mẫu theo precision/rủi ro và từng tầng critical. | Đã có bootstrap/Holm; chưa có counts/GT/run đủ để nghiệm thu. Không lấy mặc định hàm, CI suy biến hoặc nhiều cell cùng PDF làm đủ lực thống kê. |
| BQ-13 | **Tái lập và đối chuẩn:** GT/splits/projection/matching/evaluator revisions, code diff, model/lock/interpreter/hardware, seed, inference options và raw output bất biến. Baseline/candidate chạy cùng tài liệu/protocol; benchmark công khai dùng adapter đúng version. | Đã có adapter canonical GPU và pin evaluator; paired quality và adapter bộ công khai còn thiếu. Không quy điểm công bố của hệ thống khác thành kết quả A/B trên PDF dự án. |
| BQ-14 | **Vận hành và sau phát hành:** p50/p95/throughput toàn quy trình, cold/warm/cache tách, RSS/VRAM/cost, timeout/OOM/retry, process-tree exit, full-page coverage, resume/prepare/ack và soak/fault plan output riêng; drift/tài liệu mới có mẫu nhãn. | Có kiểm hợp đồng/receipt và batch lịch sử; tải dài, hiệu năng ổn định và drift chưa nghiệm thu. Không dùng tốc độ test double làm inference hoặc resource SLO chưa duyệt làm PASS. |

## 5. Ngưỡng chất lượng và quy tắc quyết định

Giữ các **ngưỡng đề xuất của dự án** trong đặc tả mục 15: CER micro strict ≤ 0,1%; cell numeric exact ≥ 99,99%; observed critical numeric errors = 0; TEDS content/structure ≥ 0,98; reading-order precedence có phạt thiếu ≥ 99,5%; coverage các đơn vị GT đã khai báo = 100%. Đề xuất auto-accept coverage ≥ 95% và review miss không critical ≤ 1% cũng còn cần khóa trên calibration. **Đây không phải ngưỡng chung do các benchmark công khai hay mọi doanh nghiệp quy định, và chưa là kết quả đã đạt.**

- Phải xác định ngưỡng áp lên estimate hay cận CI trước đo. Không tự đổi điều kiện point estimate thành CI, hoặc ngược lại sau khi xem kết quả. WER_ws, DER, từng subgroup, calibration, latency/cost còn cần giá trị/rationale được duyệt; thiếu giữ null.
- Noninferiority là cổng bổ sung: một candidate không kém baseline nhưng cả hai dưới ngưỡng tuyệt đối vẫn chưa đạt. Điểm trung bình cao không bù được lỗi critical bị bỏ qua review.
- Báo riêng **annotation coverage** của population mục tiêu, **evaluation coverage** trên GT đã khóa và **auto-accept coverage**; ba mẫu số khác nhau. `NOT_EVALUATED` không phải đạt và không tự biến thành 0.
- Scalar 1,0 ở output `NO_TABLES` hoặc `not_evaluated_empty_reference` không là bằng chứng chất lượng. Consumer phải xét status, denominator và counts trước score; test evaluator và bộ tổng hợp cần kiểm trường hợp này.
- Khi không quan sát lỗi trong `n` phép thử Bernoulli độc lập, cận trên xác suất lỗi một phía 95% là `1 - 0,05^(1/n)`. Muốn cận dưới accuracy 99,99% theo giả thiết này cần ít nhất **29.956** phép thử độc lập không lỗi. Đây là minh họa toán học, **không phải chỉ tiêu gom 29.956 cell trong vài PDF**. Dữ liệu tương quan cần thiết kế cụm/precision phù hợp; không quan sát lỗi không chứng minh rủi ro bằng 0.

Ba cổng độc lập:

1. **Sẵn sàng đo:** population/splits/GT, guideline/phân xử, metric/matching/projection, sample-size plan và ngưỡng đã khóa; adapter qua contract/parity tests. Chưa đủ thì `NOT_READY_FOR_ACCEPTANCE_MEASUREMENT`.
2. **Đạt chất lượng trong phạm vi:** có run thật trên tập đã khóa; tất cả metric/subgroup bắt buộc có denominator/CI hợp lệ và đạt rule đã duyệt; mọi missing output được tính; giải quyết critical defects. Nếu thiếu một phần bắt buộc thì `NOT_EVALUATED` cho phần đó và chưa cấp nghiệm thu tổng thể.
3. **Đủ phát hành/vận hành:** thêm SLO/soak/phục hồi, human review capacity, người kiểm độc lập và quyết định phát hành. Chỉ có điểm benchmark không thay cổng vận hành.

## 6. Hợp đồng nghiệm thu đề xuất

[Mẫu protocol YAML](templates/benchmark_acceptance_protocol.example.yaml) gom ID/hash, partition, projection, metric, ngưỡng, sample-size/CI, review và runtime. Mẫu giữ **DRAFT** để chuẩn bị hồ sơ cho `protocol_preflight` và `release_gate`. Các null là phần còn thiếu và cần bằng chứng trước khi được duyệt. Ngày 05/11 đã nối count công thức từ replay vào mẫu và họ kiểm định chung. [Hướng dẫn hiện tại](../benchmark/scientific_evaluation/FORMULA_FAMILY_V7.md).

Tối thiểu mỗi metric record phải nhận dạng: protocol/run/document/page/source hoặc cell; GT revision và trạng thái annotation; prediction/evaluator hash; normalization/projection/matching; numerator/denominator và S/D/I hoặc TP/FP/FN khi áp dụng; missing/ignore/abstain; unit/cluster/subgroup; estimate/CI; threshold/rule và verdict. Record đơn vị không có GT khác với record GT đã xác nhận rỗng.

Một benchmark bundle cần kèm input/split/GT manifests, annotation/adjudication log, protocol.lock và evaluator tests, prediction receipts, counts cấp đơn vị, bảng subgroup/CI, baseline comparison, danh sách lỗi dẫn về ảnh/source và quyết định có người duyệt. Chỉ số không thể chấm phải có reason, không biến thành zero hay bị bỏ khỏi danh sách bắt buộc.

## 7. Đầu việc bổ sung vào quy trình cải tiến

Giữ 23 ID của backlog gốc; các đầu việc dưới đây là phần triển khai chi tiết, có thể gắn vào phiếu SESSION. Người thực hiện/kiểm độc lập, lịch và công chưa được phân công/ước lượng. Chưa thay đổi mã trong phiên audit này.

| Việc | Gắn backlog | Đầu ra / điều kiện đóng |
| --- | --- | --- |
| BK-01 — Khóa protocol và thống nhất guideline | GAP-01/02/05/08 | Population, GT độc lập và quy tắc phân xử thống nhất; chốt cách primary text/HTML/pipe table, WER_ws, critical và subset/CI. Không ghi HUMAN_VERIFIED khi thiếu nhãn/người duyệt. |
| BK-02 — Enforcement bốn partition | GAP-02, DC-06 | Schema/adapter calibration version mới; kiểm company/template near-duplicate, membership/hash/access; ca rò rỉ/đổi GT/đổi split bị từ chối, đọc/từ chối schema cũ có policy rõ. |
| BK-03 — Nối scoreboard end-to-end | GAP-02/05, DC-03/04/05 | Adapter từ extraction/cell/source GT sang text/numeric/table/order/layout; TEDS và numeric không còn NOT_EVALUATED khi GT hợp lệ; thiếu output/duplicate/annotated-empty đều có counts. Nối partial-order mới hoặc ghi rõ protocol cũ. |
| BK-04 — Corpus khó và kiểm nội dung PDF | GAP-01/02/03/04, DC-01/02 | Tầng khó và đối chứng có nhãn; sự kiện hiện diện/vắng mặt, multiplicity, adjacency/ownership, công thức nếu trong scope; raw/bbox không mất. Fixture không được thay tập nghiệm thu. |
| BK-05 — Calibration/review có nhãn | GAP-02, DC-06 | Định nghĩa label/unit, reliability và risk–coverage; ngưỡng khóa trên calibration, báo review misses/precision/time/cost và kết quả trước/sau; không tự duyệt bằng score. |
| BK-06 — Cỡ mẫu, CI và scorecard theo tầng | GAP-02/05/07 | Precision/power/risk plan, counts theo company/document/subgroup; paired bootstrap/Holm có kiểm độc lập, absolute gate và noninferiority riêng; ít cụm/CI suy biến không cấp acceptance. |
| BK-07 — Adapter đối chuẩn hiện hành | GAP-05/07 | Tách baseline lịch sử khỏi canonical GPU full-page; pin external dataset/evaluator và model versions, ghi native/hidden-text policy. Chạy paired cùng input, báo version/mapping và contamination limits. Không chạy matrix CPU cũ như production mới. |
| BK-08 — Gate phát hành và giám sát | GAP-06/07, WF-01 | Validator protocol/GT/coverage/status/denominator/identity; unit pass hoặc audit receipt không thể tự cấp accuracy. SLO/soak output mới, drift sampling và quyết định độc lập. Không sửa receipt/hash của batch cũ. |

Thứ tự: chuẩn bị BK-01/02/04 trước; BK-03 và parity/invalid-input tests chạy trên development; BK-05/06 khóa trên calibration; chỉ mở holdout sau chốt candidate/BK-07; BK-08 tổng hợp điều kiện phát hành. Không sửa ngưỡng sau khi xem holdout. Thiếu GT vẫn có thể hoàn thiện adapter/validator, nhưng chưa được đóng nghiệm thu chất lượng.

## 8. Kết quả của phiên này

Đã kiểm mã/tài liệu và đối chiếu năm nguồn chính; chạy 159 kiểm thử liên quan đạt; bổ sung bộ tiêu chí, khoảng cách triển khai, tám gói việc và mẫu protocol DRAFT. **Chưa có benchmark OCR thực nghiệm mới, chưa công bố xếp hạng/SOTA, chưa nghiệm thu corpus hoặc chạy soak/GPU.** Kiểm tài liệu và bảo toàn mã được lưu trong [evidence](evidence/benchmark_quality_audit_20261103.json); nhật ký/snapshot đầy đủ trong `scratch/dev_sessions/20261103-benchmark-quality/` chỉ có trên máy, cần mang kèm khi bàn giao.

## Kiểm hồ sơ trước khi mở holdout

Phần kiểm đầu vào của BK-01/BK-08 đã có CLI riêng. Giữ nguyên mẫu DRAFT. Khi người phụ trách đã duyệt hồ sơ, lưu một bản protocol mới với `status: LOCKED`, `approved_by`, `locked_at` là chuỗi ISO 8601 có múi giờ, `thresholds.status: APPROVED` và các giá trị đã chốt. Giữ `decision.acceptance_status: NOT_EVALUATED` ở giai đoạn này.

Phạm vi công thức dùng object `formula_scope_decision` với `decision: IN_SCOPE` và `reason`, đồng thời có `formulas` trong `declared_modalities`. Chuỗi tự do cũ không được dùng để mở nghiệm thu. CLI preflight và release gate kiểm `V70_RELEASE`, bắt buộc công thức theo quyết định người dùng. Thư viện preflight có thể kiểm bộ đo thành phần `COMPONENT_MEASUREMENT` loại trừ công thức có lý do, nhưng kết quả đó không cấp nghiệm thu v7.0. [Quy tắc chuyển đổi và dữ liệu còn thiếu](11_NGHIEM_THU_CONG_THUC_V70.md).

```powershell
.venv/Scripts/python.exe -m benchmark.scientific_evaluation.protocol_preflight scratch/HOSO/protocol.locked.yaml --artifact-index scratch/HOSO/artifacts.yaml
```

`artifacts.yaml` ánh xạ từng khóa đầy đủ trong [`REQUIRED_ARTIFACTS`](../benchmark/scientific_evaluation/protocol_preflight.py) tới đường dẫn tệp tương đối với thư mục index. Ví dụ, `data.input_manifest_sha256` trỏ đến CSV inventory đã dùng để tạo splits-v2, `data.split_manifest_sha256` trỏ đến khóa splits-v2 và `data.near_duplicate_audit_sha256` trỏ đến audit gốc. Các giá trị SHA-256 tương ứng nằm trong protocol. CLI đối chiếu các hash và tính lại membership, nhóm và người giữ holdout từ ba file này.

Nghiệm thu mới yêu cầu `split-leakage-audit-v2`. Audit khai báo các tài liệu chỉ dùng development, hồ sơ quyền sử dụng và bằng chứng tách quyền truy cập calibration/holdout. Người phụ trách kiểm trực tiếp nội dung các hồ sơ được dẫn trước khi khóa. [Cấu trúc audit](../benchmark/ground_truth_tools/ANNOTATION_V6.md#phân-tập-và-rà-rò-rỉ).

BK-02 có công cụ rà cặp nguồn theo SHA-256 PDF, ảnh thu nhỏ, bố cục và cụm chữ trên trang. Worklist ghi số trang vật lý, mức tương đồng và phần không đủ tín hiệu. Dùng các vị trí này để đối chiếu mẫu, nội dung gần trùng và tên đơn vị trước khi ký audit. Các trường nhóm và phân tập vẫn chờ quyết định của người phụ trách. [Lệnh và cách đọc worklist](../benchmark/ground_truth_tools/ANNOTATION_V6.md#tạo-danh-sách-cặp-pdf-để-rà).

Exit 0 trả `INPUTS_VERIFIED` cho cấu hình và file khớp danh tính. Exit 1 báo mục thiếu hoặc sai, exit 2 báo input không đọc hoặc không phân tích được. Người phụ trách vẫn kiểm nội dung nhãn, độc lập của người gán nhãn, quyền holdout và tính phù hợp của ngưỡng. Chất lượng giữ `NOT_EVALUATED` cho tới khi có lượt chạy và bằng chứng chấm. Gate sau lượt chạy, SLO và soak thuộc phần còn lại của BK-08.

## Nối benchmark với batch CUDA đã công bố

Adapter BK-07 đọc batch gốc, kiểm revision SQLite đã acknowledge và hash workbook, rồi xác minh danh tính OCR, SHA-256 PDF, đủ trang, hợp đồng nguồn GPU, receipt và thứ tự thoát tiến trình. Báo cáo giữ riêng fingerprint do export ghi và fingerprint cấu hình batch. Stage được tái dùng có danh sách riêng. Workbook gộp từ analysis-only dùng cho đối chiếu keyword.

```powershell
.\.venv\Scripts\python.exe -B -m benchmark.scientific_evaluation.canonical_predictions `
  --candidate output/unified_aaa_abt_agr_gpu_20261104 output/unified_vic_pilot_gpu_20261104 `
  --report scratch/canonical_predictions_new.json
```

Nếu có baseline canonical riêng, thêm `--baseline <batch>` để ghép cặp theo ID, SHA-256 PDF và số trang. Exit 0 xác nhận danh tính predictions. Exit 1 trả `PREDICTIONS_REJECTED` cùng lý do. Báo cáo ghi `accuracy: NOT_EVALUATED`. Adapter đối chuẩn bộ công khai và kết quả paired quality trên GT đã khóa là phần việc tiếp theo của BK-07.

BK-07 hiện có adapter paired sang OmniDocBench ở commit `ea2d138c7d2e185feb71ef8014e97d7206820b34`. Adapter kiểm ảnh/PDF một trang, publication canonical và GT snapshot, rồi xuất Markdown từng ảnh, asset và config cho hai phía. Đã kiểm contract resolver chính thức trên fixture; evaluator và inference trên bộ công khai chưa chạy. [Hướng dẫn và giới hạn](../benchmark/scientific_evaluation/OMNIDOCBENCH_V7.md).

Khi chấm từng tài liệu, thêm `--canonical-batch <batch>` cho `scripts/run_scientific_benchmark.py`, giữ `--prediction <batch>/<doc_id>` và đặt `--output-dir` ngoài batch. Báo cáo đính kèm bằng chứng của prediction. Để chấm nội dung, truyền GT văn bản và GT cấu trúc theo hợp đồng hiện hành. Runner yêu cầu SHA-256 đầy đủ của GT cấu trúc khớp PDF đã xác minh. Kết quả CLI là chẩn đoán theo GT được cung cấp. Nghiệm thu cần thêm hồ sơ độc lập, ngưỡng và protocol khóa.

## Đo calibration và hiệu quả review

BK-05 có CLI đọc ba JSON đã căn theo nguồn và kiểm lại `splits-v2` từ inventory cùng audit. Mỗi lượt dùng một đơn vị dòng hoặc ô và một định nghĩa điểm. Đúng nghĩa là khớp toàn bộ bản chép theo `visible_strict_v1`, giữ dấu, hoa thường, số và khoảng trắng.

- `review-calibration-sample-v1` khai báo `partition`, `split_sha256`, `unit` (`line` hoặc `cell`), `normalization`, `score_semantics` (`rank` hoặc `probability_of_exact_match`), `score_protocol_sha256`, `label_definition_sha256` và `currency` (mã ba chữ như VND). Mỗi đơn vị trong `units` có `unit_id`, `document_id`, `pdf_sha256`, `page` và `source_id`. Chốt mẫu và ánh xạ trước khi đối chiếu nhãn.
- `review-calibration-labels-v1` chứa `sample_sha256`, `independent_reviewer`, `adjudication_sha256` và `units` với `unit_id`, `text`, `critical`. Chuỗi rỗng biểu thị nội dung đã xác nhận rỗng. Thiếu mục nhãn nghĩa là chưa đánh giá đơn vị.
- `review-calibration-predictions-v1` chứa `sample_sha256`, `score_protocol_sha256` và `units` với `unit_id`, `text`, `score`, `mandatory_review`. Dùng `null` khi thiếu điểm hay đầu ra. Review thực tế ghi `review` gồm `text` sau sửa và `seconds`, `cost` nếu đã đo. Giữ hồ sơ căn vùng/ô, receipt prediction và bằng chứng sửa riêng theo giao thức đo.

```powershell
.\.venv\Scripts\python.exe -B -m benchmark.scientific_evaluation.review_calibration `
  --sources sources.csv --splits splits.locked.json --audit split-audit.json `
  --score-protocol score-protocol.json --label-definition label-definition.md `
  --adjudication adjudication.json --sample calibration-sample.json `
  --labels calibration-labels.json --predictions calibration-predictions.json `
  --threshold 0.9 --report scratch/calibration-new.json
```

`0.9` là ví dụ cú pháp. Báo cáo calibration có đường risk–coverage với các điểm bằng nhau đi cùng nhau. Cờ bắt buộc review, điểm thiếu và output thiếu luôn chuyển review. Risk dùng số đơn vị đã gán nhãn trong nhóm tự nhận làm mẫu số. Recall review dùng số lỗi đã quan sát. Precision review dùng số đơn vị có nhãn được chuyển review. Chi phí và thời gian chỉ cộng tổng khi có bản ghi cho mọi đơn vị đã review. Trước/sau dùng cùng các đơn vị đã review thực tế có nhãn. ECE/Brier chỉ tính khi giao thức định nghĩa điểm là xác suất đúng toàn đơn vị.

Sau khi người duyệt chọn ngưỡng đã chạy trong báo cáo calibration đầy đủ, lưu file `review-threshold-lock-v1` với `status: LOCKED`, `approved_by`, `locked_at` có múi giờ, `threshold` và `calibration_report_sha256`. Đưa hash file khóa vào `review.calibrated_thresholds_sha256` của protocol nghiệm thu. Với mẫu holdout, thay `--threshold` bằng `--policy <file-khóa>` và `--calibration-report <báo-cáo>`. CLI kiểm cùng split, định nghĩa điểm/nhãn và ngưỡng đã đo, rồi chỉ áp dụng ngưỡng đã khóa. Người quản lý holdout chịu trách nhiệm khóa trước khi mở dữ liệu.

Exit 0 báo mẫu có đủ nhãn để đo, exit 1 báo thiếu nhãn, exit 2 báo input sai hợp đồng. `acceptance_status` luôn là `NOT_EVALUATED` ở CLI này. Kết quả dùng bản ghi đã căn do người dùng cung cấp, cần kiểm độc lập nội dung nhãn, nguồn dự đoán, quyền truy cập holdout và cỡ mẫu trước nghiệm thu.

### Ghim bản ghi review vào extraction đã công bố

Ở chế độ canonical, thêm `bbox` dạng `xyxy`, `coordinate_space` và `transforms` vào từng unit nguồn trong mẫu. Chốt mẫu cùng định nghĩa nhãn trước khi đối chiếu prediction. Hai người gán nhãn A/B đọc ảnh độc lập và phân xử để lập GT. Bước căn prediction thực hiện riêng sau khi đã khóa các bản chép nguồn.

`review-canonical-score-protocol-v1` có `unit`, `score_semantics: rank` và `source_field`. Với `line`, dùng `quality_score` của một text block hiển thị chỉ chứa một dòng. Với `cell`, dùng `confidence` của ô theo ID bảng và hàng/cột. Heuristic dùng xếp hạng. Ô định vị theo bbox bảng, cờ review của ô/bảng, cờ review dòng hoặc điểm thiếu đều bắt buộc review. Không có cơ chế tự ghép dòng tách/gộp trong adapter BK-05 này.

Lập `review-canonical-alignment-v1` có `sample_sha256`, `prediction_manifest_sha256`, `reviewed_by`, `reviewed_at` (ISO 8601 có múi giờ), `reviewed_against_source: true` và `units`. `prediction_manifest_sha256` tính bằng `sha256_json_compact` trên đối tượng `candidate` từ báo cáo canonical inventory của batch sẽ dùng. Giữ cùng thứ tự batch roots khi tái lập inventory.

- Mỗi unit ghi `unit_id`, `source_id`, `reason`, `status` và locator khi khớp. `MATCHED` trỏ `locator: {"item_id": "..."}` với dòng, hoặc thêm `row`, `col` bắt đầu từ 0 với ô. Locator phải nằm đúng trang, giao bbox nguồn và chỉ dùng một lần.
- `MISSING_OUTPUT` cần quyết định có lý do sau đối ảnh và để locator trống. Không thay vắng mặt bằng một chuỗi rỗng, một ID gần nhất hay một ô đoán được.
- Lệnh xuất đọc lại văn bản, điểm, cờ review, bbox và provenance từ extraction được ghim bằng completion/receipt. Muốn đo sau review, giữ file ban đầu và chỉ thêm trường `review` vào từng unit trong bản nộp riêng. Trường này dùng bản sửa và số đo người kiểm đã ghi, nếu có.

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
.\.venv\Scripts\python.exe -B -m benchmark.scientific_evaluation.review_prediction_source `
  --canonical-batch output/RUN --sample calibration-sample.json `
  --score-protocol score-protocol.json --alignment calibration-alignment.json `
  --output scratch/calibration-predictions-new.json
```

Khi đo bằng `review_calibration`, truyền lại cùng `--canonical-batch` cho từng batch. Bộ đo tái lập các quan sát trước review và từ chối thay đổi. Báo cáo ghim manifest dự đoán, extraction SHA-256 từng tài liệu và hash alignment. Chế độ bản ghi cũ giữ được báo cáo chẩn đoán, còn cổng phát hành giữ source binding ở `NOT_EVALUATED` cho đến khi có dữ liệu canonical.

Trước khi mở holdout, ghim file mẫu review vào `review.holdout_sample_sha256` và thêm khóa này vào artifact index. Gate kiểm mẫu đã khóa trùng với mẫu trong index đầu vào và báo cáo đã tính. Bổ sung trường trên bản protocol mới khi lập hồ sơ duyệt.

## Scorecard theo tầng và kế hoạch cỡ mẫu

BK-06 đọc protocol đã khóa qua preflight và bốn artifact JSON đã pin trong protocol. Khóa ID của họ kiểm định trước khi mở holdout. Các ID phải khớp giữa bốn file.

- `ocr-comparison-family-v1` tại `statistics.multiple_comparison_family_sha256` có `tests` ánh xạ ID sang `metric` và `stratum`. Tầng `overall` bao phủ toàn mẫu đã khai báo cho metric. Các metric có mẫu số GT cộng được gồm `cer`, `wer` (WER_ws), `der`, `teds_content`, `teds_structure`, `numeric_cell_exact`, `reading_order` và `keyword_recall`. Với TEDS, cộng điểm trên mọi bảng GT và cho bảng bỏ sót điểm 0. F1 cần hợp đồng TP/FP/FN riêng.
- `ocr-sample-precision-plan-v1` tại `statistics.sample_size_and_precision_plan_sha256` có `sample_sha256` và `comparisons`. Mỗi ID khai báo `minimum_companies`, `minimum_documents`, `minimum_denominator`, `maximum_ci_width` và `power` gồm `target`, `pilot_company_influence_sd`, `detectable_gap`, `pilot_sha256`. Có thể thêm `zero_event_company_risk_max` cho kế hoạch rủi ro sự kiện cấp công ty.
- `ocr-absolute-thresholds-v1` tại `thresholds.subgroup_thresholds_sha256` có `comparisons` ánh xạ ID sang `threshold` và `basis` (`point` hoặc `confidence_bound`). Ngưỡng `overall` tương ứng phải khớp trường ngưỡng của protocol.
- `ocr-noninferiority-margins-v1` tại `thresholds.baseline_noninferiority_margins_sha256` có `comparisons` ánh xạ ID sang margin không âm theo đơn vị metric.

Cỡ mẫu theo power là xấp xỉ chuẩn một phía dùng SD influence cấp công ty từ pilot độc lập, khoảng cách tối thiểu tới biên giả thuyết và alpha Bonferroni cho họ đã khóa. Người duyệt kiểm giả định cụm độc lập và phương pháp ước lượng SD. Sàn rủi ro zero-event dùng `ceil(log(1-confidence)/log(1-risk))` với sự kiện Bernoulli ở cấp **công ty độc lập**. Phép tính này là yêu cầu lập kế hoạch, cần hồ sơ sự kiện riêng để suy ra rủi ro quan sát. Cổng precision kiểm độ rộng CI thực tế. Sàn công ty là giá trị lớn nhất giữa sàn protocol, sàn theo tầng, sàn power và sàn rủi ro nếu có.

```powershell
.\.venv\Scripts\python.exe -B -m benchmark.scientific_evaluation.stratified_scorecard `
  --protocol protocol.locked.yaml --artifact-index artifacts.yaml `
  --sample holdout-sample.json --prediction-inventory paired-predictions.json `
  --baseline baseline-counts.json --candidate candidate-counts.json `
  --report scratch/stratified-scorecard-new.json
```

Mẫu `ocr-holdout-scorecard-sample-v1` có `units` với `unit_id`, `document_id`, `pdf_sha256`, `page`, `region_id`, `metrics` và `strata`. Inventory ghép cặp là báo cáo của adapter BK-07. Mỗi file `ocr-paired-counts-v1` có `run_id`, `sample_sha256`, `gt_sha256`, `normalization`, `prediction_inventory_sha256`, `prediction_manifest_sha256` (digest `sha256_json_compact` của object phía baseline hoặc candidate trong inventory), và `records_by_metric`. Mỗi record gồm `unit_id`, `status` và cặp `numerator`, `denominator` nếu đã chấm. Giữ `MISSING_OUTPUT` với mẫu số GT để áp phạt, `NOT_EVALUATED` khi thiếu nhãn. Text trên GT rỗng vẫn có thể đóng góp insertion vào tử số micro.

Báo cáo giữ số đơn vị dự kiến, đã chấm, thiếu output, số đếm theo công ty và tài liệu, micro, macro theo tài liệu, CI percentile chưa hiệu chỉnh cho hai điểm và chênh lệch. CI suy biến, quá rộng, ít cụm hoặc thiếu cặp giữ cổng tương ứng ở `NOT_EVALUATED`. Holm dùng toàn họ và giữ slot chưa đo với p dùng hiệu chỉnh bằng 1. Exit 0 khi mọi cổng thống kê trong họ đã khóa đạt, exit 1 khi có cổng trượt hoặc chưa đo, exit 2 khi lỗi hợp đồng. Nghiệm thu tổng thể và kiểm tính đúng của count nguồn thuộc BK-08.

## Xuất số đếm trực tiếp từ đầu ra CUDA đã xác minh

`data.gt_manifest_sha256` trỏ tới manifest JSON `ocr-scorecard-gt-v1`. Trong `documents`, mỗi khóa là ID tài liệu và có `pdf_sha256`. Khai báo `text_pages` theo số trang vật lý nếu có bản chép UTF-8, `structure` nếu có `structured-page-gt-v1` và `keywords` nếu có `keyword-source-gt-v1`. Các mục file đều dùng `path` tương đối trong thư mục manifest và `sha256`. Trang được xác nhận rỗng dùng file bản chép rỗng. Trang chưa gán nhãn không có mục bản chép.

```powershell
.\.venv\Scripts\python.exe -B -m benchmark.scientific_evaluation.scorecard_counts `
  --protocol protocol.locked.yaml --artifact-index artifacts.yaml `
  --sample holdout-sample.json --prediction-inventory paired-predictions.json `
  --side candidate --output scratch/candidate-counts.json
```

Chạy tương tự với `--side baseline` và đường dẫn mới. Metric văn bản và cấu trúc dùng `region_id: page`. Văn bản được chấm từ marker trang của `result.md`, marker lặp hoặc ngoài số trang hợp lệ bị từ chối. Cấu trúc dùng `extraction.json` và xuất tổng TEDS trước khi làm tròn, TP/FN ô số theo vị trí và số cặp thứ tự đúng. Số bảng thừa và lỗi ngoài mẫu số recall vẫn có trong bằng chứng theo đơn vị.

Với keyword, dùng `region_id` đúng ID vùng trong GT keyword và thêm `--keyword-alignments <index.json>`. Index `ocr-keyword-alignment-index-v1` ghi `side`, `prediction_inventory_sha256` và `documents` ánh xạ ID tài liệu sang `path` và `sha256` của file căn nguồn đã được rà. Mỗi file căn nguồn phải trỏ đến đúng bản GT và publication. Vùng chưa căn đủ giữ `NOT_EVALUATED`.

Với reading order, trang GT khai báo `alignment_mode: reviewed_spans` cần artifact căn span đã rà. Dùng `--reading-order-alignments <index.json>` cho từng bên và hai cờ tương ứng khi chạy `release_gate`. Điểm từng trang giữ tử số cặp đúng, mẫu số toàn bộ cặp GT và hash artifact căn nguồn. Giữ `NOT_EVALUATED` khi còn trang đã xuất nhưng thiếu căn bắt buộc. [Hợp đồng span và index](../benchmark/ground_truth_tools/ANNOTATION_V6.md#căn-thứ-tự-đọc-khi-khối-bị-tách-hoặc-gộp).

Với layout, đặt `layout` theo trang trong `structured-page-gt-v1`, ghi rõ `intended_partition: holdout` khi dùng scorecard. Nếu khai báo modality này, khóa ngưỡng và margin cho `layout_recall` và `layout_errors_per_gt`. Cổng yêu cầu đủ lớp bắt buộc. COCO mAP chẩn đoán được tính riêng khi có backend và GT, do mAP không gộp theo trung bình mỗi trang. [Hợp đồng bố cục](../benchmark/ground_truth_tools/ANNOTATION_V6.md#chấm-bố-cục-vật-lý).

Bộ xuất kiểm protocol, scope mẫu, SHA-256 của GT và receipt của prediction. Exit 0 xác nhận đã xuất số đếm cho mọi đơn vị/metric, exit 1 có phần chưa chấm, exit 2 lỗi dữ liệu hoặc định danh. Cổng nghiệm thu vẫn cần kiểm nhãn độc lập, cấu hình chấm và điều kiện vận hành.

## Cổng BK-08 sau lượt chạy

`release_gate` chấm lại hai phía từ GT khóa, tính lại scorecard và kiểm riêng review, vận hành. Báo cáo giữ số đếm nguồn theo đơn vị. Các metric overall bắt buộc gồm CER, WER_ws, DER, TEDS content/structure, ô số exact và reading order. Thêm keyword recall khi khai báo modality keywords. Modality ngoài hợp đồng hiện hành giữ `NOT_EVALUATED`. Cổng tính lại coverage theo mẫu đã khóa.

```powershell
.\.venv\Scripts\python.exe -B -m benchmark.scientific_evaluation.release_gate `
  --protocol protocol.locked.yaml --artifact-index artifacts.yaml `
  --sample holdout-sample.json --prediction-inventory paired-predictions.json `
  --operational-evidence operational-evidence.json --report scratch/release-gate-new.json
```

Trước chạy, `evaluation.evaluator_commit_and_dirty_diff_sha256` cần manifest `ocr-evaluator-files-v1` có `modules` ánh xạ đúng các tên trong `release_gate.EVALUATOR_MODULES` sang SHA-256 file hiện tại. `evaluation.projection_code_sha256` là hash `markdown_evaluator.py`. Manifest lock `ocr-dependency-lock-manifest-v1` có `locks` khớp bản ghi runtime candidate. Manifest `ocr-interpreter-hardware-v1` ghi `text_python`, `docling_python` và `gpu` với `device`, `total_mib`. Registry model đã pin phải xuất hiện trong bản ghi model của candidate. Các file này dùng các trường runtime/evaluation tương ứng trong protocol.

Index vận hành `ocr-release-operational-evidence-v1` khai báo `protocol_sha256`, `prediction_inventory_sha256`, `operator` và các file qua cặp `path`, `sha256` tương đối trong thư mục index.

- `holdout_review` trỏ báo cáo BK-05. `review_inputs` trỏ index `ocr-release-review-inputs-v1` có `prediction_manifest_sha256` của candidate và `files` gồm sample, labels, predictions, score_protocol, label_definition, adjudication, policy, calibration_report. Mỗi file dùng cặp path/hash. Gate tính lại báo cáo và xác minh quan sát holdout từ candidate.
- Trong `ocr-release-review-inputs-v1`, `calibration_inputs` là cặp path/hash trỏ `ocr-release-review-calibration-inputs-v1`. Index con có `batch_roots` là các đường dẫn tuyệt đối đến batch canonical đã công bố, và `files` gồm sample, labels, predictions, adjudication của calibration. Gate kiểm cùng cấu hình OCR với candidate, cùng score protocol, định nghĩa nhãn, split và ngưỡng khóa rồi tính lại báo cáo calibration. Thiếu nguồn calibration hoặc holdout giữ cổng review chưa đủ điều kiện PASS.
- `review_capacity` trỏ `ocr-review-capacity-v1` với `approved_by`, `locked_at` có múi giờ, `review_report_sha256`, `currency`, `expected_units_per_day`, `available_seconds_per_day` và `cost_budget_per_day`. Đơn vị công việc theo cùng định nghĩa dòng/ô của báo cáo review. Gate ước tính tải review từ tỷ lệ chuyển review và thời gian/chi phí thực tế.
- `operation_plan` trỏ `ocr-operation-plan-v1` và khớp `runtime.warm_cold_repeated_run_plan_sha256`. Plan có `workload_pdf_sha256`, `minimum_runs` cho cold/warm/cache (ít nhất hai lượt mỗi loại), `minimum_soak_minutes` và danh sách `recovery_scenarios` đã duyệt.
- `slos` trỏ `ocr-operation-slos-v1` và khớp `runtime.latency_resource_cost_slos_sha256`. File có `currency` và `modes` theo cold/warm/cache. Mỗi mode khai báo các khóa trong `release_gate.SLO_LIMITS`, gồm p50/p95 mỗi PDF, trang/giây, RSS/VRAM đỉnh, chi phí mỗi trang và giới hạn timeout/OOM/retry.
- `operational_runs` là danh sách file `ocr-operation-trace-v1`. Mỗi trace có `run_id`, `batch_roots`, `inventory_sha256` (digest object do `collect_predictions` trả), `mode`, `currency`. Mode đo thông thường có `elapsed_seconds`, `document_seconds` theo ID, `peak_rss_mib`, `peak_vram_mib`, `cost`, `retries`, `timeouts`, `oom`. Mode recovery có thêm `scenario`, `interrupted_at` có múi giờ và `recovered_publication_verified: true`. Giữ trace sự cố, các log gốc và phép đo để người kiểm độc lập rà.
- `drift_sampling_plan` trỏ `ocr-drift-sampling-plan-v1`, gồm `owner`, `interval_days`, `minimum_documents`, `strata`, `escalation_trigger` và `independent_annotation_required: true`. Gate yêu cầu `status: LOCKED`, `approved_by` và `locked_at` có múi giờ để điều kiện kế hoạch đạt. Bản nháp giữ điều kiện vận hành `NOT_EVALUATED`. Bộ lấy mẫu lập worklist từ PDF và trang vật lý đã xác minh, ghi phần còn thiếu và phát hai phiếu trắng để rà độc lập. [Hợp đồng lấy mẫu](../benchmark/scientific_evaluation/DRIFT_SAMPLING_V7.md).

Gate đọc lại batch, SQLite, workbook và receipt của mọi lượt vận hành. Mỗi lượt dùng output mới và đúng tập PDF của plan. Gate đối chiếu cùng cấu hình extraction (gồm DPI, assets, output mode), model, dependency, code và GPU của candidate. Lượt cache cần bằng chứng stage reuse. Thời lượng soak là tổng thời gian các lệnh OCR mới thuộc cold/warm. Người vận hành ghi rõ điều kiện cold/warm, lịch chạy và cách đo tài nguyên trong trace. Đỉnh từ lấy mẫu là đỉnh quan sát được. Thiếu đơn giá giữ cost null và cổng chi phí `NOT_EVALUATED`.

Khi ba cổng chất lượng/review/vận hành đạt, báo cáo có `AWAITING_INDEPENDENT_DECISION` và `evidence_sha256`. Người kiểm độc lập lưu `ocr-independent-release-decision-v1` có `reviewer`, `reviewed_at`, `evidence_sha256`, `status` (APPROVED hoặc REJECTED), số `observed_critical_numeric_errors`, `unresolved_critical_defects`, `drift_sampling_plan_sha256` và bốn xác nhận `independent_gt_checked`, `critical_scope_checked`, `runtime_trace_checked`, `drift_sample_checked`. Các xác nhận phải đúng với hồ sơ thật. Danh tính reviewer phải khác người duyệt protocol, người giữ holdout và operator. Chạy lại với `--decision <file>` và đường dẫn báo cáo mới để ràng buộc quyết định vào đúng bằng chứng. Đây là kiểm danh tính đã khai báo trong hồ sơ, cần quy trình quản lý người duyệt của đơn vị sử dụng.

Exit 0 khi có quyết định APPROVED khớp bằng chứng và mọi cổng đạt. Exit 1 khi còn thiếu điều kiện hoặc bị từ chối. Exit 2 khi sai hợp đồng. Protocol DRAFT giữ `NOT_EVALUATED` trước khi mở holdout. Báo cáo được lưu ngoài batch đã công bố. Các mục chưa có GT độc lập, người duyệt hoặc phép đo vận hành vẫn cần hoàn thiện để đóng BK-08.

Theo đặc tả 09, phát hành v7.0 còn bắt buộc `keywords` trong scope và gate occurrence không thiếu/thừa, độc lập với ngưỡng recall/CI/Holm. Gate dùng count nguồn đã tính lại cho đủ đơn vị keyword trong mẫu khóa; vùng không có keyword vẫn được kiểm lỗi thừa. Thiếu evidence không thành lỗi 0. Preflight phép đo thành phần vẫn cho phép scope hẹp hơn. [Quy tắc và trạng thái](09_DAC_TA_BAO_TOAN_DAU_9999.md#đối-chiếu-từng-lần-xuất-hiện-keyword).

## Chấm mã và đơn vị theo từng lần xuất hiện

`financial_token_accuracy` phục vụ ca `TC_SCI_TXT_05`. Chuẩn bị JSON có `schema_version` bằng `aligned-financial-token-input-v1`, `expected_ids` là các ID occurrence đã khóa, `references` và `predictions` là map theo cùng ID. Mỗi ID cần truy được PDF hash, trang, vùng hoặc ô và đoạn token. Một dòng có hai token giống nhau cần hai ID. Người gán nhãn đọc ảnh theo quy trình A/B và phân xử. Bản chấm lấy prediction đã căn nguồn từ artifact được ghim hash.

```powershell
.\.venv\Scripts\python.exe -B -m benchmark.scientific_evaluation.financial_token_accuracy aligned-token-input.json
```

Bộ chấm chuẩn hóa NFC và so phân biệt hoa thường. Kết quả tách khớp, chỉ lệch hoa thường, sai ký tự và thiếu đầu ra. Token đã có nhãn nhưng thiếu đầu ra vẫn nằm trong mẫu số. Thiếu nhãn hoặc có ID ngoài phạm vi làm `accuracy` giữ null. Báo cáo ghi hash file đầu vào. `EVALUATED` chỉ báo tính được điểm trên tập đã khai báo. Nghiệm thu ngưỡng và coverage cần protocol cùng bộ nhãn đã duyệt. [Kiểm chứng ca TXT_05](../scratch/dev_sessions/20261104-financial-token-fidelity/session.md).

## Chấm phân cấp dòng bảng

Với `TC_SCI_TAB_04`, ghim PDF hash, trang, ID bảng, ô nhãn và mã dòng trước khi căn prediction với nhãn A/B đã phân xử. Cả hai bản phải quy về cùng ID dòng. Trong JSON `aligned-table-row-hierarchy-input-v1`, `expected_ids` khai báo các dòng đã khóa, `references` và `predictions` ánh xạ ID sang `depth` và `parent_id`. Dòng gốc có độ sâu 0 và cha null. ID cha được khai báo trong cùng phạm vi. Căn độ sâu theo gốc của cùng mảnh bảng đã chọn và ghi các dòng ngoài phạm vi riêng.

```powershell
.\.venv\Scripts\python.exe -B -m benchmark.scientific_evaluation.table_hierarchy_metric aligned-hierarchy-input.json
```

Bộ chấm báo riêng độ sâu, cha trực tiếp và tỷ lệ cả hai cùng đúng. Dòng có nhãn mà prediction vắng vẫn ở mẫu số. Nhãn thiếu hoặc ID ngoài phạm vi giữ điểm null. Ngưỡng 90% trong test case cần được kiểm trên tập độc lập theo protocol khóa. [Bằng chứng phát triển](../scratch/dev_sessions/20261104-table-row-hierarchy/session.md).

## Chấm độ bền trước biến dạng ảnh

`degradation_metric` chấm các bản chữ đã căn cùng nguồn ở control, góc nghiêng, tương phản, nhiễu muối tiêu và vết ố. Bộ chấm giữ mẫu số đã khóa, tính S/D/I/H, CER theo mức, hiệu số CER so control, độ dốc hai điểm theo góc và insertion rate. Hash file chữ được kiểm trước/sau chấm. Thiếu GT giữ null; thiếu output tính deletion. `EVALUATED` chưa cấp nghiệm thu chất lượng.

[Hợp đồng input, lệnh và giới hạn](../benchmark/scientific_evaluation/DEGRADATION_V7.md) quy định ảnh/recipe, transcript A/B, phép chiếu và identity cần kèm. Công cụ này không gọi OCR, không tự cấp GT và chưa chứng minh ba ca `TC_SCI_DEG_01/02/03` đạt trên ảnh thật. Trace kỹ thuật giữ 61/65 cho đến khi có bằng chứng đúng phạm vi.

## Thu phép đo vận hành

```powershell
.\.venv\Scripts\python.exe -B -m benchmark.scientific_evaluation.measure_operations `
  --input inputs --output output/operation_new `
  --evidence scratch/operation_new --mode warm
```

Collector chụp danh sách PDF, fingerprint mã và SHA-256 mã collector trước khi gọi CLI canonical. Giám sát cây tiến trình, lấy mẫu tổng RSS của các tiến trình con đang sống và VRAM toàn GPU, ghi telemetry JSONL và thời gian quan sát từng commit. Không cộng RSS theo danh sách PID lịch sử vì PID có thể được tái sử dụng. Thời gian mỗi PDF đầu tiên có preflight, các PDF sau tính từ commit trước. Chu kỳ lấy mẫu mặc định hai giây. `--mode cache` dùng resume với output mới. Khi đã có đơn giá tổng chi phí tính theo giây do người phụ trách cung cấp, thêm `--cost-per-second` và `--currency`. Thu lần lượt từng lượt để giữ điều kiện đo, đọc trace và audit trước khi đề xuất hoặc khóa SLO.

Để đối chiếu lỗi paging file và lỗi lưu file, `input.json` ghi snapshot tài nguyên máy trước lệnh, từng dòng `telemetry.jsonl` có `host_resources` và `failure.json` giữ snapshot sau lỗi. Dung lượng trống và dung lượng toàn phần được lấy trên filesystem của output, evidence và thư mục tạm của Python. Khi đường dẫn output chưa có, phép đo dùng thư mục cha tồn tại và ghi rõ thư mục được đọc. Trên Windows, collector ghi committed bytes, giới hạn commit hiện tại và hiệu số từ `GetPerformanceInfo`. Mẫu thiếu giữ null và ghi lỗi truy vấn nếu có. Giới hạn commit có thể đổi khi pagefile thay đổi. Đây là dữ liệu chẩn đoán toàn máy, tách khỏi RSS cây tiến trình, VRAM và điều kiện SLO. [Hợp đồng API Windows](https://learn.microsoft.com/en-us/windows/win32/api/psapi/ns-psapi-performance_information).

Collector dùng yêu cầu `SetThreadExecutionState` trong thời gian chạy trên Windows, rồi khôi phục trạng thái thread khi kết thúc. Khoảng trống giữa các mẫu hoặc từ mẫu cuối tới lúc hoàn tất vượt `--max-sample-gap` (mặc định 30 giây) tạo `INVALID_FOR_SLO` trong failure.json, kèm các thời gian đã quan sát. Trường hợp thiếu quyền đọc RSS của worker giữ peak_rss_mib null và lưu phần đỉnh đã đọc được riêng. Retry đếm lượt thử tài liệu bổ sung. Timeout/OOM lấy từ các response lỗi đã ghi. Người kiểm giữ log gốc để đối chiếu các số đếm này. [Tài liệu Windows về trạng thái thực thi](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-setthreadexecutionstate).

Client Docling giải phóng PDF yêu cầu của từng trang sau phản hồi hợp lệ, hoặc sau khi đóng và xác minh worker thoát khi lỗi. Nếu không xác minh được thoát thì giữ tệp; worker log vẫn được giữ. Cache cũ không tự bị xóa. Lỗi ghi đĩa trong phép đo cần giữ log gốc và điều tra dung lượng trước khi dùng thời gian để đề xuất SLO.
