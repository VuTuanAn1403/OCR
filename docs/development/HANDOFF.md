# Bàn giao

Cập nhật 12/11/2026, Asia/Bangkok. Nhánh `v8-diacritic-bounds-keyword-challenger`, PR [#1](https://github.com/VuTuanAn1403/OCR/pull/1). Commit cục bộ `5d8cbb5`, `7097375` và tiếp theo (chưa push). Khóa hiện hành `BASELINE-V8-20261112-001`. Trạng thái: `scripts/check_knowledge_map.py --summary`. Nhật ký [12/11](../../scratch/dev_sessions/20261112-v8-no-silent-drop/session.md), [rà soát 12/11](../../scratch/dev_sessions/20261112-v8-progress-audit/session.md).

## 12/11 — §4.1, V8-080, V8-140

- **Sửa `src/` (đổi identity):**
  - Dòng bị cổng A1 loại được ghi vào `extraction.json` (`rejected_ocr_lines`, có `source_id`, bbox, `text_raw`, mã review) và vào review packet; không vào `result.md`.
  - Ô bảng heuristic mang bbox dòng nguồn; chữ không bị viết lại; token bị bỏ được ghi lại.
  - Dòng khớp cả bảng heuristic chồng lẫn một bảng model thì bảng model nhận.
- **Kiểm:** hồi quy 2.657 passed, 1 skipped; smoke + audit exit 0. Batch `output/v8_004_nosilentdrop_r2_20261112` 9/9 (AAA cần retry vì ONNX arena), identity 9/9 MATCH.
- **So với 003:**
  - Dòng mất 3.652 → 0; ô số không truy được nguồn 292 → 2; 333 bản trùng bỏ; 0 dòng nguồn mất.
  - DSER dev và keyword không đổi.
  - 69 thay đổi khác do worker Docling crash `0xC0000005` không tất định.
  - Hồ sơ: [`CANDIDATE_SELECTION_DOSSIER.md`](../../cai%20tien%20v2/bao_cao/CANDIDATE_SELECTION_DOSSIER.md).
- **V8-011:** đo dev khóa v7 trùng v6. Phiếu v7 `scratch/v8/adjudication/v8_011_dev_003_v7_20261112/` nhận 4.525 quyết định v6 (ảnh cắt và A/B khớp, `migrate_adjudication_decisions.py --leave-changed`); còn 5.208 mục.
- **V8-012:** holdout cần khoảng 680.000 slot (`scratch/v8/holdout/HOLDOUT_PREP_20261112.md`).
- **V8-095:** protocol ở `benchmark/challengers/parsers/README.md`.
- **Crop cố định (V8-065/050/030):** 3.000 dòng dev (`scratch/v8/recognition_crops/v8_065_dev_004_3000_20261112/`, tham chiếu là text layer, không phải GT).
  - VietOCR đọc crop gốc so với từng biến: `upscale2` 132 sửa / 13 sai (DSER 1.223 → 1.043); `clahe` 38/72; `denoise` 4/34; `otsu` 26/1.350.
  - V8-030 trên cùng crop: 16 sửa / 0 sai.
- **GT có cấu trúc (V8-060/070/071/080):** 44 trang chọn theo giả thuyết; phiếu rỗng có autosave ở `scratch/gt/structured_dev_004_20261112/` (cấu hình `structured-gt-sheets`).
- **V8-085:** 9 PDF dev không có công thức; cần bộ PDF có công thức.
- **Candidate phóng ×2 (V8-050):** `recognition_line_upscale`, mặc định tắt (`7097375`); cấu hình `config/candidates/v8_050_line_upscale2.yaml`; khóa `BASELINE-V8-20261112-002`.
  - So với 004 trên 6 PDF dev: 1.208 đơn vị sửa / 258 làm sai (DSER 11.046 → 9.743); keyword 3 sửa / 0 sai.
  - AAA lỗi arena detector 3/3 ở trang 21 (`gpu_mem_limit_mb: 1024` trong `models/v62/runtime-models.json`), nên ở dạng này là REJECT theo hợp đồng.
- **Vintern (V8-090):** 137/137 trang, 0 thiếu; 2 trang lặp prompt. Trên 90 trang có text layer: DSER VLM 4.647 so với production 1.606 (33 trang tốt hơn / 43 kém hơn). Đề xuất `KEEP BASELINE`.

## Trước đó (10–12/11)

- 7 PDF dev sàng lọc `ACCEPTED`; kiểm lại mù từ 17/11 (`scratch/v8/screening/recheck/`).
- Phân xử v6: 5.021/9.733 mục; bảo thủ 14.274/346.402 (4,1%); ρ_U 0,026. Chi tiết ở protocol §7.6.

## Phát hiện còn mở

- **Chỉ mở phiếu qua `scripts/serve_review_sheets.py`.** Khung trình duyệt của app làm mất localStorage. Mở phiếu để kiểm đã ghi file trạng thái rỗng (0 quyết định) vào `autosave/` của phiếu 72 số và phiếu v7.
- **Chính sách dòng confidence thấp có chữ thật** (cần người dùng): VIC tr.95 "số hóa tài liệu đào tạo…" (0,535) nằm ngoài `result.md`, nên keyword "Số hóa" không được đếm (`scratch/v8/v8_100_retained_line_keywords_004_20261112.json`).
- Ô rỗng của bảng ảnh mang bbox cấp bảng, nên audit báo 45 số "vắng"; không mất chữ.

## Bước kế tiếp (cần người dùng)

1. Push nhánh khi muốn (commit `5d8cbb5` đã có cục bộ).
2. Chấm phiếu v7: nạp `migrated-f2cd97ad29f6fa25.jsonl`, chấm 5.208 mục, rồi `seal`. Chấm 72 mục số trong bảng, rồi `build_table_number_review.py seal`. Kiểm lại mù từ 17/11.
3. Quyết: chuẩn hóa `ƣ`→`ư`; chính sách dòng confidence thấp; dùng khóa 004 làm baseline; xử lý giới hạn arena detector (manifest model) rồi chạy lại candidate ×2; đề xuất cho Vintern.
4. Holdout: PDF mới và manifest của custodian.
5. Ghim và tải ứng viên REC, LAYOUT, công thức, parser. Gán nhãn 44 trang GT, rồi `label_structured_gt.py export`.

## Kiểm tra chiều 12/11

- HEAD `17bd541`, hơn ref `origin` cục bộ 2 commit. Backlog 23 `DONE`, 13 `IN_PROGRESS`, 2 `TODO`. Bản sửa 004 đã có batch và audit. Claude đang kiểm thử ứng viên crop ×2 trong thư mục làm việc.
- Phiếu v7 còn 5.208 mục sau khi chuyển quyết định. Phiếu 72 số chưa có quyết định mới. Cổng dấu vẫn `NOT_EVALUATED`.
- [Nhật ký kiểm tra chiều 12/11](../../scratch/dev_sessions/20261112-v8-afternoon-status/session.md).
