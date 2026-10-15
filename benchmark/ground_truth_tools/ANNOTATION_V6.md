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
