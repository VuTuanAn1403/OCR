# Gán nhãn công thức từ ảnh và phân xử A/B/C

Pilot này dùng ba ảnh toàn trang AGR 2022 trang 38, 43 và ASM 2022 trang 67 để phát triển bộ đo. A và B nhận riêng gói cùng ảnh nguồn, làm độc lập rồi gửi phiếu của mình cho điều phối viên. Người C chỉ bắt đầu sau khi điều phối viên niêm phong hai bản nộp. Dùng ảnh gốc khi gán nhãn và phân xử.

## Phiếu A hoặc B

1. Mở ảnh ở kích thước gốc để lấy bbox `[x0, y0, x1, y1]`. Với ảnh 144 dpi trong pilot, chia tọa độ pixel gốc cho 2 để đổi sang điểm PDF. Bbox ôm đúng biểu thức. Rà toàn trang, giữ đúng số trang vật lý.
2. Mỗi biểu thức cần `id` duy nhất trên trang, `bbox`, `placement` (`inline` khi thuộc đoạn hoặc ô bảng, `display` khi là khối riêng), `format` (`TEXT`, `LATEX`, `MATHML`), `content_raw` và `equation_label`. Dùng `null` cho nhãn phương trình vắng. Với chữ tuyến tính nhìn thấy, dùng `TEXT`. Giữ dấu, chữ số, 0 đầu, tử/mẫu, chỉ số, số mũ, ngoặc và đơn vị theo ảnh. Các biểu thức lặp ở vị trí khác cần ID riêng.
3. `formulas: null` nghĩa là chưa rà xong. `formulas: []` nghĩa là đã rà toàn trang và xác nhận âm tính. Vùng không đọc được hoặc ngoài phạm vi phải có `ignore_regions` với `id`, `bbox` và `reason`. ID ignore và ID công thức cần khác nhau trên cùng trang. Ghi chú trường hợp phân vân.
4. Khi hoàn thành tất cả trang, điền `annotator`, `actor_type: "HUMAN"`, `completed_at` có múi giờ và `status: "SUBMITTED"`. Người nộp xác nhận `source_images_checked`, `no_model_or_native_text` và `no_peer_before_submission` là `true` chỉ khi đúng thực tế. Dùng ảnh nguồn trong gói, giữ nguyên hash manifest và hướng dẫn. Nộp trực tiếp cho điều phối viên.

## Điều phối và phân xử

`formula_annotations` kiểm SHA-256 PDF, ảnh, manifest và hướng dẫn, rồi kiểm khung trang, phạm vi, phiếu và khai báo. `audit` ghi kết quả vào file mới. `seal` chỉ tạo seal khi A/B hoàn tất và khác người. `template` đọc hai phiếu còn nguyên byte theo seal rồi tạo phiếu trống cho C. Dùng các lệnh từ thư mục dự án và đặt file đầu ra ngoài thư mục nguồn.

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
$source = 'scratch/dev_sessions/20261104-formula-source-alignment/pilot-source/source-manifest.json'
$guide = 'benchmark/ground_truth_tools/FORMULA_ANNOTATION_V7.md'
$common = @('--source', $source, '--guideline', $guide, '--a', 'scratch/nhan/A.json', '--b', 'scratch/nhan/B.json')
.venv/Scripts/python.exe -B -m benchmark.ground_truth_tools.formula_annotations audit @common --output scratch/nhan/audit.json
.venv/Scripts/python.exe -B -m benchmark.ground_truth_tools.formula_annotations seal @common --received-by 'TEN_DIEU_PHOI_VIEN' --output scratch/nhan/seal.json
.venv/Scripts/python.exe -B -m benchmark.ground_truth_tools.formula_annotations template @common --seal scratch/nhan/seal.json --output scratch/nhan/blank-C.json
```

Người C đối chiếu ảnh với hai phiếu đã niêm phong. Với mỗi trang, điền `formulas`, `ignore_regions`, `page_reason` và các nhóm `decisions`. Một nhóm gồm `id`, `A` (danh sách ID từ A), `B` (danh sách ID từ B), `final` (ID các mục cuối) và `reason`. Nhóm có thể chứa nhiều ID khi gộp/tách. `final: []` giải trình các mục bị loại. `A: []` và `B: []` cùng một ID cuối thể hiện mục C tìm thêm từ ảnh. Mỗi mục của A, B và bản cuối phải xuất hiện đúng một lần trên trang. Trang cả ba phiếu đều âm tính có thể để `decisions: []` và ghi lý do rà toàn trang. C khai báo danh tính người và thời điểm hoàn tất sau khi niêm phong, xác nhận đã đọc ảnh và giữ nguyên `ab_seal_sha256`.

```powershell
.venv/Scripts/python.exe -B -m benchmark.ground_truth_tools.formula_annotations export @common --seal scratch/nhan/seal.json --c scratch/nhan/C.json --output scratch/nhan/references.json
```

File `references.json` đi vào `formula_alignment --annotations`. Phần `custody` giữ hash A/B/C, seal và số nhóm giống, khác hoặc chỉ một bên tìm thấy. Kết quả kiểm khai báo của pilot dùng cho development. Xác minh người thật, việc làm độc lập và nội dung cần điều phối viên đối chiếu. Pilot giữ `NOT_EVALUATED` cho phát hành v7.0. [Bộ căn công thức](../scientific_evaluation/FORMULA_ALIGNMENT_V7.md).
