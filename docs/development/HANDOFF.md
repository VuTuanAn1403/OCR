# Bàn giao

Cập nhật 07/11/2026, Asia/Bangkok. Gốc `4852f53`; 08/11 đã commit lên main, chưa push. Working tree có test numeric guard do người dùng sửa trước phiên, được giữ nguyên. [Báo cáo dọn dẹp](../../CLEANUP_REPORT.md), [phiên](../../scratch/dev_sessions/20261106-project-cleanup/session.md).

QA-02 07/11: đã triển khai [Registry offline v1](../../benchmark/qa/README.md): import review, validate, revision append-only; giữ raw/source và hash evidence. [Phiên/bằng chứng](../../scratch/dev_sessions/20261107-qa-registry/session.md). 90 test chọn lọc pass; hồi quy CPU unit/scientific/legacy: 2290 pass/1 skip. Gói review lịch sử 40 mục/131 file được nhập và kiểm hash; vẫn NEEDS_REVIEW, không phải 40 lỗi xác nhận. [Sáu đặc tả QA](../quality_assurance/CURRENT_ARCHITECTURE.md) đã bỏ ignore. GT/quality NOT_EVALUATED; chưa chạy OCR/GPU. Audit trước và 152 test có phạm vi riêng ở [phiên audit](../../scratch/dev_sessions/20261107-qa-repository-audit/session.md).

08/11: CLAUDE.md nạp `@AGENTS.md`; AGENTS thêm node ID, import contracts, legacy `src/ocr`; 13 pass/16 contract ([run](../../scratch/runs/20261108-152658-95374b64/run.json)). Xóa `Cai Tien/` chưa commit (3 test cần template). Bỏ ignore `matchAt.js`; checkout sạch: 547 pass, 18 lỗi vì `Test case/` bị ignore ([run](../../scratch/runs/20261108-153425-7e563d34-clean-vendor-fix/run.json)).

## Phiên dọn dẹp hiện tại

- Xóa 789 file sinh tự động: 301 build, 483 bytecode có source, 5 metadata pytest; 6.291.651 byte file. Không xóa source/test/config/GT/model/evidence; .cache OCR/output/scratch lịch sử giữ nguyên. Manifest từng file và bản nén build cũ ở phiên.
- Trước sửa tài liệu, cả 815 file Git quản lý còn nguyên SHA; cuối phiên chỉ HANDOFF thay đổi có chủ đích và tạo CLEANUP_REPORT. Test người dùng SHA `20cd4a48…e020` nguyên byte. [Đối chiếu](../../scratch/dev_sessions/20261106-project-cleanup/final-preservation.json).
- Baseline 23 pass. Hồi quy CPU unit/scientific/legacy + keyword e2e: 2245 pass/1 skip, exit 0. [JUnit](../../scratch/runs/20261106-project-cleanup-regression/evidence/junit.xml). 16 import contracts đạt; cú pháp 587 file đạt.
- Build sdist → wheel v7.0 thành công từ bản sao scratch, 407 file gói khớp nguồn; import/CLI/keyword probe đạt. Wheel mới chỉ là artifact kiểm đóng gói CPU, chưa phát hành: [identity](../../scratch/dev_sessions/20261106-project-cleanup/build-elevated/build-verification.json). Không build Docker/chạy GPU/đo accuracy. Baseline/build đầu bị sandbox mode-0700; chạy lại quyền phù hợp ở output mới, không sửa ACL.

## Bằng chứng trước phiên: giữ nguyên, chưa đo lại

[HANDOFF nguyên byte trước dọn](../../scratch/dev_sessions/20261106-project-cleanup/handoff-before-cleanup.md) giữ đầy đủ kết luận, identity và link cũ; không coi chúng là phép đo checkout hiện tại. Các đầu mối tiếp tục:

- Global Alias: giữ v1 86/86; keywords SHA `63737b33…0b9800`; bản 88/87 nguyên byte ở keywords-v1-original.txt. CPU final `output/analysis_global_alias_final_20261106` có 9 PDF/938 trang, 165 literal/15 alias chấp nhận/3 loại trừ/5 Pending. [Phiên Alias/Kaggle](../../scratch/dev_sessions/20261106-alias-rules-kaggle/session.md). ZIP nguồn Kaggle cũ STALE sau sửa tài liệu, chưa chạy Kaggle thật/100–1.000 PDF.
- GAP-03: snapshot riêng 80 trang/10 PDF dẫn xuất, đủ coverage/frame; thiếu GT hướng/nội dung/ownership. DC-02 crop retry chỉ là diagnostic target-only, không GT độc lập. [Phiên](../../scratch/dev_sessions/20261106-retry-alias-rotation/session.md).
- DC-01: sáu VIC O2O còn sai, chỉ review/đề xuất, không đổi số. [Failure](../../scratch/dev_sessions/20261105-table-source-ownership/ppocr-probe-failure.json).
- TAB_05: bridge thêm frozen OCR sources, AGR/ASM có cải thiện placement; còn review, auto stitch chưa nối. [Phiên](../../scratch/dev_sessions/20261106-bridge-frozen-sources/session.md).
- TXT/MD numeric oracle và warm/resume đã có bằng chứng trước; giữ hai cache và mọi archive/output, không chạy thay thế. [Warm](../../scratch/dev_sessions/20261106-warm-resume-recheck/session.md).

## Giới hạn và bước kế tiếp

User xác nhận không có người A/B; không hỏi lại phân công, không dùng AI/protocol làm GT. Nhãn nhận dạng 0/38, keyword 0/12, L5 0/13, formula 0/3; workbook chỉ chuẩn tổng, formula bắt buộc, dung sai CDM duyệt 0,0005. GT/split/quyền/protocol/ngưỡng/renderer và official OmniDocBench còn thiếu; quality NOT_EVALUATED.

Mục tiêu QA-01–09 tạm dừng. QA-03 có mã paired/report và 117 test chọn lọc đạt theo [artifact](../../scratch/runs/20261107-qa-report-contracts/run.json). Probe DRAFT giữ `NOT_READY`. Kiểm CLI detector ngoài pytest và render dashboard còn mở. [Nghiên cứu báo cáo Word](../../scratch/dev_sessions/20261107-ocr-tech-docx-review/session.md) ghi các điểm cần khóa cho benchmark PP-OCRv6, gồm recipe ONNX, crop cố định và giới hạn frame detector. GT chỉ khóa khi đủ nguồn/nhãn/hồ sơ thật. Bằng chứng scratch/output bị ignore cần lưu kèm khi bàn giao.
