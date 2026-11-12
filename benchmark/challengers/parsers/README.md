# Parser đối chứng (V8-095)

Mục đích: so một parser tài liệu ngoài (Marker hoặc tương đương) với production, **chỉ trên những trang đã có giả thuyết lỗi**. Parser này không thay production. Kết quả chỉ dùng để chọn trang cần gán nhãn và để kiểm một giả thuyết đã nêu trước khi chạy.

Trạng thái 12/11/2026: phần chuẩn bị đã xong, chưa chạy. Catalog `../model_catalog.json` chưa có ứng viên parser nào được ghim revision và sha weights. Vì vậy `catalog.download_allowed` từ chối tải. Người dùng cần chọn parser, kiểm licence, rồi ghim revision và sha trước khi tác nhân được tải.

## Trang được chạy (chọn trước khi xem kết quả)

Mỗi trang phải thuộc ít nhất một giả thuyết sau. Danh sách được tạo tất định từ output production đã khóa:

| Giả thuyết | Nguồn chọn trang |
| --- | --- |
| Thứ tự đọc sai ở trang nhiều cột | `scratch/v8/v8_071_reading_order_003_r3_20261110.json`, các trang có đồng thuận cặp < 0,9 (156 trang) |
| Bảng heuristic chồng lên bảng Docling, hoặc ô số không truy được nguồn | báo cáo `scripts/audit_runtime_invariants.py` của output ứng viên |
| Trang có chẩn đoán lỗi chữ | `scratch/v8/v8_090_vlm_selection_003_20261110.json` (137 trang, `vlm-page-selection-v1`) |

## Hợp đồng đầu ra

- Bản ghi theo `../canonical.py` (`ocr-v8-challenger-prediction-v1`), lớp `page_text`, `reading_order` hoặc `table`.
- Mỗi bản ghi giữ `text_raw` nguyên văn của parser, `bbox` cùng `coordinate_space`, và `source_image_sha256`.
- Trang lỗi thành `MISSING_OUTPUT` và vẫn tính vào mẫu số.
- Manifest theo `../experiment.py`, với ID `EXP-V8-PARSE-YYYYMMDD-NNN`. Thiếu trường identity thì kết quả là `INCONCLUSIVE`.
- Thư mục: `scratch/benchmarks/<experiment>/{manifests,predictions,scorecards,errors,logs}`.

## Đo

- Thứ tự đọc: `benchmark/scientific_evaluation/reading_order_metric.py`, gồm pair accuracy và missing/duplicate node, trên trang có GT thứ tự đọc.
- Bảng: `benchmark/scientific_evaluation/teds_metric.py` và numeric cell exact theo địa chỉ ô, trên bảng có GT.
- Chưa có GT thì chỉ báo mức đồng thuận với production. Đồng thuận không phải accuracy, và quyết định duy nhất được phép là `INCONCLUSIVE`.

## Ràng buộc

- Cài parser vào venv riêng, không vào `.venv` hoặc `.venv-v62/*`.
- Không chạy khi batch OCR đang dùng GPU.
- Không ghi đè output production. Không gộp chữ của parser vào `result.md`.
