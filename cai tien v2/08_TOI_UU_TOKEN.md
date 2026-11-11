# Tối ưu lượng token khi làm việc với dự án

Kế thừa phần nạp theo tầng của [Cai Tien/02](09_LUU_TRU_CAI_TIEN_V7.md#ct-02). **Chưa có phép đo token nào** cho các cách làm dưới đây. Không ghi số token hay phần trăm tiết kiệm khi chưa đo (`NOT_MEASURED`); byte chỉ là chỉ báo kích thước. Trình `scripts/check_knowledge_map.py` từ chối các câu khẳng định số token chưa đo.

## 1. Nạp theo tầng, dừng sớm nhất có thể

| Tầng | Nguồn | Khi nào dừng |
| --- | --- | --- |
| 0 | Skill `ocr-pdf-knowledge-map` → `check_knowledge_map.py --summary` | Câu hỏi về trạng thái, tiến độ, tầng nào yếu |
| 1 | AGENTS + HANDOFF (CLAUDE nạp AGENTS tự động) | Bắt đầu phiên, cần ràng buộc vận hành |
| 2 | [PROJECT_MAP](../docs/development/PROJECT_MAP.md) hoặc `references/layers.md` của skill | Cần biết module và test nào |
| 3 | README module dưới `src/ocr_*/` | Cần hợp đồng của module |
| 4 | Mã: chỉ hàm, caller và test liên quan | Sửa hoặc kiểm hành vi |
| 5 | Dữ liệu lớn: chỉ qua script, chỉ trả số đếm và địa chỉ | Cần số liệu run cụ thể |

Ngân sách byte của từng tài liệu nằm ở `DOC_BUDGETS` trong `scripts/build_dev_context.py`. `--summary` in tổng số lỗi, cảnh báo và trạng thái STALE.

## 2. Thao tác đọc tiết kiệm

- **Xem cỡ trước khi đọc:** `wc -c <file>`, hoặc `git ls-files -s` để biết file có được Git theo dõi không.
- **Đọc heading trước:** `grep -n '^#' ARCHITECTURE.md`; với file lịch sử dùng `git show 08f7602:"<path>" | grep -n '^#'`. Sau đó đọc đúng đoạn bằng offset/limit.
- **Tìm đúng công cụ:** `git grep -n` cho file được theo dõi; thêm `--untracked` để thấy file chưa commit như `cai tien v2/`. Công cụ Grep (`rg`) **trả rỗng khi đường dẫn tìm là `docs`** do luật `/docs/*` trong `.gitignore`; tìm từ gốc repo hoặc từ `docs/development`, `docs/quality_assurance` thì vẫn thấy.
- **Không glob gốc repo:** `.venv*`, `output/`, `.cache/` rất lớn và làm lệnh timeout. Tìm trong `src/`, `benchmark/`, `tests/`, `docs/`, `scripts/`, `config/`.
- **Không nạp** PDF, JSON evidence, log, notebook, model hay `CLEANUP_REPORT.md` (61 KB) vào hội thoại. Muốn trích thì viết script in số đếm.
- **Tài liệu DOCX:** trích văn bản bằng `zipfile` (stdlib) vào `scratch/`, đọc heading trước.
- **Khám phá rộng giao cho subagent,** yêu cầu trả kết luận kèm đường dẫn, không trả nguyên văn file.

## 3. Viết tài liệu để lần sau đọc ít hơn

- **Mỗi thông tin một nơi chuẩn** ([07](07_PHUONG_PHAP_DU_AN_LON_AI.md) §6). Nơi khác chỉ đặt liên kết.
- **Trạng thái để trong registry JSON,** bảng trong Markdown sinh từ đó (`--render`). Không viết tay bảng trạng thái ở nhiều nơi.
- **Trích `đường_dẫn::ký_hiệu`, không trích số dòng.** Số dòng lệch ngay khi mã đổi.
- **HANDOFF chỉ ghi thay đổi, lệnh, kết quả, đường dẫn bằng chứng và bước kế tiếp.** Chi tiết đưa vào SESSION trong `scratch/`.
- **Tài liệu có ngày,** để người đọc biết khi nào cần kiểm lại.

## 4. Nếu muốn đo

1. Ghi số liệu của phiên bằng công cụ của client (ví dụ `/cost` hoặc skill `explain-usage`) vào mục chỉ số của SESSION ([mẫu](../docs/development/templates/SESSION.md)).
2. So sánh các phiên có cùng loại việc. Ghi rõ client, model và số phiên.
3. Chỉ khi đã có số đo mới viết kết luận kèm phạm vi. Trước đó mọi chỉ số giữ `NOT_MEASURED`.
