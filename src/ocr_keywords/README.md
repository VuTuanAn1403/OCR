# ocr_keywords

Đếm literal, snapshot từ điển, report và kiểm nhóm artifact keyword. Không nạp OCR hoặc openpyxl; việc ghi Excel thuộc `ocr_reporting`.

- API: `counter.KeywordCounter`; `contract.dictionary_snapshot`, `count_report`, `validate_report`; `validation.validate_keyword_group`.
- Dependency: contracts/artifacts, pydantic và thư viện chuẩn. Cài `python -m pip install -e . pytest` từ gốc checkout.
- Test: `python -m pytest tests/unit/keywords -q -p no:cacheprovider`.
- Giữ nguyên `literal_v1`: NFC + casefold, đếm chuỗi con không chồng lấn trên Markdown đã xuất. Semantics mới cần policy/version mới và fixture tương thích.
- Thay keyword/reporting không được gọi OCR. Analysis chỉ nhận extraction đã kiểm receipt/provenance; không tự chứng thực nguồn bằng snapshot từ điển.

Quy trình fixture, schema, closure/cache và CI: [hướng dẫn chung](../../docs/architecture/HUONG_DAN_PHAT_TRIEN_MODULE.md).
