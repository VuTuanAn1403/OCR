# ocr_document

Ghép trang, reading order/furniture, ID ổn định, Markdown/JSON và validation tài liệu. Không nạp recognition/layout/structure hoặc keyword/reporting.

- API: `export.DocumentExporter`, `validation.validate_document`; `page_assembly`, `reading_order`, `document_furniture`, `document_contracts`, `result_reader`.
- Cài `python -m pip install -e ".[app]" pytest` cho fixture export CPU.
- Test: `tests/unit/document`, `tests/unit/test_migration_v63_export_baseline.py`; fixture baseline ở `tests/fixtures/migration/v63_sample`.
- Renderer/processor mới nhận contracts và metadata nguồn, không điều khiển OCR. Đổi Markdown có thể đổi vector keyword, nên kiểm cả baseline chữ/số/nguồn/bbox và đếm khi cần.
- Đổi schema cần policy đọc/từ chối fixture cũ rõ ràng; không sửa receipt/output cũ để làm test qua.

Quy trình schema, cache và baseline: [hướng dẫn chung](../../docs/architecture/HUONG_DAN_PHAT_TRIEN_MODULE.md).
