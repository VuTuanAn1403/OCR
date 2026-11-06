# Chấm độ bền trước biến dạng ảnh

`degradation_corpus` chuẩn bị ảnh và PDF chỉ chứa ảnh cho `TC_SCI_DEG_01/02/03` và BK-04. `degradation_metric` đọc các bản chép đã căn theo nguồn và tính điểm CPU. Hai công cụ tách bước tạo dữ liệu khỏi lượt inference và nghiệm thu.

## Tạo corpus phát triển

Dùng plan `paired-degradation-render-plan-v1` với `partition: development`, DPI, seed, danh sách `sources` gồm ID, đường dẫn PDF tương đối, SHA-256, số trang vật lý và `conditions` dùng cùng hợp đồng với bộ chấm. Khóa nguồn trước prediction. Tạo output mới ngoài cây PDF và batch. [Plan đã chạy](../../scratch/dev_sessions/20261105-degradation-corpus/final-plan.json).

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
.venv/Scripts/python.exe -B -m benchmark.scientific_evaluation.degradation_corpus `
  --plan scratch/degradation-plan.json --pdf-root inputs --output scratch/degradation-corpus-new
```

`manifest.json` ghim plan, mã, runtime, ảnh nguồn, ảnh biến dạng, PDF và mẫu input chấm. PDF dẫn xuất có một trang, một ảnh thang xám với byte pixel khớp PNG, kiểm lại khi xuất. Mỗi đơn vị có cùng khổ ảnh giữa các điều kiện. Canvas đủ chứa bốn góc của ảnh nguồn sau xoay. Ảnh control chỉ thêm nền trắng quanh ảnh gốc. Góc dương xoay ngược kim đồng hồ, dùng bicubic và ghi affine từ pixel đích về nguồn.

Tương phản dùng `round(255 − level × (255 − luma))`. Nhiễu muối tiêu chọn pixel duy nhất theo seed, gán đen và trắng, ghi cả tỷ lệ chọn lẫn số pixel đổi thực tế. Vết ố dùng đa giác với biên làm mềm, độ đậm cố định và seed. Mức `stain` là tỷ lệ diện tích danh nghĩa của đĩa dùng để định kích thước, manifest ghi tỷ lệ đa giác thực. Các mức phát triển cần duyệt lại trước holdout.

Pilot ngày 05/11 dùng AAA trang vật lý 196, ABT 23 và ASM 130, DPI 180. Có control, nghiêng 2°/5°/10°, tương phản 75%/50%/25%, nhiễu 0,4% và vết ố danh nghĩa 2%. Hai lượt tạo cho 59 file khớp byte, gồm 27 cặp PNG/PDF. Trang AAA 197 bị loại khi xem ảnh vì chữ quay ngang dù metadata không báo xoay. [Corpus](../../scratch/dev_sessions/20261105-degradation-corpus/final-corpus/manifest.json) · [Kiểm tra](../../scratch/dev_sessions/20261105-degradation-corpus/final-corpus-verification.json).

## Chuẩn bị dữ liệu

1. Khóa danh sách đơn vị từ ảnh thẳng trước khi xem prediction. Mỗi ID cần truy được PDF SHA256, trang vật lý và vùng nếu chấm crop. Giữ cùng phạm vi chữ ở mọi điều kiện, kể cả nguồn không có đầu ra. Không chọn lại vùng theo các dòng detector tìm được.
2. Hai người đọc ảnh nguồn độc lập, rồi phân xử. Lưu bản A/B, ảnh, quyết định, hash và protocol. Chỉ đưa transcript đã phân xử vào `references`. Native text, OCR hoặc nhãn AI sơ bộ không tự trở thành GT. Những trang đã dùng phát triển giữ trong development.
3. Lưu ảnh control và ảnh biến dạng, recipe/seed, renderer/DPI, transform, padding/crop, model/config/code/runtime và receipt dự đoán. Dùng cùng hệ thống trên mọi điều kiện. Nếu xoay làm mất mép chữ, không bỏ phần chữ đó khỏi GT để tăng điểm. Ghi riêng dữ liệu scan xuống cấp tự nhiên và biến dạng chủ động.
4. Tạo một file chữ UTF-8 cho mỗi reference và prediction đã căn. Nếu bắt đầu từ Markdown/HTML, khóa phép chiếu văn bản và ánh xạ nguồn trước khi chấm. Không đưa trực tiếp markup vào bộ chấm chữ. Mỗi descriptor chứa `path` và `sha256` của byte file thật; đường dẫn tương đối tính từ JSON đầu vào.

Schema `paired-degradation-input-v1` có năm trường dữ liệu:

| Trường | Hợp đồng |
| --- | --- |
| `expected_ids` | Danh sách ID nguồn duy nhất, cố định cho mọi điều kiện |
| `conditions` | Danh sách `{id, kind, level}`; đúng một control và ít nhất một biến dạng |
| `references` | Map ID nguồn → descriptor file chữ hoặc null khi chưa có nhãn |
| `predictions` | Map ID điều kiện → map ID nguồn → descriptor file chữ hoặc null khi thiếu output |
| `schema_version` | `paired-degradation-input-v1` |

Descriptor có dạng `{"path": "labels/p1.txt", "sha256": "<64 ký tự SHA256 thực>"}`. Đây là mô tả cấu trúc; phải thay giá trị hash bằng số tính từ file, không dùng chuỗi ví dụ làm input.

`kind=control` có level 0. `skew` dùng góc có dấu tính bằng độ, trong khoảng −45 đến 45 và khác 0. `contrast` dùng hệ số từ 0 đến dưới 1, ví dụ 0,5 cho 50%. `salt_pepper` dùng tỷ lệ pixel bị nhiễu, `stain` dùng tỷ lệ diện tích vết ố, đều lớn hơn 0 và không quá 1. Recipe phải định nghĩa cụ thể phép biến đổi; cùng hệ số có thể cho ảnh khác nhau khi dùng thuật toán khác. Không có mặc định đã duyệt cho mật độ nhiễu hoặc vết ố.

## Ghép publication canonical

`degradation_predictions` kiểm manifest corpus theo SHA-256 đã khóa, ảnh, PDF dẫn xuất và mẫu input. Mỗi điều kiện nhận một hoặc nhiều batch đã được SQLite acknowledge. Các PDF trong batch phải giữ tên file theo ID đơn vị, đúng hash theo điều kiện và có đúng một trang. Dùng batch riêng giữa các điều kiện để các PDF có cùng stem vẫn được phân biệt. Adapter đối chiếu cấu hình ngoài đường dẫn input, danh tính export và GPU giữa các batch.

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
.venv/Scripts/python.exe -B -m benchmark.scientific_evaluation.degradation_predictions `
  --manifest scratch/degradation-corpus-new/manifest.json `
  --manifest-sha256 <sha256-da-khoa> `
  --batch control=output/deg-control `
  --batch skew-05=output/deg-skew-05 `
  --output scratch/degradation-intake-001
```

Lặp `--batch` cho mọi điều kiện đã có publication. Có thể bỏ cờ này để kiểm corpus và liệt kê phần đang chờ. Exit 1 ghi `intake.json` với từng ID còn thiếu và giữ `score_input: null`. Trạng thái này dành cho PDF chưa có publication. Exit 2 từ chối corpus hoặc publication sai danh tính. Adapter chỉ đọc batch, không gọi OCR.

Khi mọi PDF đã công bố, exit 0 ghi `score-input.json` cùng file chữ và hash. Projection lấy trang vật lý 1 của `result.md` theo `visible_strict_v1`, bỏ lời dẫn do exporter tạo trước marker và giữ nội dung trang theo bộ chiếu Markdown hiện hành. Marker thiếu, trùng hoặc không thuộc trang 1 bị từ chối. Gói này áp dụng cho cả trang, với transcript cùng phạm vi. Ghi hash bộ chiếu và thông tin publication trong `intake.json`.

Sau phân xử, có thể truyền `--references <manifest.json>` dùng schema `paired-degradation-references-v1`. Manifest ghi `corpus_sha256`, `reference_origin: DECLARED_HUMAN_ADJUDICATED` và `references` ánh xạ đủ ID sang descriptor tương đối với manifest hoặc null. Giữ hồ sơ ảnh, A/B và phân xử kèm theo. Adapter chỉ kiểm khai báo và byte file. Thiếu manifest hoặc transcript thì để nhãn null. Khi nhận thêm nhãn, dùng output intake mới.

## Chạy và đọc báo cáo

```powershell
.\.venv\Scripts\python.exe -B -m benchmark.scientific_evaluation.degradation_metric `
  scratch/degradation-input.json --output scratch/degradation-report-new.json
```

Output phải là file mới. CLI kiểm hash file chữ trước và sau khi chấm, ghim hash JSON cùng hai file mã evaluator. Nó giữ file nguồn, chữ hoa/thường, dấu, số, khoảng trắng và dấu câu. Policy `visible_strict_v1` chỉ chuẩn hóa NFC và kiểu xuống dòng. JSON trùng key, kiểu sai, mức không hữu hạn, điều kiện trùng hoặc hash lệch bị từ chối.

Mỗi điểm có S/D/I/H, độ dài reference/prediction, CER micro, trung bình CER của các đơn vị có reference khác rỗng và tỷ lệ insertion. Mẫu số CER micro là tổng ký tự reference, gồm mọi đơn vị đã khóa; insertion trên nguồn xác nhận rỗng vẫn vào tử số. Thiếu prediction được chấm như chuỗi rỗng, ghi `MISSING_OUTPUT` và tính deletion. Thiếu reference giữ `NOT_EVALUATED`; counts của phần có nhãn chỉ nằm ở `observed_counts`, các điểm tổng hợp giữ null. ID ngoài phạm vi cũng ngăn tính điểm tổng hợp.

`cer_delta_from_control = CER_biến_dạng − CER_control`. Riêng góc nghiêng, `cer_delta_per_abs_degree` chia hiệu số này cho trị tuyệt đối góc. Đây là độ dốc giữa hai điểm control/biến dạng, không phải hệ số hồi quy trên toàn đường cong. Hiệu số giữ dấu âm nếu đầu ra cải thiện. CER không bị chặn ở 1. Tỷ lệ insertion là I/N ký tự GT, báo cùng hiệu số so control; các số này chưa chứng minh nguyên nhân của lỗi.

Reference rỗng được xác nhận khác với reference null. Khi toàn bộ GT rỗng, counts insertion vẫn có nhưng CER, insertion rate và slope đều null. `EVALUATED` chỉ có nghĩa tính được counts theo phạm vi khai báo, kể cả khi rate không có mẫu số. Exit 0 báo trạng thái này; exit 1 báo thiếu dữ liệu/phạm vi, exit 2 báo lỗi hợp đồng hoặc file. Không diễn giải exit 0 thành PASS độ chính xác.

## Điều kiện còn thiếu để nghiệm thu

Corpus phát triển đã có ảnh, recipe và bộ ghép publication. Audit corpus ghi 0/27 publication dẫn xuất được cung cấp và chưa nhận nhãn. Dùng intake mới khi đã có bằng chứng. Hồ sơ nghiệm thu còn cần quyền dùng, hai người gán nhãn, protocol và số đo theo tập đã khóa. [Audit intake](../../scratch/dev_sessions/20261105-degradation-predictions/actual-pending-final/intake.json).

Ca góc nghiêng cần đủ 2°, 5°, 10° và control; ca tương phản cần điểm 50%; ca nhiễu cần mức/recipe đã duyệt. Ngưỡng trong ma trận là đề xuất cần khóa trước đo. Cần paired theo đơn vị nguồn, counts, phân tầng và CI theo cụm phù hợp. Khi chưa có nhãn độc lập và prediction tương ứng, chỉ xác minh corpus và bộ chấm. Nghiệm thu vẫn chưa đánh giá.
