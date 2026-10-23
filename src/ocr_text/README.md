# ocr_text

Chuẩn hóa Unicode/làm sạch chữ và bảo vệ token số. Package chỉ dùng thư viện chuẩn; không phụ thuộc contracts, OCR hoặc reporting.

- API: `unicode_normalizer.UnicodeNormalizer`, `numeric_guard.protected_numeric_fragments`, `preserves_numeric_evidence`; `text_cleaner`.
- Test từ checkout: cài pytest, đặt `PYTHONPATH=src` rồi chạy `python -m pytest tests/unit/text -q -p no:cacheprovider`. Cài editable gốc sẽ thêm pydantic cho distribution, dù package này không dùng nó.
- Fixture phải giữ dấu tiếng Việt, dấu âm/phần trăm, ngày, mã và đơn vị. Không sửa số để hợp thức hóa output.
- Thuật toán chuẩn hóa keyword nằm riêng trong `ocr_keywords`: không thay thế bằng text cleaner mà làm đổi `literal_v1`.

Quy trình schema/fingerprint và CI: [hướng dẫn chung](../../docs/architecture/HUONG_DAN_PHAT_TRIEN_MODULE.md).
