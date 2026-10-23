# ocr_reporting

Xuất workbook từng tài liệu/ma trận từ số đếm đã có; đọc lại và đối chiếu nội dung trước khi pipeline xác nhận publication.

- API: `workbooks.export_document`, `verify_document`, `matrix_bytes`, `verify_matrix`; `validation.validate_document_workbook`; `document_workbook.KeywordExporter` phục vụ legacy.
- Dependency: contracts/artifacts/keywords và openpyxl. Cài `python -m pip install -e ".[reporting]" pytest`.
- Test: `python -m pytest tests/unit/reporting -q -p no:cacheprovider`.
- Không tự đếm lại hoặc ghi SQLite. `FAILED_DOCUMENT`/pending giữ ô trống, không đổi thành số 0. So workbook bằng giá trị/cấu trúc, không byte XLSX có metadata ZIP biến thiên.
- Thay layout Excel không làm mất hiệu lực extraction; kiểm publication recovery ở `tests/unit/test_v63_pipeline.py` bằng môi trường app.

[Cài đặt, cách chạy và kiểm thử](../../README.md).
