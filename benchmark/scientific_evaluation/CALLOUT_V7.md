# Đo thử trích dẫn xen cột trong LAY_02

`callout_metric` dùng lại `extraction.json` và `document.json` từ batch canonical đã công bố. Bộ đo kiểm danh tính PDF, hash artifact, biên nhận và trạng thái công bố. Phép đo chỉ chạy trên CPU và thuộc tập development.

## Chuẩn bị vùng đối chiếu

Plan `ocr-callout-development-plan-v1` có `partition: development`, `reference_origin` và danh sách `windows`. Mỗi vùng ghi `id`, `document_id`, `pdf_sha256`, số trang vật lý `page` bắt đầu từ 1, `coordinate_space`, `transforms`, `width`, `height` và `window_bbox`. Dùng cùng hệ tọa độ với extraction. [Plan đối chứng âm](../../scratch/dev_sessions/20261105-pull-quote-source/negative-plan.json).

- `quote_regions` nhận danh sách vùng có `id` và `bbox` riêng. Dùng `[]` khi đã kiểm ảnh và xác nhận vùng không có trích dẫn xen cột. Dùng `null` khi chưa có nhãn.
- `body_reference` nhận `null` hoặc `path` tương đối với plan cùng `sha256` của bản chép UTF-8. Bản chép cần theo đúng thứ tự thân bài, bỏ trích dẫn và phân tách đoạn bằng hai ký tự xuống dòng. Chỉ truyền bản chép sau khi hai người đọc ảnh độc lập và hoàn tất phân xử. `DECLARED_HUMAN_ADJUDICATED` ghi nguồn do người lập plan khai báo. CLI kiểm byte, chưa xác minh danh tính người lập nhãn.
- Với ca rà phát triển, dùng `DEVELOPMENT_OBSERVATION` và để `body_reference: null`.

## Chạy trên publication đã lưu

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
.venv/Scripts/python.exe -m benchmark.scientific_evaluation.callout_metric `
  --plan scratch/dev_sessions/20261105-pull-quote-source/negative-plan.json `
  --batch output/operations_4pdf_warm_1_20261104 `
  --output scratch/callout_diagnostics_001.json
```

Dùng đường dẫn báo cáo mới ở ngoài batch. Bộ đo ghim hash plan, evaluator và publication. Một dòng nguồn được gắn vào vùng trích dẫn khi có ít nhất 80% diện tích bbox nằm trong đúng một vùng. Báo số vùng lọt vào thân bài, vùng thiếu đầu ra, vùng tách đúng theo các dòng quan sát được và số chunk tách nhầm. Nếu không có vùng dương tính, tỷ lệ chèn theo vùng GT để `null`.

CER lấy `text_corrected` từ chunk thân bài trong thứ tự `document.json`, nối bằng hai ký tự xuống dòng và dùng `visible_strict_v1`. Nếu nguồn chạm ranh giới, chunk chứa nguồn ngoài vùng hoặc không định vị được, bộ đo giữ kết quả liên quan ở `NOT_EVALUATED`. Không cắt chữ từ chunk để tiếp tục chấm. Thiếu bản chép hoặc vượt giới hạn 10 triệu ô tính CER cũng giữ `null`. Một vùng tách đúng theo nguồn quan sát chưa chứng minh đã nhận đủ ký tự trên ảnh. Báo cáo development luôn giữ nghiệm thu `NOT_EVALUATED`.
