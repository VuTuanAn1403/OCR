# Công cụ tiếp quản: công thức, keyword và identity holdout

Các công cụ dưới đây dùng Python supervisor. Chúng không chạy OCR, không sửa receipt/khóa và không tự tạo quyết định của người duyệt. Trạng thái dự án vẫn lấy từ `cai tien v2/10_TRANG_THAI_V8.json`.

## Công thức OmniDocBench (V8-085)

`benchmark.scientific_evaluation.omnidocbench_formula` có hai bước. `prepare` kiểm plan, hash GT/ảnh/PDF, pixel hiển thị, số trang và tọa độ trước khi tạo annotation. Nội dung LaTeX, polygon và ID nguồn được giữ nguyên; bbox là bao chữ nhật của polygon đổi sang PDF points. Mỗi PDF phải ứng với một ảnh; alias PDF bị từ chối để tránh nhân hoặc bỏ mẫu số.

```powershell
$env:PYTHONPATH='src;.'
.venv/Scripts/python.exe -B -m benchmark.scientific_evaluation.omnidocbench_formula prepare `
  --plan <export-plan.json> --plan-sha256 <hash-plan-da-ghim> `
  --dataset-root <dataset> --inputs <thu-muc-PDF-anh> --output <nhan-moi>
```

Chạy pipeline chuẩn trên toàn bộ `inputs` sau khi GPU trống. `score` yêu cầu publication canonical đủ mọi PDF đã ghim và dùng lại `formula_alignment`/`formula_scorecard`:

```powershell
.venv/Scripts/python.exe -B -m benchmark.scientific_evaluation.omnidocbench_formula score `
  --prepared <nhan-moi> --prepared-sha256 <sha256-cua-prepared.json> `
  --batch <output-OCR> --iou-threshold <nguong-development-da-chon> --output <score-moi>
```

Output có `alignment/cdm-pairs.json`, `alignment/alignment.json`, `scorecard.json` và manifest `run.json`. Dùng cặp này để chạy [CDM](../../benchmark/scientific_evaluation/FORMULA_CDM_V7.md), rồi chạy `score` vào thư mục mới với `--cdm <thu-muc-CDM>`. `--critical` nhận phiếu critical đã duyệt, nếu có. Công cụ không điền thay người duyệt hoặc suy TEXT từ LaTeX.

Đây là scorecard development theo hình học của dự án, không phải điểm evaluator chính thức OmniDocBench và không thay [chính sách nghiệm thu công thức](../../benchmark/scientific_evaluation/FORMULA_ACCEPTANCE_POLICY_V7.md). Bộ 223 trang đã chọn chỉ có 1.660 nhãn display; TEXT CER và chất lượng inline chưa được đánh giá. `company_id` giữ `unknown`; không suy công ty từ tên ảnh để tính cận. Critical, renderer validation, applicability và protocol phát hành vẫn cần bằng chứng riêng.

## Phiếu đối chiếu occurrence keyword (V8-100)

Trước hết gán nhãn nguồn A/B/C và xuất GT bằng [quy trình người duyệt](../../benchmark/ground_truth_tools/ANNOTATION_V6.md). Công cụ mới chỉ tạo phiếu liên kết prediction với **GT đã chốt**, không tạo GT từ OCR và không thay bước chọn phạm vi nguồn.

```powershell
.venv/Scripts/python.exe scripts/review_keyword_occurrences.py prepare `
  --document <output/DOC> --dictionary <keyword_dictionary.snapshot.json> `
  --ground-truth <keyword-gt-development.json> --pdf <PDF-nguon> --output <phieu-moi>
.venv/Scripts/python.exe scripts/serve_review_sheets.py --directory <phieu-moi> --port 8774
```

Mở địa chỉ local trong trình duyệt. Mỗi occurrence phải được người duyệt liên kết với GT, đánh dấu thừa trong vùng, hoặc ghi lý do ngoài phạm vi. Phiếu giữ nguyên hash, vùng nguồn, trang và offsets; vùng chưa có GT không được coi là đúng. Có highlight occurrence đang xét, ảnh nguồn với bbox, bản chép đã chốt, danh sách cả GT chưa được prediction liên kết. Mọi quyết định ban đầu đều trống. Dùng tải JSON hoặc bản autosave trên đĩa:

```powershell
.venv/Scripts/python.exe scripts/review_keyword_occurrences.py export `
  --sheet <phieu-moi> --decisions <quyet-dinh.json> --output <ket-qua-moi>
```

Exporter kiểm lại hash PDF, GT, ảnh, từ điển và inventory publication. `alignment.json` của lượt literal tương thích `keyword_acceptance.py`. Đọc `score.json.status` để biết PASS/FAIL/NOT_EVALUATED trong phạm vi đã duyệt. Báo cáo giữ riêng missing, extra và liên kết lặp dù tổng bằng nhau.

Với output phân tích đã tích hợp Q6/Q7, tạo phiếu chờ duyệt bằng cùng lệnh `prepare` kèm `--pending --literal-alignment <ket-qua-literal/alignment.json>`. Phiếu liệt kê alias chưa giải quyết, ứng viên O/0 và từ khóa trong dòng A1 bị loại. Export ghi số reference được phủ thêm sau khi bỏ trùng cùng ID, các ứng viên dư và reference còn thiếu. Khi chưa có alignment literal, báo cáo chỉ ghi kết quả của phiếu pending. Hai lượt giữ `eligible_for_quality_acceptance: false`. Số đếm Excel vẫn lấy từ pipeline và quy tắc duyệt hiện hành.

## Identity cho input holdout mới

Chế độ mặc định của `check_baseline_identity.py` vẫn kiểm đúng danh sách PDF trong khóa. Với input mới:

```powershell
.venv/Scripts/python.exe scripts/check_baseline_identity.py `
  --new-inputs --lock <baseline_lock.json> --output <batch-holdout> --report <bao-cao-moi.json>
```

Chế độ này so snapshot code, config đã resolve, hash model/lock, đường dẫn interpreter và request defaults với baseline. Sau đó kiểm hash PDF hiện tại, loại trùng byte baseline và tính identity theo `ocr_pipeline.backend.ocr_identity`; receipt hợp lệ và đủ mọi trang vẫn bắt buộc. Báo cáo giữ `scope: NEW_INPUTS_FROZEN_BASELINE_RUNTIME`. Khóa baseline không bị sửa. Cần chạy thêm `audit_batch_outputs.py --validate` để kiểm publication/SQLite, và đọc nội dung báo cáo audit thay vì dùng exit code 0 làm bằng chứng chất lượng.

Kiểm identity không chứng minh nguồn GT độc lập, đúng protocol hoặc accuracy. Chỉ đo holdout khi đủ phiếu sàng lọc ACCEPTED và khóa đo được duyệt.

Khi có hai báo cáo `MATCH`, truyền `--baseline-identity` và `--candidate-identity` cho `scripts/compare_text_layer_runs.py` cùng hai output, khóa và seal. So cặp kiểm đủ cùng cohort, cùng reference và receipt hiện tại. Báo cáo holdout chỉ giữ số tổng hợp. CER đo trên các đơn vị chung của phép đo dấu và giữ tử số, mẫu số.

## Kiểm lại mù các quyết định phân xử dấu

Dùng phiếu gốc và `seal.json` của phân xử lần đầu. Theo §7.4 D, công cụ lấy 10% quyết định theo seed, tối thiểu 50 nếu đủ mục. Phiếu dùng ảnh gốc đã xác minh và một ID lưu riêng. Đọc mốc `review_not_before` trước khi giao người duyệt.

```powershell
.venv/Scripts/python.exe -B scripts/recheck_diacritic_adjudication.py build `
  --sheet <phieu-goc> --sealed <seal.json> --out <phieu-kiem-lai-moi>
.venv/Scripts/python.exe -B scripts/recheck_diacritic_adjudication.py resolve `
  --sheet <phieu-goc> --sealed <seal.json> --recheck-decisions <lan-2.jsonl> --out <ket-qua-moi>
```

`agreement.json` ghi tỷ lệ đồng thuận và hash đầu vào. Nếu có mục lệch, output có phiếu lần ba. Chạy lại `resolve` với `--third-decisions <lan-3.jsonl>` và output mới. Mục vẫn lệch chuyển `UNRESOLVED`. Dùng `decisions-reconciled.jsonl` để chạy `adjudicate_text_layer_diacritics.py seal` vào thư mục mới. Giữ cả phiếu, quyết định và seal ban đầu để truy lại. Dữ liệu sau bước này vẫn cần áp dụng cổng 99,99% theo protocol.
