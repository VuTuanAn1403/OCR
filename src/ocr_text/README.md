# ocr_text

Chuẩn hóa Unicode/làm sạch chữ và bảo vệ token số. Package chỉ dùng thư viện chuẩn; không phụ thuộc contracts, OCR hoặc reporting.

- API: `unicode_normalizer.UnicodeNormalizer`, `numeric_guard.protected_numeric_fragments`, `preserves_numeric_evidence`; `text_cleaner`.
- Test từ checkout: cài pytest, đặt `PYTHONPATH=src` rồi chạy `python -m pytest tests/unit/text -q -p no:cacheprovider`. Cài editable gốc sẽ thêm pydantic cho distribution, dù package này không dùng nó.
- Fixture phải giữ dấu tiếng Việt, dấu âm/phần trăm, ngày, mã và đơn vị. Không sửa số để hợp thức hóa output.
- Thuật toán chuẩn hóa keyword nằm riêng trong `ocr_keywords`: không thay thế bằng text cleaner mà làm đổi `literal_v1`.
- Guard giữ tiền tệ hai phía, dấu đứng trước tiền tệ, `%`/`‰` và ngoặc có khoảng trắng/NBSP. Vocabulary review bổ sung chuyển đổi số/đổi mới/an ninh mạng; chỉ gắn nghi vấn, không thay chữ theo từ điển. Kiểm bằng `tests/unit/text` và caller fallback.
- Guard giữ cách viết và thứ tự mã tiền tệ đứng riêng, bốn mã trong `TC_SCI_TXT_05` (`VNM`, `VCB`, `FPT`, `HPG`) và mã ba ký tự in hoa có nhãn như “Mã chứng khoán”. Khi retry đổi một mã được bảo vệ, hệ thống giữ dòng nguồn và đưa bất đồng vào review. Số và mã được bảo vệ theo bản đọc hiện có, còn độ đúng phải đối chiếu ảnh.

[Cài đặt, cách chạy và kiểm thử](../../README.md).

`numeric_guard.short_token_suspicions` chỉ báo nghi vấn O/0 theo ngữ cảnh, giữ offset trên chuỗi đầu vào (kể cả NFD). Mã dài, ngày/số có hậu tố và số `020` không có ngữ cảnh phù hợp không bị đổi. Guard bảo toàn số vẫn từ chối thay `020` thành `O2O`; cần ảnh và người rà cho quyết định sửa.
