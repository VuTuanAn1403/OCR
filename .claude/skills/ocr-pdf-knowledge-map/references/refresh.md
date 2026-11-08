# Cập nhật bản đồ kiến thức

Nguồn trạng thái duy nhất là `cai tien v2/10_TRANG_THAI_V8.json`. Bảng trong 02 và 03 được sinh từ đó. Skill không chứa trạng thái nên thường không phải sửa.

## Khi nào cập nhật

- Một mục backlog đổi trạng thái: TODO → IN_PROGRESS → DONE, BLOCKED hoặc REJECTED.
- Mã đổi làm một tầng hay gap đổi năng lực, ví dụ thêm adapter, sửa metric.
- Có phép đo chất lượng trên GT độc lập. Chỉ khi đó mới được đổi `quality`, và phải kèm `gt_evidence` cùng `gt_source_kind`.
- HEAD mới mà `--summary` báo STALE, và bạn đã kiểm lại các evidence bị đổi.

## Các bước

1. **Sửa registry.** Mỗi evidence có `path`, `symbol` (nếu là mã) và `label`. Evidence nằm ở thư mục bị Git bỏ qua thì thêm `"local_only": true`. Gap `MISSING` phải ghi `searched` là lệnh tìm đã chạy.
2. **Sửa backlog** `cai tien v2/06_BACKLOG_V8.csv` (UTF-8 có BOM). ID có dạng `V8-NNN` và không được dùng lại. Đường dẫn chưa tồn tại thì ghi `planned:`. Mục `DONE` phải có cột `evidence`.
3. **Sinh lại bảng và kiểm:**

   ```bash
   .venv/Scripts/python.exe -B scripts/check_knowledge_map.py --render
   .venv/Scripts/python.exe -B scripts/check_knowledge_map.py --check
   ```

   `--check` phải exit 0. STALE chỉ là cảnh báo; thêm `--require-fresh` nếu muốn chặn cả STALE.
4. **Đổi mốc:** khi đã kiểm trên HEAD mới, cập nhật `verified_head` (40 ký tự), `last_verified` và `verified_scope`.
5. **Xuất lại Word:** nếu nội dung 00–09 đổi, xuất lại DOCX rồi cập nhật sha trong `exports[]`. Nếu bỏ qua bước này, `--check` sẽ báo STALE.
6. **Thêm file mới** vào `cai tien v2/` hoặc vào skill thì thêm mục ngân sách byte vào `DOC_BUDGETS` trong `scripts/build_dev_context.py`.
7. **Chạy test của trình kiểm:**

   ```bash
   .venv/Scripts/python.exe scripts/run_pytest_scratch.py tests/unit/test_check_knowledge_map.py tests/unit/test_build_dev_context.py -q --capture=fd
   ```

8. **Ghi HANDOFF:** thay đổi, lệnh, kết quả, đường dẫn bằng chứng.

## Trình kiểm chặn gì

- Enum sai.
- Năng lực không có evidence.
- Đường dẫn sai hoa/thường, hoặc bị Git bỏ qua.
- Ký hiệu không còn trong mã.
- Liên kết gãy, kể cả liên kết vào `Cai Tien/` đã xóa.
- Backlog trùng ID hoặc `blocked_by` trỏ tới ID không có.
- Bảng 02/03 lệch registry.
- Câu khẳng định số token chưa đo.
- Số dòng `.py:NNN` trong skill hoặc registry.
- Frontmatter skill sai.
- Lệch phiên bản với `version.py`.
- File vượt ngân sách byte.
