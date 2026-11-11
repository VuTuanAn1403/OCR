# Adapter OmniDocBench cho BK-07

`omnidocbench_adapter` xuất cặp prediction canonical sang Markdown từng ảnh cho evaluator chính thức. Commit evaluator được ghim là `ea2d138c7d2e185feb71ef8014e97d7206820b34`. README nhánh này ghi cập nhật v1.7, còn metadata package ghi 1.6.0. Danh tính dùng commit và hash file, cùng revision dataset riêng. [Nguồn chính thức đã ghim](https://github.com/opendatalab/OmniDocBench/tree/ea2d138c7d2e185feb71ef8014e97d7206820b34).

Evaluator end2end nhận JSON GT và thư mục Markdown từng trang. Tên Markdown theo basename ảnh, đổi bốn ký tự cuối thành `.md`. Adapter hỗ trợ ảnh JPG/PNG, giữ HTML bảng, biểu thức LaTeX và thứ tự nội dung. Asset được kiểm hash, copy theo namespace tài liệu và cập nhật liên kết. [Resolver tên file](https://github.com/opendatalab/OmniDocBench/blob/ea2d138c7d2e185feb71ef8014e97d7206820b34/src/dataset/end2end_dataset.py) · [Cấu hình evaluator](https://github.com/opendatalab/OmniDocBench/blob/ea2d138c7d2e185feb71ef8014e97d7206820b34/configs/end2end.yaml).

## Chuẩn bị nguồn và plan

Plan `ocr-omnidocbench-export-plan-v1` hiện áp dụng `partition: development`. Ghi `dataset_version`, `dataset_revision` là commit 40 ký tự hex và `evaluator` gồm `repository`, `revision` như trên. Dùng `ground_truth: {path, sha256}` tương đối với `--dataset-root`. Danh sách `sources` ghi đủ mỗi ảnh GT đúng một lần, với `image_name`, `image: {path, sha256}`, `document_id` và `pdf_sha256`. Basename ảnh và tên Markdown phải duy nhất khi so không phân biệt hoa thường.

Mỗi PDF đầu vào có một trang chứa đúng ảnh đã pin, phủ kín trang theo hướng gốc. Adapter kiểm pixel RGB nhúng khớp ảnh, kích thước GT, nguồn chữ native, vector và annotation. Mask ảnh bị từ chối. Trang PDF được render về đúng lưới pixel của ảnh nguồn và phải khớp RGB từng byte; ảnh bị clip hoặc ẩn không thể được chấp nhận chỉ vì dữ liệu ảnh nhúng còn nguyên. Hash pixel hiển thị được ghi trong `pixel_proof`/`source_images`. Đây là phép kiểm nguồn đầu vào, chưa phải phép đo accuracy. Bộ `omnidocbench_corpus` chuẩn bị PDF ảnh và plan từ snapshot nguồn trước prediction.

```powershell
$env:PYTHONPATH = ((Resolve-Path .).Path,(Resolve-Path src).Path -join ';')
.venv/Scripts/python.exe -B -m benchmark.scientific_evaluation.omnidocbench_corpus `
  --ground-truth scratch/omni-data/OmniDocBench.json --ground-truth-sha256 <sha256-gt> `
  --dataset-root scratch/omni-data --image-directory images `
  --dataset-version <ten-release-dataset> --dataset-revision <commit-dataset-40-hex> `
  --output scratch/omni-inputs-new
```

Output có thư mục `inputs`, `export-plan.json` và `prepared.json`. Tên PDF dùng hash nội dung, DPI mặc định 180 như profile hiện hành. Bộ chuẩn bị kiểm pixel sau khi nhúng, giữ file nguồn và ghim hash ảnh/GT/PDF. Lượt chuẩn bị trùng dữ liệu tạo cùng byte. `prepared.json` được ghi cuối khi nguồn kiểm lại không thay đổi. Cần pipeline canonical chạy trên thư mục `inputs` khi người dùng cho phép, rồi dùng plan đã tạo để xuất paired.

Khi nhiều mục ảnh tạo cùng byte PDF, bộ chuẩn bị dùng một PDF với alias nguồn rõ ràng. Adapter phát Markdown riêng cho từng mục GT và ghi `image_units`, `distinct_pdf_inputs` và nhóm alias. Số mục GT và số PDF được báo riêng. GT gốc được giữ đủ, cùng prediction nguồn có thể phục vụ các tên ảnh tương đương đã kiểm pixel.

Revision, ảnh và GT do curator cung cấp cần được đối chiếu với nguồn phát hành dataset, quyền dùng và lịch sử model. Adapter kiểm tính nhất quán của snapshot đã khai báo. Nó chưa xác thực quyền, nhãn người hoặc contamination của model.

## Xuất cặp prediction

```powershell
$env:PYTHONPATH = ((Resolve-Path .).Path,(Resolve-Path src).Path -join ';')
.venv/Scripts/python.exe -B -m benchmark.scientific_evaluation.omnidocbench_adapter `
  --plan scratch/omnidocbench-plan.json --plan-sha256 <sha256-plan-da-khoa> `
  --dataset-root scratch/omnidocbench-dataset `
  --baseline output/omni-baseline --candidate output/omni-candidate `
  --output scratch/omni-export-new
```

Hai phía phải là publication canonical đã acknowledge, cùng tập PDF/hash và có output riêng. GT được copy nguyên byte. Trang xuất lấy từ `result.md`, bỏ lời dẫn/marker và dấu phân trang do exporter tạo, chuẩn hóa CRLF, giữ phần thân. Trang rỗng vẫn xuất file rỗng. Marker trùng, thiếu, ảnh/PDF sai, Markdown đổi hash, asset ngoài publication và tên file đụng nhau bị từ chối.

Output có `ground-truth.json`, `baseline`, `candidate` và `export.json`. Mỗi phía có `predictions`, `assets` và `end2end.yaml`. Manifest ghim tất cả file xuất, inventory hai phía, plan, ảnh nguồn, mã adapter và parser marker. Một worker được dùng cho matching/CDM/TEDS. Cấu hình giữ `quick_match`, metric Text Edit distance, table TEDS/Edit distance, formula CDM/Edit distance và reading-order Edit distance theo hợp đồng đã đọc.

Exit 0 chỉ xác nhận gói paired hợp lệ. `official_evaluation` vẫn `NOT_RUN` và chất lượng `NOT_EVALUATED`. Khi lỗi, giữ output dở để kiểm và dùng thư mục mới cho lần thử tiếp. File `export.json` chỉ được ghi cuối lượt thành công.

## Chạy evaluator riêng và giới hạn

Dùng checkout evaluator ở đúng commit, môi trường dependency riêng và runtime TeX/ImageMagick/Ghostscript đã pin. Chạy `python pdf_validation.py --config <đường-dẫn-end2end.yaml>` từ checkout đó, lưu cả log, runtime và kết quả từng phía. Hai phía dùng cùng dataset/evaluator/config đo, chỉ khác prediction. [Entry point chính thức](https://github.com/opendatalab/OmniDocBench/blob/ea2d138c7d2e185feb71ef8014e97d7206820b34/pdf_validation.py).

Các điểm OmniDocBench có phương pháp và population riêng. Hồ sơ v7.0 còn cần GT, protocol và phép đo nội bộ theo [các tiêu chí của bộ v8](../../cai%20tien%20v2/00_README.md). Phiên phát triển mới kiểm adapter trên fixture và resolver chính thức. Chín PDF tài chính đã lưu không có GT OmniDocBench tương ứng. Chưa chạy evaluator chính thức hoặc inference mới trên bộ công khai.
