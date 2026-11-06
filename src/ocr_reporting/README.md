# ocr_reporting

Xuất workbook từng tài liệu/ma trận từ số đếm đã có; đọc lại và đối chiếu nội dung trước khi pipeline xác nhận publication.

- API: `workbooks.export_document`, `verify_document`, `matrix_bytes`, `verify_matrix`; `validation.validate_document_workbook`; `document_workbook.KeywordExporter` phục vụ legacy.
- Dependency: contracts/artifacts/keywords và openpyxl. Cài `python -m pip install -e ".[reporting]" pytest`.
- Test: `python -m pytest tests/unit/reporting -q -p no:cacheprovider`.
- Không tự đếm lại hoặc ghi SQLite. `FAILED_DOCUMENT`/pending giữ ô trống, không đổi thành số 0. So workbook bằng giá trị/cấu trúc, không byte XLSX có metadata ZIP biến thiên.
- Thay layout Excel không làm mất hiệu lực extraction; kiểm publication recovery ở `tests/unit/test_v63_pipeline.py` bằng môi trường app.
- Mỗi BCTC có `count_keywords.xlsx` đúng hai sheet: `Tong_hop` chứa `File_name` và 86 cột key, một dòng số đếm; `Trich_dan_chi_tiet` chứa STT/key/trang/ngữ cảnh, chữ khớp in đậm. Số 0 thật được giữ. Nguồn trang chưa rõ để trống kèm chú thích; bảng ghép ghi các trang nguồn cần review.
- Hành vi layout được chuyển từ [exporter GitHub tại commit b910247a](https://github.com/VuTuanAn1403/OCR_pdf/blob/b910247a83029d056178ddf15193f5e1698b5b9c/src/ocr/infrastructure/export/keyword_exporter.py). Report/metadata được ghi một lần để giữ rich text; đọc kiểm cả hai sheet, số đếm, trích dẫn, kiểu dữ liệu và chữ in đậm trước acknowledge. Workbook một sheet lịch sử vẫn được kiểm theo report lịch sử chưa có citation schema. Ma trận batch giữ layout riêng.

[Cài đặt, cách chạy và kiểm thử](../../README.md).
