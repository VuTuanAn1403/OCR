# Bàn giao

Cập nhật 13/11/2026 23:30, Asia/Bangkok. Nhánh `v8-diacritic-bounds-keyword-challenger`, PR [#1](https://github.com/VuTuanAn1403/OCR/pull/1), chưa push. Khóa hiện hành `BASELINE-V8-20261113-001` (output `v8_006_arena1536_20261112`). Trạng thái: `scripts/check_knowledge_map.py --summary`. [Gói duyệt Q1–Q10](../../cai%20tien%20v2/bao_cao/GOI_DUYET_V8_20261113.md).

## 13/11 tối — người duyệt trả lời Q1–Q10

- Quyết định: baseline 006; chưa PROMOTE, chưa nâng 8.0.0 (Q2 B); ×2 đo holdout; Vintern giữ baseline; tải OmniDocBench (đo nội bộ) và 3 ứng viên REC; holdout so cặp trên 6 PDF kèm ghi độ lệch §7.3 mục 5, và bổ sung PDF.
- **Q6 B, Q7 A** (đổi `src/`, worktree `C:\kk_2\OCR_pdf_wt_v8int`, nhánh `v8-integration-keyword-pending`, chưa merge): `src/ocr_keywords/review_evidence.py` thêm vào `keyword_two_tier.json` ứng viên `020`↔`O2O` và keyword trong dòng bị A1 loại. Excel thêm sheet `Cho_duyet_dong_bi_loai`, `Ung_vien_chu_so`; không cộng vào `Tong_sau_duyet`. Trên 006: VIC 6 ứng viên, 1 keyword (`Số hóa` tr.95); mọi khóa cũ không đổi. Merge sau khi batch GPU holdout xong (identity).
- **Tự động hóa:** `scripts/run_v8_evidence_chain.py` báo tiến độ các phiếu. Với `--run`, nó seal phiếu sàng lọc/phân xử đã có quyết định và chấm GT đã export. Bước cần người duyệt (ngưỡng export, khóa đo holdout) chỉ in lệnh.
- Phiên "OCR PDF v8 exit gates": OCR holdout, Q9 (`5de92d0`), Q8.

## 13/11 — ƣ→ư, holdout, gói duyệt

- **V8-011:** khóa đo v8 (`a474cf1`) đọc `ƣ`/`Ƣ` thành `ư`/`Ư` (chỉ ASM có). Dev 006: 13.777/346.393. Phiếu v8 `scratch/v8/adjudication/v8_011_dev_006_v8_20261113/` nhận 5.011 quyết định từ v7 (`959c003`); còn 4.474 mục.
- **Holdout:** 13 PDF khóa; BCE, BHN 2022 trùng byte `inputs/` nên bị loại. 6 PDF cần sàng lọc (`scratch/v8/holdout/screening/`, cấu hình `holdout-screening-sheets`), 163.662 slot. Cổng cần ρ_U ≤ 0,0046, dev đo khoảng 0,025: thiếu slot. Chưa chạy OCR (protocol §7.3 mục 5).
- **V8-100:** challenger `benchmark/challengers/keyword_confusables.py` (`O2O` đọc thành `020`). Trên 718 trang dev, tham chiếu text layer: thiếu 28 → 14 nếu nhận mọi ứng viên chờ duyệt, 0 ứng viên confusable sai.
- **V8-065:** 6 ứng viên đọc tiếng Việt vào `model_catalog.json`, cổng tải đóng. **V8-085:** OmniDocBench đủ tiêu chí nhưng licence chỉ nghiên cứu (Q8).
- Hai phiên chạy song song. Phiên "OCR PDF v8 exit gates" chạy thử chấm 4 lô bằng nhãn tổng hợp, không phải GT: export 4/4, chấm 10/10, delta 7/7 (`scratch/v8/review_packages/scoring_dryrun_20261113/README.md`). Nhật ký: [gói duyệt](../../scratch/dev_sessions/20261113-v8-review-package/session.md), [exit gates và báo cáo CHỜ](../../scratch/dev_sessions/20261113-v8-exit-gates-cho/session.md).

## 12/11 (tóm tắt)

- Batch 004: giữ dòng A1 bị loại (`rejected_ocr_lines`); ô heuristic mang bbox dòng nguồn; bảng model nhận dòng chồng bảng heuristic. Dòng mất 3.652→0, ô số không truy được 292→2. [Hồ sơ candidate](../../cai%20tien%20v2/bao_cao/CANDIDATE_SELECTION_DOSSIER.md).
- ×2 (V8-050): dev DSER 13.751→11.647; 1.781 sửa / 306 sai; keyword 3/0. Vintern: đề xuất KEEP BASELINE. V8-095 `DONE`.
- Crop cố định 3.000 dòng (`scratch/v8/recognition_crops/v8_065_dev_004_3000_20261112/`): `upscale2` 132 sửa / 13 sai; V8-030 16 / 0.

## Phát hiện còn mở

- **Chỉ mở phiếu qua `scripts/serve_review_sheets.py`.** Khung trình duyệt của app làm mất localStorage.
- Ô rỗng của bảng ảnh mang bbox cấp bảng, nên audit báo 45 số "vắng"; không mất chữ.
- `verified_head` còn ở `bcb5be4` cho đến khi chạy xong hồi quy trên HEAD mới.

## Bước kế tiếp (cần người dùng)

1. Trả lời Q1–Q10 trong gói duyệt.
2. Phiếu v8 (cổng 8767): nạp `migrated-d613bd4747c8289f.jsonl`, chấm 4.474 mục, rồi `seal`. Kiểm lại mù sàng lọc từ 17/11.
3. Sàng lọc 6 PDF holdout (cổng 8769). Thêm PDF born-digital của công ty mới cho đủ slot.
4. Gán nhãn GT cấu trúc theo 4 lô trong gói duyệt (cổng 8768). Nhãn nháp AAA ở `autosave/` (chỉ trang 2 đã rà).
5. Push khi muốn.

## Tiếp quản và bài báo 13/11

- 48 test map, reading order và keyword đạt. Audit 006/007 ghi `NEEDS_REVIEW` cho 9/9 PDF mỗi lượt. [Nhật ký tiếp quản](../../scratch/dev_sessions/20261113-project-takeover/session.md). PP-StructureV3 smoke GPU đạt ([lệnh](../../scratch/v8/ppstructurev3-install/session.md)).
- 5 bài mẫu → [bản thảo OCR](../../research_notes/BAI_BAO_OCR_PDF.md). Bản nộp cần GT độc lập. [Lệnh và bằng chứng](../../scratch/dev_sessions/20261113-baibao/session.md).
