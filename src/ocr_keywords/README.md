# ocr_keywords

Đếm literal, snapshot từ điển, report và kiểm nhóm artifact keyword. Không nạp OCR hoặc openpyxl; việc ghi Excel thuộc `ocr_reporting`.

- API: `counter.KeywordCounter`; `contract.dictionary_snapshot`, `count_report`, `validate_report`; `validation.validate_keyword_group`.
- Dependency: contracts/artifacts, pydantic và thư viện chuẩn. Cài `python -m pip install -e . pytest` từ gốc checkout.
- Test: `python -m pytest tests/unit/keywords -q -p no:cacheprovider`.
- Giữ nguyên `literal_v1`: NFC + casefold, đếm chuỗi con không chồng lấn trên Markdown đã xuất. Semantics mới cần policy/version mới và fixture tương thích.
- Mặc định v1 revision `2026-11-06`: 86 dòng/cụm đúng bảng người dùng; không có key độc lập `điện toán`. Bản 88/87 nguyên byte nằm ở `config/keywords-v1-original.txt` để đọc lại baseline; không có bộ v2 hoạt động.
- `citations.build_citations` dùng chính các occurrence literal trên toàn Markdown, giữ chữ khớp sau NFC và ngữ cảnh tối đa 10 từ mỗi phía. Chỉ gán trang khi bộ marker khớp phạm vi; bảng logic ghi tập trang nguồn, vị trí chưa xác định để trống. Analysis phải truyền thư mục extraction đã xác minh qua `citation_source_dir`; không lấy provenance từ đường dẫn bất kỳ.
- Thay keyword/reporting không được gọi OCR. Analysis chỉ nhận extraction đã kiểm receipt/provenance; không tự chứng thực nguồn bằng snapshot từ điển.
- Alias v2 bắt buộc hash PDF/Markdown/dictionary, policy, offset NFC và người duyệt. Mỗi occurrence chỉ đếm một quyết định mới nhất theo thời điểm có timezone; trùng ID khác nội dung hoặc trạng thái xung đột cùng thời điểm bị từ chối. Từ khóa khác nhau không chặn ứng viên của nhau; literal offsets được ánh xạ từ casefold về NFC.
- Bundle v2 có checksum kiểm nhất quán; analysis khóa toàn snapshot và hash byte nguồn trong `batch_config.json.alias_decisions`. Đổi bundle dùng output mới; thiếu file báo lỗi. Bundle v1 thiếu identity không tự nâng cấp: phải đối chiếu lại nguồn và xuất quyết định v2. Không sửa publication cũ.
- `global_rules.freeze_rules` kiểm schema v1, dictionary, NFC/casefold, alias cùng khung chữ và điều kiện literal cùng đoạn; gộp biến thể trùng, chặn accept/reject xung đột. Rules không sửa văn bản. Alias ngắn trong seed cần ngữ cảnh để không đếm “câu đối mới”/“ngọn đồi mới”.
- `tiered.build_tiered_report` giữ companion v2 khi không có global rules; khi có thì xuất v3 với accepted/rejected/Pending và provenance. Quyết định occurrence ưu tiên hơn rule. Chưa khớp rule giữ `NOT_EVALUATED`, bbox/trang chưa căn được giữ null/unresolved; không thay thiếu dữ liệu bằng 0. [Thiết kế và lệnh](../../cai%20tien%20v2/09_LUU_TRU_CAI_TIEN_V7.md#ct-14).

[Cài đặt, cách chạy và kiểm thử](../../README.md).
