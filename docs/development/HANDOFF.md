# Bàn giao

Cập nhật 14/11/2026, Asia/Bangkok. Nhánh `v8-diacritic-bounds-keyword-challenger`, HEAD `a8c01b1`, [PR #1](https://github.com/VuTuanAn1403/OCR/pull/1). Khóa baseline `BASELINE-V8-20261113-001`, output dev `v8_006_arena1536_20261112`. Đọc trạng thái bằng `scripts/check_knowledge_map.py --summary`. Phạm vi phát hành và các cổng ở [bàn giao chi tiết](BAN_GIAO_CHI_TIET_20261113.md). Lệnh và bằng chứng phiên ở [nhật ký tiếp quản](../../scratch/dev_sessions/20261113-codex-takeover/session.md).

## Quyết định của người duyệt

- Q1–Q10 theo [gói duyệt](../../cai%20tien%20v2/bao_cao/GOI_DUYET_V8_20261113.md). Baseline 006, chưa PROMOTE. ×2 đo so cặp trên 6 PDF holdout, Vintern giữ baseline. Q6 B/Q7 A thêm cột chờ duyệt dòng bị loại và O/0. Q8 cho phép OmniDocBench nội bộ. Q9 đã ghim và đo 3 ứng viên REC.
- Q11 giữ cổng dấu 99,99% và báo đúng PASS/FAIL. Q12 chọn VietOCR `vgg_transformer` trước. Q13 chưa cần nâng ngân sách. Q14 chờ kết quả giai đoạn 1 để duyệt push.

## Đã kiểm và đang chạy

- Holdout h01 đủ **6 PDF, 468 trang**, `MATCH` khóa 001 theo runtime, audit `NEEDS_REVIEW` 6/6. h02 ×2 khóa 002 báo thành công **5/6** lúc 01:05 ngày 14/11, tiến trình còn chạy. Q10 B cho chạy so cặp trước khi đủ slot theo protocol §7.3 mục 5. Đo sau khi seal đủ phiếu và khóa đo được duyệt. Cổng dấu `NOT_EVALUATED`. [Log h02](../../scratch/dev_sessions/20261113-codex-takeover/h02_batch.log) · [audit h01](../../scratch/dev_sessions/20261113-codex-takeover/h01_audit.json) · [identity h01](../../scratch/dev_sessions/20261113-codex-takeover/h01_identity.json) · [exposure](../../scratch/dev_sessions/20261113-codex-takeover/holdout-operations.json).
- R1 `DONE`, P7 chờ GT. Cập nhật [PROJECT_MAP](PROJECT_MAP.md), registry và bằng chứng backlog, đồng bộ hash nguồn Word. `check_knowledge_map.py --check --require-fresh` đạt, 51 test bản đồ/ngữ cảnh/Word đạt. [Nhật ký](../../scratch/dev_sessions/20261114-project-map-refresh/session.md) · [kiểm bản đồ](../../scratch/dev_sessions/20261114-project-map-refresh/map-verified.json) · [test](../../scratch/runs/20261114-010457-671d35e9/run.json).
- Đã thêm kiểm baseline trên input mới và phiếu đối chiếu keyword literal/pending sau khi có GT. OmniDocBench đã chuẩn bị 1.660 nhãn display trên 223 trang, CDM render đủ 3 ca đối chứng có/không có số phương trình. Điểm công thức chờ OCR. TEXT CER và inline thiếu nhãn phù hợp. [Công cụ tiếp quản](TAKEOVER_TOOLS.md).
- VietOCR `vgg_transformer` ở worktree `C:\Users\ASUS\.codex\worktrees\v8-vietocr-transformer\OCR_pdf` (`480285b`). Test sát thay đổi 230 đạt, preflight CPU xác minh ba file model. Chờ GPU để smoke rồi chạy 9 PDF dev.
- Q6/Q7 ở `v8-integration-keyword-pending` (`3d44756`). Phân tích lại từ 006 trong worktree riêng đạt 9/9, giữ số đếm baseline, thêm 6 ứng viên O/0 và 1 occurrence dòng bị loại. Merge sau h02 và audit. [Báo cáo Excel/SQLite](../../scratch/dev_sessions/20261113-codex-takeover/keyword_analysis_r2_audit.json).

## Công việc cần người duyệt

1. [Sàng lọc 6 PDF holdout](http://127.0.0.1:8769/) rồi báo để chạy chuỗi seal. Thêm PDF born-digital từ công ty mới, ghi manifest trước OCR. Hiện 163.662 slot ứng viên, ρ_U dev khoảng 0,025. Tính lại cỡ mẫu sau phân xử.
2. [Phân xử dấu](http://127.0.0.1:8767/v8_011_dev_006_v8_20261113/), nạp `migrated-d613bd4747c8289f.jsonl` rồi chấm 4.474 mục còn lại. Bộ kiểm lại mù 1.552 mục sàng lọc dev ở `scratch/v8/screening/recheck/`, làm từ 17/11.
3. [GT cấu trúc](http://127.0.0.1:8768/) theo 4 lô, chọn ngưỡng khi export. Chọn phạm vi GT keyword và dùng quy trình A/B/C. Các link local dùng `scripts/serve_review_sheets.py` để lưu quyết định xuống đĩa.

`scripts/run_v8_evidence_chain.py` báo tiến độ và chạy các bước tất định sau khi có quyết định. Bản thảo bài báo chờ GT độc lập. [Nhật ký gói duyệt](../../scratch/dev_sessions/20261113-v8-review-package/session.md) · [exit gates](../../scratch/dev_sessions/20261113-v8-exit-gates-cho/session.md) · [bản thảo](../../research_notes/BAI_BAO_OCR_PDF.md).
