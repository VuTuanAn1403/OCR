# Thiết kế chi tiết dự án OCR pdf V5 phục vụ nghiên cứu khoa học

**Phiên bản thiết kế:** 1.0 — **Ngày:** 11/10/2026.  
**Tính chất:** thiết kế mục tiêu để triển khai và kiểm chứng; không phải mô tả tất cả chức năng đã được nghiệm thu. Những interface, kiểu dữ liệu và file mới dưới đây là đề xuất, trừ nơi ghi rõ thành phần đang có.

## 18. Mục tiêu thiết kế và các quyết định kiến trúc

Thiết kế cụ thể hóa 38 yêu cầu FR/NF/SCI của phần đặc tả thành ranh giới module, dữ liệu trao đổi, thuật toán và hồ sơ kiểm chứng. Dùng kiến trúc domain/application/infrastructure hiện có, tách orchestration khỏi OCR adapter và tách evaluator khỏi pipeline tạo prediction. Không đưa GT vào routing, retry hoặc postprocessing của run dùng để công bố accuracy.

| Quyết định | Thiết kế chọn | Lý do và điều kiện kiểm chứng |
|---|---|---|
| D01 | IR có provenance là trung tâm; Markdown là đầu ra chính | Cho phép truy ngược lỗi; evaluator vẫn phải đọc Markdown cuối, không chỉ chấm IR |
| D02 | Định tuyến theo vùng với native-first | Hạn chế OCR không cần thiết; chứng minh bằng ablation routing trên corpus đa loại |
| D03 | Model/provider và effective config được khóa theo run | Nhãn CPU hoặc tên model phải khớp thực thi, không dựa riêng vào YAML |
| D04 | Deadline do supervisor kiểm soát ở biên process | Thread timeout không bảo đảm dừng inference; kiểm chứng bằng worker treo |
| D05 | Cache nội dung khóa toàn bộ đầu vào và phiên bản | Không dùng lại artifact khi code/config/model thay đổi |
| D06 | Export staging và xác thực trước công bố | Tránh đọc đầu ra đang viết dở hoặc ghi đè run cũ |
| D07 | Evaluator riêng và reference adapters có version | GT không ảnh hưởng extraction; có thể đánh giá lại output bằng cùng evaluator |
| D08 | Accuracy, quality, processing status và review status là các trường độc lập | Tránh cờ hoàn tất hoặc confidence cao trở thành kết luận accuracy |
| D09 | Lưu counts và metric applicability trước aggregate | Không tạo perfect score khi thiếu GT; micro/macro có thể tái tính |
| D10 | Actual run registry cho baseline và ablation | Mỗi hàng báo cáo phải có run thật, không sinh bằng hệ số |
| D11 | Report builder chỉ đọc artifacts bất biến | Tạo lại JSON/CSV/Word/LaTeX từ cùng data, không sửa prediction để khớp GT |
| D12 | Schema và adapter có migration rõ ràng | Hỗ trợ dữ liệu cũ mà không giả nó có provenance hoặc null policy mới |

Các quyết định này không khẳng định luôn tối ưu. Nếu pilot cho thấy một lựa chọn không đạt mục tiêu CPU hoặc làm tăng lỗi, thay thiết kế phải có version, evidence và chạy lại các comparison bị ảnh hưởng.

## 19. Phân rã thành phần và giao diện

### 19.1. Các thành phần xử lý

| Thành phần mục tiêu | Input và output | Liên hệ mã hiện có |
|---|---|---|
| InputResolver | Request → PDF đã xác minh, hash đầy đủ và tập trang hợp lệ | `convert_document.py`, `run_ocr.py`; cần thống nhất resolver |
| RunCoordinator | Request + RunContext → ExtractionResult và run ledger | `ConvertDocumentUseCase`; cần bổ sung lifecycle và timing biên cuối |
| PageInspector | PDF page → PageInspection có text/ảnh/geometry/features | `pdf_inspector.py`, `native_quality.py` |
| RoutingPlanner | Inspection + config → RegionProcessingPlan có lý do | `route_page.py`, routing policy và content analyzer |
| NativeAdapter | Page/region → ContentCandidates native với bbox | `native_text_extractor.py` |
| RenderAdapter | Page/region/DPI → RenderedRegion và transform | `pdf_renderer.py`, `region_cropper.py` |
| OCRAdapter | RenderedRegion + engine context → OCRCandidates | RapidOCR, VietOCR, primary/fallback engines |
| ContentAssembler | Candidates + regions → PageIR, bảng và thứ tự | Layout, reading order và table/domain components |
| RetryPlanner | PageIR + remaining budget → các retry tasks | `reocr_region.py`, candidate scorer |
| ArtifactExporter | DocumentIR → Markdown/JSON/assets và alignment | Export use case và Markdown/JSON exporters |
| ArtifactValidator | Staging artifacts → integrity errors/review items | `artifact_validator.py`; không đo semantic accuracy |
| ScientificEvaluator | Frozen final output + independent GT → metric records | `benchmark/scientific_evaluation/`, scientific runner |

Tên thành phần trong bảng là ranh giới trách nhiệm, không yêu cầu tạo một file cho mọi tên. Có thể refactor module hiện có, miễn interface và evidence rõ ràng. Không tạo một class lớn mới chứa cả routing, OCR, export và evaluation.

### 19.2. Giao diện mục tiêu

Chữ ký dưới đây là hợp đồng thiết kế; CLI/API hiện tại cần adapter tương thích, chưa được xem là đã tồn tại:

```text
convert(request: ConversionRequest, context: RunContext) -> ExtractionResult
inspect(page: SourcePage, context: PageContext) -> PageInspection
plan(inspection: PageInspection, config: EffectiveConfig) -> PagePlan
recognize(image: RenderedRegion, deadline: Deadline) -> OCRResult
assemble(candidates: CandidateSet, plan: PagePlan) -> PageIR
export(document: DocumentIR, staging: ArtifactRoot) -> ExportResult
validate(export: ExportResult) -> ValidationResult
evaluate(output: FrozenOutput, gt: FrozenGT, policy: EvaluationPolicy)
    -> EvaluationResult
```

`ConversionRequest` chứa PDF path, profile, selected pages, output root, cache mode và options đã kiểm tra. `RunContext` chứa run ID, source snapshot, config/model hashes, device/providers, logger, artifact store và clock. `PageContext` bổ sung deadline tuyệt đối và transform; không chứa GT.

`ExtractionResult` trả processing status, output paths/hashes, page ledger, review count và errors. `EvaluationResult` trả evaluation validity, metric records, coverage, failure reasons và claim eligibility. Ngoại lệ tầng library được chuyển thành error record có stage; không nuốt thành mảng rỗng hoặc object mặc định.

## 20. Thiết kế dữ liệu và định danh

### 20.1. Các quan hệ dữ liệu

Một run chứa nhiều document executions. Một source document định danh bằng SHA256 đầy đủ; từng execution ghi profile/config/cache regime. Document có nhiều trang vật lý; page có regions, content blocks, tables và assets. Table chứa cells, mỗi cell có thể nối nhiều source regions nếu là bảng tiếp nối. Review item tham chiếu entity ID, không dựa vào vị trí dòng của file report.

`SourceDocumentID` nên lấy từ full PDF SHA256, còn tên file/stem là display name. `DocumentExecutionID` kết hợp run ID, source ID, page selection và effective config. ID block/cell/region phải ổn định trong cùng schema/snapshot, có parent ID; không dùng text làm ID vì có thể trùng. Hai file khác nội dung nhưng cùng stem phải có output riêng.

| Kiểu dữ liệu mục tiêu | Trường cốt lõi | Invariant |
|---|---|---|
| RunRecord | run_id, snapshot/config/model/data hashes, device, regime, timestamps, executions | Không placeholder hash; source snapshot ổn định |
| PageInspection | page_num, page size, rotation, native features, image regions, warnings | Trang 1-based và tọa độ có đơn vị |
| PagePlan | source classification, region tasks, route reasons, budgets | Source classification độc lập route prediction |
| ContentCandidate | entity/source IDs, raw text, bbox, confidence, engine, rule history | Không sửa raw text tại chỗ; confidence có thể null |
| PageIR | blocks/tables/assets, physical page, extraction status, review reasons | Mọi vùng cần xử lý có disposition |
| ExportAlignment | Markdown hash, page/entity IDs, UTF-8 spans, parser version | Spans thuộc chính file cuối được hash |
| MetricRecord | definition/track/scope/status/value/counts/denominator/coverage | Không GT hoặc không mẫu số hợp lệ không sinh tỷ lệ giả |
| ClaimRecord | claim ID/text/unit, run IDs, raw paths/hashes, CI, reviewer | Số thực nghiệm phải truy đến actual run |

Schema mục tiêu dùng `schema_version` có version semantic. Bổ sung field optional có default null là thay đổi tương thích nếu không đổi nghĩa; đổi hệ tọa độ, denominator hoặc source enum phải tăng major contract version hoặc dùng adapter explicit. Kiểu `Any` trong domain accuracy hiện tại cần thay bằng model có status và optional value, không chỉ thêm annotation mà giữ default perfect score.

### 20.2. Transform tọa độ

Lưu phép biến đổi affine dưới dạng ma trận 3×3 cho từng bước: PDF page → rotation-normalized page → crop → render pixels → model resized image. Pipeline phải lưu transform composition và inverse; bbox prediction đổi về PDF points bằng inverse trước khi merge/match.

Trong bước không xoay, pixel scale bằng DPI/72; crop origin dịch tọa độ trước scale. Khi có rotation, phải biến đổi đủ bốn góc bbox rồi lấy enclosing rectangle. Không chỉ hoán đổi width/height hoặc nhân scale cho tọa độ đã xoay. Test dùng landmarks gần bốn góc và crop lệch tâm để phát hiện lỗi mà bbox ở giữa trang có thể che.

### 20.3. Chính sách text và provenance

Lưu `raw_text`, `normalized_text`, `selected_text` và transformations khi có thay đổi. NFC là canonical policy; không bỏ dấu, case, số, punctuation trong strict text track. Mỗi nguồn OCR lưu engine/model hash, render parameters và candidate ID; bản human-edited dùng provenance khác.

Các enum source hiện có khác nhau giữa EvidenceBlock và Region phải đi qua adapter. Không gán chuỗi nguồn ngoài enum rồi sửa validator để chấp nhận tùy ý. Confidence native có thể không có; heuristic quality phải ghi score type, không quy thành probability hoặc accuracy.

## 21. Luồng xử lý và thuật toán theo trang

### 21.1. Luồng điều phối tài liệu

```text
validate_request_and_resolve_source()
freeze_effective_config_and_source_snapshot()
start_clock_for_declared_timing_regime()
open_pdf_and_prepare_required_workers()
for each requested physical page in stable order:
    create_absolute_page_deadline()
    try valid cache entry, otherwise inspect and plan
    extract native candidates for reliable regions
    render and OCR only planned regions
    assemble layout, tables and reading order
    retry eligible regions within remaining budget
    persist PageIR, errors and review dispositions
export_document_to_staging()
validate_markdown_json_assets_alignment_and_queue()
commit_complete_or_explicit_partial_artifacts()
stop_extraction_clock_and_finalize_nonrecursive_run_ledger()
verify_source_snapshot_has_not_changed()
evaluate_frozen_output_separately_if_GT_is_available()
```

`freeze` lưu cấu hình đã giải quyết, không chỉ tên profile. Clock boundary và overhead thu thập provenance phải được ghi rõ; thời gian ghi run ledger cuối có timing/self-hash không được tạo vòng đệ quy. Không loại export/validation khỏi extraction để đạt trần CPU.

### 21.2. Routing theo vùng

Inspect native layer, lỗi Unicode/font, image coverage, region geometry và khả năng có chữ. Các ngưỡng native quality dùng profile hiện có như giá trị khởi đầu, cần calibrate trên dev; không dùng GT test để chọn threshold.

| Trường hợp | Kế hoạch xử lý | Điều kiện theo dõi |
|---|---|---|
| Native chữ hợp lệ | Dùng native; phân tích bảng/vector/ảnh riêng | Native lỗi font hoặc thiếu vùng phải vào kiểm tra |
| Scan không có lớp chữ dùng được | Render vùng/trang, OCR và layout | Không coi OCR rỗng như trang trắng |
| Mixed | Native vùng chữ đúng và OCR vùng ảnh có chữ | Deduplicate bằng geometry + source correspondence; giữ ảnh nguồn cần thiết |
| Lớp OCR cũ hỏng | OCR lại vùng lỗi hoặc toàn trang theo plan | Lưu lý do bỏ native layer và chi phí |
| Ảnh trang trí không có text | Bảo toàn ảnh, có thể bỏ OCR theo rule | Rule phải được đo trên positive/negative GT, tránh mất caption/chữ ngắn |
| Không xác định | Preserved asset + unresolved/review hoặc fallback theo config | Không tự hoàn tất semantic extraction |

Deduplication không dựa vào prefix text đơn lẻ. Cần overlap/containment đúng tọa độ, source relation và text compatibility; nếu hai nguồn bất đồng số hoặc dấu, giữ candidates và review. Bản đã bị loại vẫn có disposition trong IR.

### 21.3. Xử lý orientation và two up

Ưu tiên metadata rotation và evidence hình học; chỉ thử thêm hướng khi có dấu hiệu orientation không chắc. Mỗi lần thử ghi angle, score type, số OCR calls và thời gian. Không thử bốn hướng cho mọi vùng bất kể cần thiết.

Two-up tạo các logical subpages gắn với cùng physical page. Reading order đi qua subpage order rồi block order; denominator tốc độ và selected pages vẫn đếm trang PDF vật lý. Landmark transform tests xác nhận text/bbox của hai nửa không bị đảo hoặc nằm ngoài nguồn.

## 22. Thiết kế layout bảng và thứ tự đọc

### 22.1. Layout và reading order

Adapter layout trả labels, bbox, confidence type và method (`heuristic` hoặc model inference). Registry ánh xạ nhãn model → ontology dự án → categories COCO, có version. Không gọi mọi nhãn nội bộ là category của DocLayNet hoặc OmniDocBench khi schema khác nhau.

Order assembler xây đồ thị precedence theo cột, tiêu đề spanning, vùng bảng/ảnh và caption. Sắp thứ tự topological theo constraint; tie-break bằng page/subpage/geometry/entity ID được khóa. Nếu có cycle hoặc nhiều thứ tự chưa quyết định, ghi lý do và review; không tùy tiện sort theo y toàn trang rồi coi đã xử lý đa cột.

GT có thể là partial order. Evaluator ghép blocks một-một bằng mapping nguồn hoặc geometry/content policy đã khóa trước khi đo order. Không chọn phép ghép nhằm tối đa order score và không ghép hai predicted blocks vào một GT block.

### 22.2. Bảng và cells

Table assembler ưu tiên vector/text geometry với native; với scan cần detection và structure inference/heuristic được ghi phương pháp thực. Bước tạo grid trả rows, columns, cells, rowspan/colspan và source mapping. Cell rỗng vẫn là cell, không làm lệch cột khi parse.

Markdown GFM chỉ dùng cho grid biểu diễn được không mất spans. Bảng merged cells dùng HTML table đã escape nội dung; giữ header/caption và thứ tự xuất. Nếu không tái tạo được structure, xuất ảnh bảng cùng trạng thái preservation, không đo TEDS như bảng trích đúng.

Gộp bảng nhiều trang cần evidence về vị trí tiếp nối, cấu trúc cột, headers và caption; lưu group ID cùng individual source table IDs. Bảng giống nhau nhưng không liên tục không được tự gộp. Evaluator phải biết GT correspondence ở scope bảng merged hay từng trang; không so hai scope khác nhau.

### 22.3. Số và bất đồng ứng viên

Numeric parser trả raw token, vị trí entity/cell, sign, unit và locale policy; không ép mọi token thành float. `(100)` giữ dấu âm theo policy đã khóa, `00123` giữ leading zeros, dấu phân cách/thập phân và `%` không bị xóa.

Nếu primary/fallback khác giá trị số, không chọn tự động chỉ vì confidence cao hơn. Ưu tiên evidence nguồn/candidate selection policy trên dev; unresolved conflict bắt buộc vào queue. NumericExact so khớp location và raw format/value policy tương ứng GT; bag-of-numbers recall là diagnostic riêng.

## 23. Thiết kế retry deadline và review queue

### 23.1. Retry có giới hạn

Tập eligible regions được xác định trước khi chọn retry: low confidence, Unicode corruption, native/OCR disagreement, numeric conflict hoặc structure unresolved. Sắp ưu tiên bằng severity, likelihood of recoverable error, estimated cost và ID; công bố scoring rule, không gọi nó là accuracy.

Đề xuất ngân sách strict: `region_budget = min(max_regions, floor(ratio * eligible_base_regions))`, đồng thời chặn theo remaining deadline. `eligible_base_regions` là số vùng nội dung đủ điều kiện của trang, phải khóa định nghĩa. Với trang ít vùng, budget có thể bằng 0: giữ output/evidence và review, không tự nâng lên 1 để vượt ratio. Nếu cần minimum retry, đổi policy/config explicit và đánh giá lại.

Retry tạo candidate mới; lưu region crop/DPI/model/angle/time và lý do accept/reject. Không sửa raw prediction cũ. Rule chọn bản mới phải được kiểm chứng trên dev và trong ablation. Khi hết ngân sách, báo budget exhausted, không coi vùng đã giải quyết.

### 23.2. Deadline process và worker lifecycle

Parent coordinator dùng deadline tuyệt đối từ monotonic clock cho toàn trang. Worker nhận thời gian còn lại cho inspect/render/OCR/assemble/retry; parent supervise timeout. Khi worker treo, parent terminate worker thuộc run của mình, ghi TIMEOUT và khởi tạo lại worker theo policy. Không dừng tiến trình ứng dụng của người dùng hoặc worker run khác.

Windows dùng process start mode được hỗ trợ và entry point guard. Worker có thể giữ model warm cho các trang trong cùng run; model init/restart costs vẫn ghi trong regime. IPC gửi job metadata/paths hoặc shared buffer theo giới hạn bộ nhớ; không sao chép toàn bộ document images cho từng task. Concurrency ban đầu nhỏ và explicit; số workers × engine threads không được tự vượt tài nguyên chuẩn.

Dừng future/thread chờ không đồng nghĩa inference đã dừng. Test S07 phải đo parent completion time, xác nhận worker không tiếp tục ghi artifacts sau timeout và batch xử lý tệp tiếp theo.

### 23.3. Queue reconciliation

Queue builder duyệt PageIR và artifact errors, tạo key theo document/page/entity/reason. Gộp items trùng cùng lỗi nhưng không gộp mất reason độc lập. Mỗi unresolved, failed extraction, numeric conflict, missing asset và review flag bắt buộc có item hoặc waiver explicit có evidence.

Validator đối chiếu predicate-to-queue theo IDs; chỉ so tổng số item là không đủ. Item có source crop/link, text candidates, severity và trạng thái `OPEN`, `IN_REVIEW`, `RESOLVED`, `WAIVED`; resolution ghi người thật, timestamp và bản thay đổi. Agent không tự đánh dấu human-reviewed.

## 24. Thiết kế cache lưu trữ và xuất Markdown

### 24.1. Khóa cache và invalidation

Cache key SHA256 được tính trên canonical serialized payload gồm full PDF SHA256, physical page, effective config hash, code snapshot hash, model weights hashes, runtime compatibility fingerprint, preprocessing/layout versions và IR schema version. `run_id` không nằm trong content key để cho phép reuse giữa run, nhưng mỗi cache hit có provenance run tạo và run dùng lại.

Config canonicalization phải ổn định thứ tự keys/Unicode/float representation; thuật toán có version. Cache đọc phải validate schema và artifact hashes. Sai key/schema/hash → miss có reason; không dùng silent recovery để tạo score hoàn hảo. Cache partial chỉ được reuse phần có validity rõ ràng; phần chưa xử lý vẫn tạo tasks.

Đầu ra cache và benchmark histories tách thư mục. Không dùng resume cache time như extraction mới. Khi schema legacy không có code/model hash, báo `LEGACY_CACHE_UNVERIFIED` và không dùng cho final research comparison.

### 24.2. Artifact transaction

Mỗi run có namespace riêng; mỗi execution viết staging trên cùng filesystem với đích để có thể rename khi hoàn tất. Luồng: write → flush/close → validate paths/hashes/schema → write completion marker/ledger → publish namespace. Khi crash, staging không được đọc như final output; recovery scan chỉ nhận marker hợp lệ.

Không overwrite run cũ; lỗi trùng run ID phải báo. Paths assets là relative trong output root, kiểm tra containment trước ghi. Khi export ảnh thất bại ở mọi DPI, giữ error và review item; không phát sinh link đến file không tồn tại.

### 24.3. Markdown và alignment

Exporter tạo buffer UTF-8 cuối, ghi boundary metadata cho từng page/entity tại thời điểm nối nội dung. Byte spans lấy trên buffer thực tế sau mọi header/footer/table rendering, trước hoặc cùng lần ghi `result.md`. Sau write, tính hash từ bytes trên disk và xác nhận mapping vẫn đúng. Mọi thao tác sửa final file invalidates alignment.

Alignment có thể có nhiều spans cho một table/cell nếu output interleave, nhưng mỗi span cần semantic type. Metadata exporter được đánh dấu riêng để evaluator bỏ đúng metadata. Text giống marker trong PDF phải escape hoặc nằm ngoài channel metadata; không suy page chỉ bằng regex đề mục.

Per-page Markdown là artifact chẩn đoán có hash riêng. Nếu final mapping hỏng, evaluator báo ALIGNMENT_FAILED, không chuyển sang page files để giữ điểm. Images preserved có source mapping nhưng không trở thành text prediction cho CER.

## 25. Thiết kế bộ đánh giá khoa học

### 25.1. Quy trình evaluator

1. Nạp frozen run/output manifests; kiểm tra PDF/output/schema/source snapshot hashes và scope.
2. Nạp GT độc lập; xác nhận page/modality status, annotation version, rights và coverage.
3. Parse Markdown cuối thành semantic AST bằng parser/version đã khóa; lấy text/table content theo track.
4. Match prediction với GT bằng correspondence hoặc policy đã khóa; lưu missing/spurious/mapping failures.
5. Tính counts và per-scope metrics bằng reference adapters; không truncate prediction hoặc bỏ trang lỗi.
6. Aggregate micro/macro/per-stratum, uncertainty và paired deltas khi comparable.
7. Xuất metric records/status, raw counts và claim eligibility; quality/confidence không thay accuracy.

Adapter GT phải phân biệt `not_annotated`, `annotated_empty` và `annotated_nonempty`. Chưa gán nhãn không được xem như không có thực thể; annotated-empty prediction có chữ/bảng phải ghi insertions/spurious. Không có mẫu số tỷ lệ hợp lệ → null, vẫn giữ error counts phù hợp.

### 25.2. Định nghĩa và implementation adapters

| Adapter | Phép tính mục tiêu | Kiểm chứng |
|---|---|---|
| TextEditAdapter | Căn chỉnh S/D/I/H; CER trên ký tự NFC; WER_ws trên whitespace tokens | JiWER parity cùng transformations; insertion vượt 100%; empty-GT policy riêng |
| VietnameseDiacriticAdapter | DER_VN_v1 theo alignment rồi shape/tone/stroke slots | Golden cases cho sắc/huyền, mũ/móc/trăng và đ; custom definition/version |
| TableAdapter | TEDS/TEDS-S official/adapted HTML track, TEDS_GT và detection P/R/F1 | Pin PubTabNet source; parser normalization; thiếu/dư tables |
| LayoutAdapter | pycocotools COCOeval với image/category mapping và xywh | Official reference outputs; scale/rotation, crowd/area/maxDets và absent classes |
| OrderAdapter | 1-1 correspondence, coverage và precedence trên GT pairs | Duplicate/missing blocks; partial order; Spearman N/A khi không đủ matched blocks |
| NumericAdapter | Exact TP/FP/FN theo raw format/location policy | Sai vị trí và token dư bị phạt; sign/unit/locale/leading-zero cases |
| AggregationAdapter | Pooled counts, macro document, strata và cluster bootstrap | Recompute từ raw records; paired resampling seed và insufficient-document status |

CER và WER dùng reference denominator, không normalized edit distance có mẫu số khác. DER không tự đổi thành `1-DER` rồi gọi accuracy khi insertion có thể làm error rate vượt 1. TEDS matched cao không chứng minh không có table dư; order matched cao không chứng minh content coverage đủ.

Numeric exact nếu thay token ở cùng location tạo một FP và một FN; token location/value khớp tạo TP. Nếu không có GT numeric entities đã xác nhận, tỷ lệ recall không có mẫu số: value null và spurious count vẫn có. Mẫu số của mỗi metric phải xuất cùng record.

### 25.3. Parity và provenance

Registry lưu exact package version hoặc upstream commit/source hash, license, adapter hash, normalization policy và commands tạo golden outputs. `>=version` hoặc nhãn VERIFIED không đủ làm pin/parity evidence. So trên cùng inputs, capture reference and project outputs cùng tolerance đã khóa. Không lấy kết quả từ project implementation làm independent golden result.

Fixtures toán học và synthetic cases nằm ngoài empirical corpus. Reference failures/unsupported classes phải báo, không thay official evaluator bằng approximation mà vẫn giữ tên official score. Mọi adaptation cần track name riêng và phạm vi tương thích.

## 26. Thiết kế thực nghiệm và báo cáo có thể tái lập

Run registry khóa system/config/code/model hashes cho V4.3, V5 và mỗi ablation. Tạo matrix từ experimental plan, thực thi từng row, lưu completion/failure và raw outputs. Collector chỉ nhận rows có actual run ID và valid artifacts; biến thể không chạy ghi NOT_RUN.

Comparability service đối chiếu corpus/split/pages/GT/policy/evaluator/device/regime và output scope. Khác điều kiện quan trọng → INCOMPARABLE với lý do; không tính improvement/regression như một experiment ghép cặp. Khi evaluator thay đổi, re-evaluate outputs cả hai bên.

Bootstrap resample document clusters; cùng draw dùng cho paired system delta. Tính lại estimator từ counts của các document lấy mẫu; không bootstrap trực tiếp vài giá trị mean toàn corpus. Timing repetitions được lưu nested theo document/run; không xem repeated runs là tài liệu độc lập. CI thiếu independence phải ghi insufficient scope.

Report builder đọc metrics và claims qua immutable IDs/hashes; formatting không thay số raw. Null hiển thị N/A kèm trạng thái, phần trăm ghi rõ chuyển từ ratio ×100, timing so threshold trước rounding. LaTeX/Word tables của kết quả chỉ tạo từ actual runs; design/report templates không chứa empirical numbers tự điền.

Claim registry bao gồm claim text, unit/scope, raw artifact paths/hashes, run IDs, code/data/GT/model/config/evaluator identity, CI và giới hạn. Lint bản thảo đối chiếu mọi số kết quả với registry; claim không có raw evidence ghi UNVERIFIED/TARGET/HYPOTHESIS, không MEASURED.

## 27. Thiết kế hiệu năng CPU và giới hạn tài nguyên

Các trần 0,15 / 1,8 / 2,5 giây/trang được giữ nguyên. Chưa có benchmark hợp lệ thì không ghi đã đạt. Primary profile, timing regime và CPU chuẩn phải freeze trước final run; warm model, cold process và artifact cache hit là các kết quả riêng.

| Nguồn chi phí | Thiết kế giảm chi phí | Bằng chứng cần có |
|---|---|---|
| Native tốt bị OCR lại | Region routing và native-first; giữ kiểm tra Unicode | Routing ablation cùng accuracy scope |
| Render toàn trang nhiều lần | Render/crop theo plan, reuse buffer cùng DPI/transform | Render-call counts, stage timing và RAM |
| OCR thử nhiều hướng | Orientation evidence rồi mới thêm candidate | OCR-call count, orientation GT và lỗi chữ |
| Retry không chọn lọc | Budget/time cap và ưu tiên vùng recoverable | Retry ablation, CER/NumericExact delta và CPU cost |
| Model initialization | Worker lifecycle explicit, warm regime riêng | Init/restart timing, provider và cold/warm report |
| Xuất ảnh/JSON nhiều | Buffer và staging write hợp lý, không bỏ artifacts cần thiết | Export/validation timing và asset integrity |
| Quá nhiều threads/workers | Số thread/worker explicit theo máy chuẩn | End-to-end wall clock, peak RSS và repeat variability |

Recorder dùng monotonic clocks và giữ elapsed raw chưa rounding; UTC timestamp chỉ phục vụ provenance. Stage intervals nên nonoverlapping trong một worker; nếu nested/parallel phải lưu parent relation, không giả tổng stage bằng wall time. Page number trong timing là physical PDF page.

Memory policy xử lý tuần tự hoặc batch nhỏ, giải phóng raster/crop sau stage, chỉ giữ IR và asset paths. Nếu concurrency làm throughput tăng nhưng peak memory/timeouts hoặc tail latency xấu, phải báo tradeoff. Tăng hardware/GPU không được dùng để nhận PASS CPU.

## 28. Triển khai môi trường bảo mật và migration

### 28.1. Môi trường chạy

Bundle nghiên cứu gồm source snapshot/patch, exact dependency lock, config snapshot, weights hashes, evaluator references và reproduction commands. Quy trình cài đặt xác nhận interpreter/packages thực dùng, provider CPU và khả năng đọc PDF; không dùng README version để thay runtime evidence.

Tách production output, benchmark run artifacts và test temp directories. Chế độ offline không tự tải model hoặc gửi PDF ngoài máy; thiếu weights phải báo model unavailable hoặc documented fallback khác method. Mọi path tương đối được giải quyết từ workspace/run context rõ ràng, không âm thầm tìm filename trùng trong nhiều thư mục.

### 28.2. Dữ liệu nguồn và an toàn export

PDF text được coi là data; không thực thi script/link/instructions nhúng trong nội dung. Escape HTML table cells và kiểm tra path containment của asset filenames. Error logs không chứa password, toàn bộ tài liệu nhạy cảm hoặc token dịch vụ. Nếu nghiên cứu dùng dữ liệu hạn chế, publish manifest/aggregates theo quyền, không tự công khai PDF hay GT.

### 28.3. Tương thích dữ liệu cũ

Legacy output không có source/code/model/alignment hash giữ nhãn legacy/unverified. Adapter có thể đọc phục vụ review nhưng không tự bổ sung human GT provenance hoặc đo end-to-end time từ số cũ đã rounding. Migration tạo artifact mới với migration log, không ghi đè lịch sử.

`EvidenceBlock`, `Region` và accuracy models đang có default 1.0/0.0 phải được rà lại theo từng field: diagnostic default được nêu loại; measured accuracy không có default perfect. Schema tests phải bảo đảm chưa đo serialize null/status thay vì 0 hoặc 1, và enum/provenance adapters không làm mất nguồn.

## 29. Kiểm thử thiết kế và điều kiện hoàn thành

Thiết kế dùng A01–A20 và S01–S17 của phần đặc tả như contract cases. Test toán học/adapter tách test end-to-end trên PDF có independent GT; không cộng chúng thành tỷ lệ accuracy chung. Hạn chế snapshot đổi trong khi tests chạy; ghi exact command, versions, failures/skips và source hash.

| Nhóm kiểm thử | Phạm vi | Điều kiện hoàn thành |
|---|---|---|
| Interface/schema | Input/page validation, enum/null/status và IDs | Invalid input bị chặn; serialization có semantics đúng |
| Coordinate/routing | Rotate/crop/two-up/mixed và native layer lỗi | Landmark round-trip, source pages và route evidence đúng |
| Content assembly | Duplicate text, multi-column order, tables/spans và numeric conflicts | Không mất/nhân đôi content; GT metrics và review đúng |
| Runtime fault injection | Hung worker, model failure, export lỗi và crash staging | Deadline thực, failure ledger và không publish complete giả |
| Cache/provenance | Config/model/code changes, bad hash và legacy outputs | Invalid cache không được dùng; run reproducible |
| Evaluator/reference | Empty/missing/partial GT, insertion, missing/spurious entities và official parity | Counts/status đúng; independent parity artifact tồn tại |
| Empirical experiment | Multi-type PDFs, baseline/ablation, CPU repeats và CI | Actual runs hợp lệ và claim scope đúng; thiếu evidence không PASS |

Hoàn thành thiết kế nghĩa là module contracts, invariants, workflow, status, schema/migration và test evidence plan đầy đủ để triển khai. Hoàn thành triển khai và nghiệm thu khoa học vẫn cần code, GT, actual runs và các gates G0–G6. Không dùng tài liệu thiết kế để tự đóng task benchmark.

## 30. Trình tự phát triển và các điểm cần quyết định

Triển khai thứ tự: contract/null/provenance → input/IDs/export/alignment → deadline/cache/review → evaluator parity → GT/split freeze → pilot → actual final comparison → claim/report audit. Duy trì compatibility adapter cho CLI hiện có; khi đổi default profile/output layout phải có release note và regression checks.

| Điểm quyết định | Giá trị hiện tại trong thiết kế | Thời điểm khóa |
|---|---|---|
| Accuracy thresholds và non-inferiority margins | Chưa xác định, null/NOT_SPECIFIED | Trước final acceptance hoặc final non-inferiority analysis |
| CPU chuẩn, profile và primary regime | Profile balanced là đề xuất; CPU-only, regime chưa khóa | Experiment plan freeze |
| Corpus size/split/GT scope | Pilot xác định sample-size rationale; không bịa số mẫu | Trước final test |
| Native quality/routing/retry policies | Profile thresholds là khởi đầu, policy có version | Sau dev/pilot, trước final |
| OCR/layout weights và references | Phải ghi bản/hash thực; không chỉ model alias hoặc version range | Trước tạo accepted run |
| Ontology và coordinate transforms | PDF points IR, explicit mapping; taxonomy version riêng | Trước annotation/evaluator freeze |

