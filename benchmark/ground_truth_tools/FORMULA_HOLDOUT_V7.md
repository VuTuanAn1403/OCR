# Nhận và kiểm lại nhãn công thức holdout

Người giữ tập holdout chuẩn bị mẫu và nhận phiếu trong thư mục có quyền truy cập riêng. Nguồn đã dùng để phát triển, gồm ba trang pilot AGR/ASM, thuộc tập development. Ghim file và khai báo danh tính giúp kiểm lại hồ sơ. Người giữ tập xác minh danh tính, tính độc lập, quyền sử dụng nguồn và việc ảnh khớp trang PDF.

## Chốt mẫu trang trước khi phát phiếu

1. Dùng inventory `sources.csv`, `splits-v2` và audit `split-leakage-audit-v2` đã được rà. Mẫu `ocr-formula-scorecard-sample-v1` ghi `document_id`, `pdf_sha256` và danh sách trang vật lý `pages` của từng PDF holdout. Ghi cả trang âm tính được chọn. Để tập development ngoài mẫu này.
2. Tạo manifest ảnh với `schema_version: ocr-formula-holdout-source-v1` và `partition: holdout`. Mỗi tài liệu ghi `document_id`, `pdf_sha256`, `total_pages`, `pages`. Mỗi trang ghi `page`, `coordinate_space`, `transforms`, `width`, `height`, `image` và `image_sha256`. Đường dẫn ảnh tính từ thư mục manifest ảnh. Ghi khung tọa độ theo trang thực tế và cách quy đổi từ pixel sang tọa độ PDF trong hướng dẫn đi kèm. PDF được lấy theo `relative_path` trong inventory, tính từ `--pdf-root`.
3. Tạo hồ sơ `ocr-formula-holdout-intake-v1`. Người giữ tập ghi `status: REVIEWED`, `reviewed_by` trùng `holdout_custodian` của split, `reviewed_at` có múi giờ, `source_manifest_sha256` và `guideline_sha256`. Thêm các cặp `<tên>_path` và `<tên>_sha256` cho `sample`, `sources`, `splits`, `source_use_audit`. Đường dẫn tương đối và nằm dưới thư mục hồ sơ. Thời điểm rà intake phải sau hoặc cùng thời điểm rà quyền nguồn. Công cụ kiểm lại split, trang và hash trước khi đọc phiếu.

## Phát phiếu, niêm phong và phân xử

Chạy từ checkout bằng Python supervisor. Ví dụ dùng các đường dẫn đã chuẩn bị dưới `scratch/holdout`, với thư mục `packets` tách khỏi `source` và `pdf`. `guideline.md` phải là bản đã ghim trong intake. Có thể dựa vào [quy tắc gán nhãn công thức](FORMULA_ANNOTATION_V7.md) và ghi cách quy đổi tọa độ của tập này.

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
$holdout = 'scratch/holdout'
$common = @('--source', "$holdout/source/manifest.json", '--guideline', "$holdout/guideline.md", '--pdf-root', "$holdout/pdf", '--holdout-intake", "$holdout/intake.json")
.venv/Scripts/python.exe -B -m benchmark.ground_truth_tools.formula_annotations template-a @common --output "$holdout/packets/blank-A.json"
.venv/Scripts/python.exe -B -m benchmark.ground_truth_tools.formula_annotations template-b @common --output "$holdout/packets/blank-B.json"
```

Gửi riêng cho A và B ảnh, hướng dẫn và phiếu tương ứng. Hai người hoàn thành từ ảnh sau khi intake được rà. Giữ nguyên `holdout_intake_sha256`. Sau khi nhận đủ hai bản nộp, người giữ tập chạy các bước sau với chính tên đã ghi trong split. Người C nhận phiếu sau khi seal và phân xử với hai bản đã niêm phong. Các trang âm tính cần `formulas: []` và lý do đã rà toàn trang.

```powershell
$packets = @('--a', "$holdout/packets/A.json", '--b', "$holdout/packets/B.json")
.venv/Scripts/python.exe -B -m benchmark.ground_truth_tools.formula_annotations seal @common @packets --received-by 'TEN_NGUOI_GIU_TAP' --output "$holdout/packets/seal.json"
.venv/Scripts/python.exe -B -m benchmark.ground_truth_tools.formula_annotations template @common @packets --seal "$holdout/packets/seal.json" --output "$holdout/packets/blank-C.json"
.venv/Scripts/python.exe -B -m benchmark.ground_truth_tools.formula_annotations audit @common @packets --seal "$holdout/packets/seal.json" --c "$holdout/packets/C.json" --output "$holdout/packets/audit.json"
```

## Ghim phân xử để bộ đo dựng lại tham chiếu

Tạo `ocr-benchmark-adjudication-manifest-v1` và ghi hash ở `data.adjudication_manifest_sha256`. Trong object `formula_custody`, người giữ tập ghi `status: REVIEWED`, `reviewed_by`, `reviewed_at`, `review_evidence` tham chiếu biên bản xác minh. Ghim các cặp `<tên>_path` và `<tên>_sha256` cho `source`, `intake`, `guideline`, `a`, `b`, `seal`, `c`. Mọi đường dẫn tương đối và nằm dưới thư mục manifest phân xử. Thứ tự thời gian là intake, hai bản nộp A/B, seal, bản C, rà của người giữ tập, khóa protocol. Hai bản nộp A/B có thể hoàn thành theo thứ tự bất kỳ.

`replay_holdout_references` là hàm bộ đo gọi sau preflight. Hàm so hash manifest phân xử, hướng dẫn, mẫu, inventory, split và audit quyền nguồn với protocol, rồi dựng lại danh sách công thức từ A/B/C, seal và ảnh. Công cụ kiểm mỗi mục được phân xử đúng một lần và mỗi trang trong mẫu có kết quả rõ ràng. Dùng lệnh replay để căn các tham chiếu này với hai publication canonical và đo định vị, TEXT. [Lệnh đo lại](../scientific_evaluation/FORMULA_HOLDOUT_REPLAY_V7.md).
