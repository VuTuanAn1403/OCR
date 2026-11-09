# Chuẩn bị và kiểm GT V6

Trạng thái ngày 14/10/2026: chưa có GT do người gán nhãn hoặc splits công ty được chốt. Công cụ ở đây tạo inventory và draft; không biến prediction hay trang trống thành GT. Kế thừa nguyên tắc trạng thái ba mức của `benchmark/research_v1/annotation_guideline.md`; taxonomy V6 bên dưới thay phần taxonomy layout V5 cho các lần đánh giá V6 mới.

## 1. Metadata và splits

Chạy từ repository sau khi cài editable; cũng có thể dùng `.venv/Scripts/python.exe -m src.ocr.cli.collect` thay `ocrpdf-collect`.

```powershell
ocrpdf-collect sources --input inputs --output benchmark/ground_truth_tools/sources.csv
```

Inventory gồm document ID, đường dẫn tương đối, SHA256 đầy đủ, số trang, encryption/copy restriction và trạng thái đọc. Tên file không được dùng để tự xác nhận công ty/năm/ngành. Metadata chưa xác minh là `unknown`; inventory chưa phải dataset nghiệm thu.

Người phụ trách đối chiếu PDF/nguồn công bố rồi tạo JSON metadata, key là đường dẫn tương đối trong inventory. Ví dụ sau chỉ mô tả format, các giá trị phải được thay bằng dữ liệu đã kiểm:

```json
{
  "example.pdf": {
    "company_id": "verified_company_id",
    "company_name": "verified_legal_name",
    "exchange": "verified_exchange",
    "year": "2025",
    "industry": "verified_industry",
    "size": "verified_size",
    "dbi_object": "unknown",
    "language": "vi",
    "source_url": "verified_publication_url",
    "collected_at": "2026-10-14"
  }
}
```

Từ 15/10/2026 inventory là `sources-v2`, thêm `company_name`, `exchange`, `language` (tên công ty, sàn, ngôn ngữ của báo cáo theo C2.0); inventory v1 vẫn đọc được, cột thiếu là `unknown`. PDF trùng SHA-256 được giữ trong inventory với `status=DUPLICATE` và không vào draft; nhiều PDF khác hash cùng công ty/năm được liệt kê ở `revision_candidates` của `.catalog.json` để người phụ trách quyết định bản dùng. Công cụ chỉ kiểm kê file đã có; tải từ nguồn công bố (điều khoản, `robots.txt`, giới hạn tốc độ) chưa được triển khai.

`company_id` là ID ổn định của pháp nhân, được chuẩn hóa NFC/lowercase; aliases và nhiều năm của cùng công ty phải quy về cùng ID. Không chia công ty theo mỗi mã tài liệu. Chạy lại inventory với `--metadata metadata.verified.json`, lưu người xác minh và phiên bản metadata trong hồ sơ GT.

Tạo `assignments.json` gồm đúng ba danh sách company ID: `train`, `dev`, `test`, mỗi danh sách không rỗng. Chốt danh sách trước tiền gán nhãn/sinh dữ liệu; không tự phân chia theo tỷ lệ khi công ty chưa được xác minh.

```powershell
ocrpdf-collect splits --sources benchmark/ground_truth_tools/sources.csv --assignments assignments.json --output benchmark/ground_truth_tools/splits.locked.json
ocrpdf-collect drafts --sources benchmark/ground_truth_tools/sources.csv --splits benchmark/ground_truth_tools/splits.locked.json --output benchmark/ground_truth_tools/pilot-v1 --pages 50 --seed 42
```

Split lock lưu hash inventory và membership của từng PDF. Nó từ chối unknown company, trùng/leakage, cùng hash PDF gán cho hai công ty hoặc thay dữ liệu trong lock đã có. Đổi dataset phải tạo phiên bản lock mới. Draft kiểm lại hash PDF, chỉ chọn train/dev, không lấy test; lấy mẫu round-robin theo company/ngành/quy mô/năm/loại trang/DPI. Loại trang và DPI là heuristic dùng cho lấy mẫu, cần người kiểm.

## 2. Gán nhãn và kiểm độc lập

Mỗi trang có `text.txt.pending`, `layout.json.pending`, `structure.json.pending`, `tables.html.pending`; `pilot_drafts.json` mang `UNANNOTATED` và `eligible_for_acceptance=false`. Không đưa các file này vào evaluator, không chỉ đổi đuôi để coi là đã xác minh.

Người gán nhãn đọc PDF gốc, giữ số/dấu/đơn vị và lưu ít nhất:

| Nhóm | Nội dung và trạng thái |
|---|---|
| L1 text | Unicode NFC, text theo thứ tự đọc; giữ dấu tiếng Việt, ngày, mã, số âm, %, đơn vị; vùng khó đọc có ignore rõ ràng |
| L2 layout | Bbox PDF point `xyxy` trong hệ tọa độ crop-relative chưa xoay; nhãn và ignore/iscrowd tách riêng |
| L3 reading order | Thứ tự item ID, quan hệ cột/figure_text; không suy ra từ y đơn thuần |
| L4 structure | Heading, level, parent, phạm vi trang, heading song ngữ và TOC nếu có |
| L5 table | HTML có rowspan/colspan, nội dung/raw số, bbox bảng/ô nếu xác định được, continuation nhiều trang |
| L6 labels | Sáu nhãn nhị phân theo taxonomy đã khóa; `Khac` loại trừ, không tự thêm nhóm thứ bảy |
| L7 KIE | Giá trị/raw/đơn vị/kỳ/phạm vi mẹ-hợp nhất/thực hiện-kế hoạch và nguồn trang/ô |

Mỗi nhóm nhận một trong `not_annotated`, `annotated_empty`, `annotated_nonempty`. Thiếu GT là `NOT_EVALUATED`; có GT nhưng không có prediction là `MISSING_OUTPUT` và vẫn chịu lỗi theo protocol. Trang xác nhận không có bảng khác với trang chưa gán nhãn bảng.

Taxonomy layout V6 dùng 11 nhãn: `Title`, `Section-header`, `Text`, `List-item`, `Table`, `Picture`, `Caption`, `Page-header`, `Page-footer`, `Document-index`, `Formula`. `Footnote` được bộ đo hỗ trợ bổ sung nhưng không thay nhãn bắt buộc. Các alias được chuẩn hóa bằng `coco_layout.canonical_class`; nhãn GT lạ gây lỗi, không tự đổi thành Text. Ignore theo diện tích prediction chồng vùng ignore; prediction khớp GT thật được giữ để tính. `iscrowd` theo backend COCO.

Ghi annotator ID, reviewer ID, ngày, nguồn tiền gán nhãn (nếu có) và lịch sử sửa. Một người khác kiểm tối thiểu 20% theo tầng cùng toàn bộ vùng bất đồng/số liệu khó; khóa quy tắc xử lý bất đồng trước gán nhãn chính thức. Mức kiểm và ngưỡng đồng thuận thực tế phải được chủ nhiệm chốt, không tự ghi `HUMAN_VERIFIED` cho draft do công cụ sinh.

Xuất GT sang format evaluator đã chọn bằng bước chuyển đổi có kiểm tra schema. Không coi layout draft là COCO JSON: scientific runner nhận COCO categories/annotations/images hoặc các records theo API; phải ghi mapping page→image ID và bbox format. Text evaluator hiện có tìm `<document_id>_page_NNNN.txt` (ví dụ `example_page_0001.txt`); dùng ID đầy đủ và thư mục GT riêng để tránh policy prefix legacy. Chỉ tạo file đó sau khi xác minh và lưu manifest human review. Table/structure/labels/KIE cần GT và evaluator tương ứng; không dùng confidence để thay chất lượng.

## Quy trình chuẩn bị corpus nghiệm thu mới

Quy tắc kiểm mẫu 20% ở trên áp dụng cho pilot V6 lịch sử. Với corpus nghiệm thu theo tài liệu 07 và 09, mỗi đơn vị cần hai người gán nhãn độc lập từ ảnh. Người phân xử lưu hai bản nhãn gốc, kết quả thống nhất, lý do loại trừ hoặc bất đồng và danh tính người thực hiện. Ghi đơn vị nguồn, PDF SHA-256, trang, bbox, hệ tọa độ và hash ảnh. Đối chiếu cả ô rỗng, số có 0 đầu, dấu và lần lặp thật. Giữ phần chưa rà ở trạng thái thiếu nhãn. Khóa guideline và quy tắc phân xử trước khi bắt đầu holdout.

Nhãn AI sơ bộ được lưu riêng với actor/provenance và trạng thái `AI_DRAFT`, không tự chuyển thành `HUMAN_VERIFIED` do hai tác nhân đồng ý. Với quy trình source-only đã chọn, không cấp bản AI/OCR/workbook cho hai người A/B trước khi họ nộp và khóa phiếu riêng. Khóa hash A/B trước khi phân xử; giữ bản gốc và lý do sửa. Hoàn tất packet hoặc đồng thuận AI không chứng minh accuracy hay độc lập thống kê.

Với bảng qua trang, dùng bộ phiếu L5 có bbox theo pixel ảnh cho từng mảnh ô qua ranh giới. Công cụ kiểm hai phiếu, khóa hash và nhận quyết định C để xuất bộ nhãn vùng ngắt dành cho phát triển. [Cách tiếp nhận L5](TABLE_BOUNDARY_INTAKE_V7.md).

### Tiếp nhận và khóa phiếu người cho pilot keyword

Điều phối viên chốt bản guideline dùng chung trước khi giao ảnh. Lưu nguyên bytes guideline đó đến hết lượt. Mỗi tài liệu dùng một source manifest `keyword-pilot-regions-v1` và thư mục phiếu mới. Hai người nhận gói ảnh và phiếu riêng, đọc phần đích đánh dấu trong từng ảnh, chép nguyên văn, giữ `020`/`O2O`, dấu, chữ hoa và lần lặp. Giữ `transcription: null` và ghi `ambiguity_reason` nếu chưa đọc được. Chỉ dùng `transcription: ""` khi xác nhận vùng rỗng, kèm `annotation_state: "annotated_empty"` và `empty_reason`. Giữ ID vùng, trang, hash ảnh và tọa độ đích đã cấp.

Nhận `annotation_A.json` và `annotation_B.json` riêng, giữ bytes gốc. Ghi `annotator_id` và `completed_at` có múi giờ trên phiếu khi nộp. Chạy các lệnh từ thư mục gốc dự án bằng Python supervisor. Trong ví dụ, đặt `$source`, `$packets`, `$guideline` theo hồ sơ thực, `$custody` là thư mục mới nằm ngoài `$packets`, `$receiver` là ID điều phối viên và `$dictionary` là snapshot từ batch dùng để đối chiếu.

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
$tool = @('-B', '-m', 'benchmark.ground_truth_tools.human_annotations')
$common = @('--source', $source, '--packets', $packets, '--guideline', $guideline)
$ab = Join-Path $custody 'declarations-ab.json'
$seal = Join-Path $custody 'seal-ab.json'
$c = Join-Path $custody 'declaration-c.json'
$decision = Join-Path $packets 'adjudication.json'
& .venv/Scripts/python.exe @tool declaration-template @common --output $ab
```

Mẫu xác nhận ghim SHA-256 của từng phiếu và để trống lời xác nhận. Sau khi xác minh trực tiếp với từng người, điều phối viên lưu `actor_type: "HUMAN"`, `completed_at`, `confirmed_at` có múi giờ và các xác nhận `source_images_checked`, `no_model_or_workbook`, `no_peer_before_submission`. Giữ hồ sơ gốc chứng minh ai nộp, thời điểm nộp và tài liệu đã giao. Chỉ chuyển cho người C sau khi khóa hai phiếu.

```powershell
& .venv/Scripts/python.exe @tool seal @common --declarations $ab --received-by $receiver --output $seal
& .venv/Scripts/python.exe @tool adjudication-template @common --declarations $ab --seal $seal --output $decision
```

C là người khác A/B. C đọc lại ảnh của mỗi vùng, kể cả khi A/B đồng ý, rồi điền `adjudicator_id`, `completed_at` có múi giờ, bản chép, `source_checked: true` và `decision_reason`. Giữ hash A/B do mẫu sinh. Tạo mẫu xác nhận C sau khi nhận phiếu C đã điền, rồi ghi xác nhận thật về danh tính, thời điểm, việc đọc ảnh và việc không xem OCR/workbook.

```powershell
& .venv/Scripts/python.exe @tool declaration-template @common --declaration-role C --seal $seal --output $c
# Complete C's declaration before running the audit.
$locked = @('--declarations', $ab, '--seal', $seal, '--adjudicator-declaration', $c)
& .venv/Scripts/python.exe @tool audit @common @locked --output (Join-Path $custody 'audit.json')
& .venv/Scripts/python.exe @tool export-keywords @common @locked --dictionary $dictionary --output (Join-Path $custody 'keyword-gt-development.json')
```

Lệnh `audit` trả mã `0` khi hồ sơ khai báo đầy đủ để điều phối viên duyệt, `1` khi thiếu phiếu hoặc xác nhận, `2` khi input không hợp lệ hoặc lỗi I/O. Lệnh chỉ tạo file mới. Khi phiếu đổi, lưu bản cũ và thực hiện lại quy trình với đường dẫn mới. Mặc định các đường dẫn nguồn PDF/ảnh trong manifest được giải từ thư mục gốc dự án. Dùng `--source-root` nếu ảnh/PDF hợp lệ nằm trong một cây dữ liệu khác.

Điều phối viên chịu trách nhiệm xác minh người thật, độc lập và nội dung ảnh. Kết quả xuất giữ văn bản nguyên gốc, vị trí, hash và các occurrence literal theo snapshot từ điển. Bộ nhãn này chỉ dùng cho `development`. Scorecard holdout từ chối artifact mang partition đó và tình trạng nghiệm thu vẫn là `NOT_EVALUATED`.

### Phân tập và rà rò rỉ

`splits-v2` nhận đúng bốn khóa trong assignments JSON gồm `train`, `development`, `calibration`, `holdout`. Mỗi khóa chứa danh sách ID công ty đã xác minh. Với nghiệm thu mới, dùng audit `split-leakage-audit-v2` có các trường sau.

- `schema_version` có giá trị `split-leakage-audit-v2` và `sources_sha256` là SHA-256 của CSV inventory đã bổ sung company ID. Giữ `status: DRAFT` trong lúc rà. Sau khi có đủ bằng chứng, người phụ trách điền `status: REVIEWED`, `reviewed_at` có múi giờ, `reviewed_by` và `holdout_custodian`.
- `template_groups` và `near_duplicate_groups` là hai map từ ID tài liệu sang nhóm đã rà, bao gồm cả tài liệu thuộc nhóm một phần tử. Mọi tài liệu trong CSV đều cần có mặt. Cùng nhóm phải thuộc cùng partition.
- `source_dispositions` có một mục cho mỗi ID tài liệu. Mỗi mục khai báo `status`, `exposure_evidence` và `rights_evidence`. Dùng `development_only` cho tài liệu đã dùng phân tích lỗi hoặc điều chỉnh hệ thống. Dùng `eligible_for_assignment` sau khi người phụ trách kiểm lịch sử sử dụng và quyền dùng. Tham chiếu bằng chứng cần chỉ rõ hồ sơ đã rà. Tài liệu `development_only` chỉ được gán vào `development`; những tài liệu cùng công ty hoặc cùng nhóm đã rà phải đi cùng partition.
- `partition_access` có hai tham chiếu hồ sơ quyền truy cập riêng cho `calibration` và `holdout`. Điều phối viên đối chiếu quyền truy cập thực tế và giữ bằng chứng. CLI kiểm hai tham chiếu khác nhau và ghim bytes audit; việc kiểm quyền trên máy hoặc kho dữ liệu do người phụ trách thực hiện.

```powershell
ocrpdf-collect splits --sources sources.csv --assignments assignments-v2.json --audit split-audit.json --output splits-v2.locked.json
ocrpdf-collect drafts --sources sources.csv --splits splits-v2.locked.json --audit split-audit.json --output pilot-v2 --pages 50 --seed 42
```

Audit là kết quả rà do người phụ trách cung cấp. CLI kiểm tính đầy đủ, membership và hash. Lệnh tạo pilot chỉ lấy train và development. Khóa lịch sử dùng audit v1 vẫn đọc được ở lệnh chẩn đoán. Preflight nghiệm thu yêu cầu bằng chứng nguồn theo audit v2. Khi đổi inventory, nhóm audit hoặc phân tập, dùng đường dẫn khóa mới.

#### Tạo danh sách cặp PDF để rà

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
.venv/Scripts/python.exe -B -m benchmark.scientific_evaluation.source_overlap `
  --sources scratch/HOSO/sources.csv --source-root inputs `
  --canonical-batch output/BATCH --report scratch/HOSO/pair-worklist.json
```

Bỏ `--canonical-batch` để dùng lớp chữ PDF. Khi có tùy chọn này, công cụ xác minh batch và đối chiếu đúng tập PDF rồi dùng chữ thô trong frozen evidence. Cả hai chế độ render ảnh thu nhỏ bằng CPU và kiểm SHA-256 PDF, số trang, SHA-256 inventory. Trang có cảnh báo render bị loại khỏi so sánh ảnh. Nếu dùng lớp chữ PDF, cảnh báo render hoặc đọc chữ cũng loại trang khỏi so chữ. Các trang thiếu tín hiệu được phản ánh trong mẫu số. Công cụ giữ cả cặp có cùng SHA-256 của PDF.

Danh sách ghi số trang vật lý và bằng chứng theo từng cặp tài liệu. So chữ dùng cụm bốn token, NFC và casefold cho mục đích truy hồi. So bố cục dùng cosine trên lưới ảnh xám chuẩn hóa và giới hạn chênh lệch tỷ lệ trang. Có thể gặp ảnh giống nhau do mẫu kiểm toán, trang bìa hoặc biểu mẫu chung. Điểm giống và ảnh thu nhỏ trùng là tín hiệu để xem ảnh nguồn. Người phụ trách ghi lý do, chốt nhóm sau khi xem bằng chứng và kiểm quyền sử dụng. Báo cáo giữ `DRAFT_FOR_CURATOR`, `NOT_EVALUATED` và mọi quan hệ nhóm để trống.

## GT cấu trúc cho báo cáo chẩn đoán

Lưu một file `structured-page-gt-v1` cho từng tài liệu. Đầu file có `schema_version`, `document_id`, `pdf_sha256`, `total_pages` và danh sách `pages`. Từng trang ghi `page` bắt đầu từ 1, `coordinate_space` và `transforms` đúng không gian ảnh đã gán nhãn. Bbox dùng `[x0, y0, x1, y1]` theo điểm PDF, gốc trên trái. Với trang xoay, ghi phép xoay như extraction.

- `tables` chứa `id`, `bbox` và một bảng HTML trong `html`. Dùng `[]` khi đã rà và trang không có bảng. Thiếu trường hoặc `null` biểu thị chưa rà.
- `numeric_cells_complete: true` xác nhận đã rà toàn bộ bảng trên trang. Khi đó mỗi bảng cần `numeric_cells`, kể cả danh sách rỗng. Ghi toàn văn từng ô chứa chữ số trong `value` và tọa độ logic `row`, `col` bắt đầu từ 0. Phép chấm ghép bảng bằng IoU rồi so ô theo hàng và cột, giữ dấu, ký hiệu và số 0 đầu. Chỉ số này đo ô chứa chữ số, chưa phân loại nghiệp vụ, đơn vị, kỳ báo cáo hoặc độ nghiêm trọng.
- `reading_order` có `nodes` và `before_pairs`. Mỗi node có `id`, `text` và `bbox`. Chỉ gán các cặp có quan hệ đọc xác định, giữ cả node ngắn, số và chữ lặp. Dùng `adjacent_pairs` nếu nguồn xác định hai node phải liền nhau, mỗi cặp cần nằm trong `before_pairs`. Danh sách cặp rỗng vẫn cho phép đếm node thừa/thiếu. Phạm vi v1 là các text block hiển thị trong extraction.
- `layout` là danh sách vùng vật lý gồm `id`, `category` theo taxonomy V6 và `bbox` dạng `xyxy` trong cùng hệ tọa độ/transform với trang. Dùng `[]` cho trang đã rà và xác nhận rỗng. Thiếu trường hoặc `null` biểu thị chưa gán nhãn. Vùng loại trừ dùng `ignore: true`. Vùng crowd dùng `iscrowd: true` và cần category. Hai cờ là boolean và không bật cùng lúc.

```powershell
.venv/Scripts/python.exe scripts/run_scientific_benchmark.py --prediction output/RUN/DOC --ground-truth benchmark/ground_truth --structured-gt scratch/DOC.structure.json --output-dir scratch/DOC-score
```

Harness cũ trong `Test case/` đã bị người dùng xóa ngày 08/11/2026, và các test của nó đã bỏ theo quyết định ngày 10/11 (V8-170); chỉ dùng `scripts/run_scientific_benchmark.py`. Báo cáo giữ riêng điểm chữ từ `result.md`, điểm cấu trúc từ `extraction.json`, hash hai file dùng cho chấm cấu trúc và các trang thiếu đầu ra theo modality. Phần cấu trúc đối chiếu ID và tiền tố SHA-256 ghi trong extraction. Nghiệm thu cần liên kết SHA-256 đầy đủ với receipt của run, GT và protocol đã khóa. Điểm chẩn đoán có thể đo trên dữ liệu phát triển trước khi đủ điều kiện nghiệm thu.

### Chấm bố cục vật lý

Adapter `canonical-layout-boxes-v1` đọc bbox và role từ `extraction.json`. Đầu/chân trang đã nhận dạng vẫn tham gia vì đây là bố cục trên trang. Số trang đứng riêng nằm ngoài taxonomy và có danh sách loại riêng. Table dùng bbox bảng, còn fragment mang nhãn ô rời không tự đổi thành Table. Giữ ID vùng chưa ánh xạ hoặc thiếu bbox để tính vùng thừa.

Ghép một-một theo lớp tại IoU ≥ 0,5, ưu tiên số cặp khớp rồi tổng IoU. Dự đoán trùng một vùng hợp lệ vẫn tính thừa. Vùng ignore áp ngưỡng chồng 0,5 theo diện tích dự đoán. Vùng crowd chỉ bỏ qua dự đoán cùng lớp. Báo cáo giữ TP/FP/FN và ID vùng khớp/thừa/thiếu, kể cả trang xác nhận rỗng hoặc trang thiếu đầu ra. `Footnote` có mặt trong chẩn đoán và không thay cho một lớp bắt buộc của V6.

Khi có nhãn hợp lệ, báo cáo chẩn đoán có thể tính COCO mAP bằng `pycocotools`. Bbox không có điểm layout xuất bản dùng cùng thứ hạng mặc định. Điểm confidence của nhận dạng chữ không được dùng để xếp hạng mAP bố cục. Scorecard paired dùng số đếm ghép bbox thay vì trung bình mAP từng trang.

GT dùng ở scorecard cần `intended_partition: holdout`. Khi protocol khai báo modality `layout`, khóa kế hoạch, ngưỡng tuyệt đối và margin của hai metric overall `layout_recall = TP/(TP+FN)` và `layout_errors_per_gt = (FP+FN)/(TP+FN)`. Dùng mẫu số chung là vùng GT thường, không gồm ignore/crowd. Giữ FP của trang được gán nhãn rỗng trong tử số. Cổng giữ `NOT_EVALUATED` nếu thiếu lớp GT bắt buộc hoặc thiếu chỉ số overall. Đơn vị có GT mà thiếu prediction vẫn chịu lỗi trong mẫu số.

### Căn thứ tự đọc khi khối bị tách hoặc gộp

Hai người gán nhãn đọc ảnh và người phân xử chốt GT nguồn, gồm node, thứ tự và cặp liền nhau. Chốt `reading_order.alignment_mode` theo trang trước khi rà prediction. Dùng `automatic` hoặc bỏ trường để giữ cách ghép một-một V6.2. Dùng `reviewed_spans` trên trang yêu cầu đối chiếu từng đoạn. Hai phía baseline/candidate dùng cùng chế độ của GT. Khi khóa holdout, đưa file GT vào manifest đã khóa trước khi mở prediction để rà.

Sau khi khóa GT, người rà căn nguồn lập **một artifact mỗi tài liệu và mỗi prediction**. Schema `ocr-reading-order-alignment-v1` có `document_id`, `pdf_sha256`, `ground_truth_sha256`, `extraction_sha256`, `intended_partition`, `reviewed_by`, `reviewed_at` (ISO 8601 có múi giờ), `reviewed_against_source: true` và `pages`. Mỗi trang có số trang vật lý `page` và `mappings`. Mỗi mapping có `gt_id`, `reason` và `spans` dưới dạng `{"prediction_id": "...", "start": 0, "end": 3}`.

- Offset là chỉ số code point bắt đầu từ 0 trên chính `text_corrected` của item, tính đoạn `[start, end)`. Giữ nguyên dấu và khoảng trắng khi tính offset. Chỉ chọn đoạn chứa chữ hoặc ký hiệu có nghĩa trong text block hiển thị có bbox giao với node nguồn.
- Khối tách dùng nhiều span cho cùng một GT node. Khối gộp dùng những span rời nhau trong cùng prediction item. Mỗi đoạn prediction dùng tối đa một lần. Căn theo ảnh và bằng chứng vị trí, giữ các đoạn thiếu hoặc thừa đúng như đầu ra.
- Rà toàn bộ node trong trang khai báo `reviewed_spans`. Node vắng mặt bỏ khỏi `mappings`; `mappings: []` xác nhận đã rà và không có node nào khớp. Nếu còn điểm chưa rõ, giữ hồ sơ trang chưa nộp cho tới khi phân xử.
- Cặp đúng khi mọi span của node trước kết thúc trước hoặc đúng điểm bắt đầu của span đầu tiên của node sau. Các đoạn xen kẽ tính cặp sai. Cặp liền nhau còn yêu cầu giữa hai đoạn không có nội dung khác hoặc block chen vào. Báo riêng GT node khớp, prediction block được dùng, khối thừa và cặp đúng.

Truyền `--reading-order-alignment <file>` cùng `--structured-gt <file>` vào scientific runner. Nếu còn trang có prediction nhưng thiếu hồ sơ căn bắt buộc, aggregate giữ `NOT_EVALUATED` và ghi danh sách trang. Trang có GT mà thiếu prediction vẫn chịu lỗi trong mẫu số. Người điều phối kiểm danh tính và đối chiếu thực tế; phần mềm kiểm phạm vi, span, khai báo và hash file.

Ở scorecard dùng `--reading-order-alignments <index>`. Cổng phát hành dùng `--baseline-reading-order-alignments <index>` và `--candidate-reading-order-alignments <index>`. Mỗi index `ocr-reading-order-alignment-index-v1` có `side`, `prediction_inventory_sha256` và `documents` ánh xạ ID tài liệu sang `path` tương đối, `sha256`. Artifact dùng cho scorecard cần `intended_partition: holdout`; kết quả chấm giữ hash căn nguồn theo trang.

## 3. Bootstrap paired và Holm

Một count report cho mỗi metric có metadata giống nhau ở B0/candidate:

```json
{
  "gt_sha256": "sha256_of_locked_gt_manifest",
  "splits_sha256": "sha256_of_locked_splits",
  "normalization": "locked_normalization_version",
  "records": [
    {"company_id": "verified_id", "document_id": "example", "page": 1,
     "status": "MEASURED", "numerator": 3, "denominator": 100}
  ]
}
```

CER/WER/DER dùng số lỗi và số ký tự/từ/dấu GT; số lỗi có thể lớn hơn mẫu số. TEDS/F1 dùng tổng score và số đơn vị GT; lỗi số dùng count thô và cùng reference count. Các lần lấy mẫu giữ toàn bộ trang của mỗi công ty rồi tính lại micro ratio/tổng lỗi, không trung bình tỷ lệ trang. `region_id` phân biệt nhiều đơn vị trên cùng trang. Thiếu output phải có record paired; numeric missing cần count lỗi GT rõ ràng.

```powershell
python -m benchmark.scientific_evaluation.cluster_statistics --baseline b0-counts.json --candidate f-counts.json --metric cer --output comparison.json --seed 42 --resamples 2000 --margin 0.005
python -m benchmark.scientific_evaluation.matrix_statistics --input matrix-counts.json --output matrix-statistics.json
```

Biên CER/DER 0.005, WER 0.01, TEDS/F1 0.01, lỗi số 0 hiện chỉ là **đề xuất**. CLI đơn lẻ không tự duyệt biên. Input ma trận có `protocol` (metrics, seed, resamples, margins, alpha, status/approved_by) và `runs` (`B0`, `F`, `A1`–`A6`, `V1`). Mỗi run lưu run ID, config SHA256, metadata GT/splits/normalization và `records_by_metric`. Công cụ không triển khai hay tự chạy các ablation.

Họ kiểm định gồm toàn bộ 8 candidate × metrics đã khai báo. Slot thiếu/chạy lỗi vẫn có trong report với p=1 phục vụ Holm; không được coi là đo thành công. Báo CI percentile chưa hiệu chỉnh riêng với p sau Holm. CI suy biến/ít công ty/mismatched GT không được coi là đạt. `eligible_for_quality_acceptance=false` vẫn cần ngưỡng tuyệt đối 9.3, GT thực và hồ sơ thí nghiệm.

## 4. Điều kiện nghiệm thu còn thiếu

Chốt company metadata/splits, người gán nhãn/kiểm GT, B0 sạch, normalization và ADJ-01–05; chọn D1 và đường bảng trên dev; khóa ngưỡng rồi mới chạy test. Giữ test kín. Chạy đủ các loại trang/DPI và workload CPU/GPU mục tiêu, báo p50/mean/p95, throughput tổng, RSS/VRAM đúng phạm vi. Fixture synthetic không thay thế bất kỳ điều kiện nào trong số này.
