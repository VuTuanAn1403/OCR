# Đo công thức TEXT và rà ký hiệu critical

`formula_content.py` đọc `cdm-pairs.json` do `formula_alignment` xuất. Khi truyền thêm `alignment.json`, bộ chấm kiểm hash của file cặp và đọc lại hai vế từ kết quả căn để phát hiện thay đổi. Báo cáo giữ PDF SHA-256, trang vật lý, ID và bbox tham chiếu, ID prediction hoặc ID span trong ô/block.

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
.venv/Scripts/python.exe -B -m benchmark.scientific_evaluation.formula_content `
  --pairs scratch/formula-alignment-moi/cdm-pairs.json `
  --alignment scratch/formula-alignment-moi/alignment.json `
  --output scratch/formula-content-moi
```

`--alignment` có thể bỏ qua khi chạy fixture trực tiếp. `--output` cần thư mục mới ngoài batch đã công bố. Có thể thêm `--critical-review <file.json>` khi đã rà. Lệnh hoàn thành báo cáo trả exit 0 kể cả khi một phần còn `NOT_EVALUATED`. Đọc trạng thái trong `formula-content.json` để biết phần nào có số đo.

## TEXT và CDM là hai phép đo nội dung riêng

Phép đo `formula-text-visible-strict-v1` đối chiếu ký tự Unicode theo `visible_strict_v1`. Nó đưa Unicode về NFC và thống nhất xuống dòng, giữ chữ hoa/thường, khoảng trắng, dấu, ngoặc, số 0 đầu và dạng chỉ số. Báo cáo có số thay thế, xóa, chèn, khớp, CER và cờ trùng khớp toàn chuỗi. Offset trong danh sách lỗi là chỉ số từ 0 trên chuỗi đã chuẩn hóa. File cặp gốc được ghim theo SHA-256.

- Tham chiếu TEXT có prediction TEXT hoặc thiếu prediction thuộc phạm vi chấm. Thiếu prediction được tính xóa toàn bộ ký tự tham chiếu.
- Tham chiếu TEXT nhưng prediction khác định dạng, tham chiếu rỗng, hoặc chuỗi vượt 2.048 ký tự được ghi `NOT_EVALUATED`. Khi còn ca như vậy, tỷ lệ exact và micro CER của toàn cohort TEXT để `null`. Bộ đếm của phần chấm được có trường riêng.
- Cặp LATEX tiếp tục dùng adapter CDM. Hai phương pháp xuất số đo riêng. `TEXT` so chuỗi nhìn thấy và không tự suy tương đương giữa TEXT, LaTeX và MathML. [Cách chạy CDM](FORMULA_CDM_V7.md).

## Hồ sơ người rà lỗi critical

Schema `ocr-formula-critical-review-v1` gồm `pairs_sha256`, `alignment_sha256` (null nếu dùng cặp trực tiếp), `reviewer`, `reviewed_at` có múi giờ và `pairs`. Mỗi mục trong `pairs` có `id` trùng file cặp và `categories` với đủ bảy khóa sau.

| Khóa | Phạm vi rà |
| --- | --- |
| `SIGN` | Dấu âm, dương, cộng trừ có nghĩa |
| `RELATION` | Dấu bằng, bất đẳng thức và hướng so sánh |
| `FRACTION` | Tử/mẫu, nhóm toán hạng và cấu trúc phân số |
| `INDEX_OR_EXPONENT` | Chỉ số, số mũ và vị trí tương đối |
| `NUMBER` | Chữ số, 0 đầu, vị trí phân tách, độ lớn |
| `UNIT` | Đơn vị, phần trăm, chữ hoa/thường |
| `EQUATION_LABEL` | Nhãn phương trình đi kèm |

Mỗi khóa có `status` là `MATCH`, `ERROR`, `NOT_APPLICABLE` hoặc `UNRESOLVED`, cùng `reason` mô tả căn cứ. Rà trên ảnh và đối chiếu hai vế. Tham chiếu đã có nhãn phương trình bắt buộc ghi trạng thái rà nhãn. Prediction vắng không nhận `MATCH`. Cặp chưa có dòng rà được tính `UNRESOLVED` ở cả bảy loại. Báo cáo đếm số **cặp có lỗi** theo loại, mỗi cặp tính tối đa một lần trong loại đó. Khi còn ca chưa xử lý, tỷ lệ lỗi của loại tương ứng giữ `null`. Điểm CDM hoặc TEXT exact không tự điền phiếu critical.

Thêm `--critical-template` khi có `--pairs` và `--alignment` để tạo `critical-template.json` trong output mới. Phiếu có nguồn từng cặp, giữ danh tính và khai báo trống, bảy nhóm đều `UNRESOLVED`. Với alignment holdout, bản nộp cần `status: SUBMITTED`, `actor_type: HUMAN`, `source_images_checked: true` và thời điểm rà đến thời điểm xử lý. Bản DRAFT, khai báo AI hoặc thiếu xác nhận xem ảnh bị từ chối.

Trạng thái `MEASURED_DECLARED_REVIEWS` cho biết file khai báo bao phủ mọi cặp và loại. Xác minh danh tính, tính độc lập và ngưỡng phát hành thuộc protocol nghiệm thu. [Phạm vi v7.0](../../cai%20tien%20v2/09_LUU_TRU_CAI_TIEN_V7.md#ct-11) · [Lệnh replay holdout](FORMULA_HOLDOUT_REPLAY_V7.md).
