# Bàn giao

Cập nhật 13/11/2026, Asia/Bangkok. Nhánh `v8-diacritic-bounds-keyword-challenger`, PR [#1](https://github.com/VuTuanAn1403/OCR/pull/1). Commit cục bộ, chưa push. Khóa hiện hành `BASELINE-V8-20261113-001` (output `v8_006_arena1536_20261112`, arena detector 1536 MB). Xem trạng thái bằng `scripts/check_knowledge_map.py --summary`.

## 12/11 — §4.1, V8-080, V8-140

- **Batch 004 (mã `5d8cbb5`):** giữ dòng A1 bị loại trong `rejected_ocr_lines` và review packet. Ô heuristic dùng bbox dòng nguồn, giữ chữ và ghi token bị bỏ. Bảng model nhận dòng khi chồng bảng heuristic.
- **Audit 004:** 9/9 PDF, identity MATCH. Dòng mất 3.652→0, ô số không truy được 292→2, bỏ 333 dòng trùng, DSER dev và keyword trùng 003. Có 69 khác biệt do Docling crash không tất định. [Hồ sơ candidate](../../cai%20tien%20v2/bao_cao/CANDIDATE_SELECTION_DOSSIER.md).

- **V8-011:** đo dev khóa v7 trùng v6. Phiếu v7 `scratch/v8/adjudication/v8_011_dev_003_v7_20261112/` nhận 4.525 quyết định v6 (ảnh cắt và A/B khớp, `migrate_adjudication_decisions.py --leave-changed`); còn 5.208 mục.
- **V8-012:** holdout cần khoảng 680.000 slot (`scratch/v8/holdout/HOLDOUT_PREP_20261112.md`).
- **V8-095:** protocol ở `benchmark/challengers/parsers/README.md`.
- **Crop cố định (V8-065/050/030):** 3.000 dòng dev (`scratch/v8/recognition_crops/v8_065_dev_004_3000_20261112/`, tham chiếu là text layer, không phải GT).
  - VietOCR đọc crop gốc so với từng biến: `upscale2` 132 sửa / 13 sai (DSER 1.223 → 1.043); `clahe` 38/72; `denoise` 4/34; `otsu` 26/1.350.
  - V8-030 trên cùng crop: 16 sửa / 0 sai.
- **GT có cấu trúc (V8-060/070/071/080):** 44 trang chọn theo giả thuyết; phiếu rỗng có autosave ở `scratch/gt/structured_dev_004_20261112/` (cấu hình `structured-gt-sheets`).
- **V8-085:** 9 PDF dev không có công thức; cần bộ PDF có công thức.
- **Candidate phóng ×2 (V8-050):** `recognition_line_upscale`, mặc định tắt; cấu hình `config/candidates/v8_050_line_upscale2.yaml`.
  - Lượt 1 (arena 1024 MB): AAA lỗi 3/3 nên REJECT. Người dùng nâng arena lên 1536 MB (`4274a49`); 004 so 006 không đổi kết quả.
  - Lượt 2 (khóa `20261113-002`, 9/9): DSER khóa v7 13.751 → 11.647 / 345.300; 1.781 sửa / 306 sai; keyword 3/0; phiếu 72 số không đổi. Dev, `INCONCLUSIVE`, đáng đo holdout trước.
- **Vintern (V8-090, `DONE`: gate đạt, `scripts/check_vlm_run_gate.py`):** 137/137 trang, 0 thiếu; 2 trang lặp prompt. Trên 90 trang có text layer: DSER VLM 4.647 so với production 1.606 (33 trang tốt hơn / 43 kém hơn). Đề xuất `KEEP BASELINE`.

## Phát hiện còn mở

- **Chỉ mở phiếu qua `scripts/serve_review_sheets.py`.** Khung trình duyệt của app làm mất localStorage. Mở phiếu để kiểm đã ghi file trạng thái rỗng (0 quyết định) vào `autosave/` của phiếu 72 số và phiếu v7.
- **Chính sách dòng confidence thấp có chữ thật** (cần người dùng): VIC tr.95 "số hóa tài liệu đào tạo…" (0,535) nằm ngoài `result.md`, nên keyword "Số hóa" không được đếm (`scratch/v8/v8_100_retained_line_keywords_004_20261112.json`).
- Ô rỗng của bảng ảnh mang bbox cấp bảng, nên audit báo 45 số "vắng"; không mất chữ.

## Bước kế tiếp (cần người dùng)

1. Push nhánh khi muốn (commit `5d8cbb5` đã có cục bộ).
2. Chấm phiếu v7: nạp `migrated-f2cd97ad29f6fa25.jsonl`, chấm 5.208 mục, rồi `seal`. Kiểm lại mù từ 17/11.
   - **Xong 12/11 20:24:** phiếu 72 số trong bảng (worklist audit trên output `v8_003_baseline_20261109`, không phải mẫu ngẫu nhiên) đã seal ở `scratch/v8/table_review/sealed/v8_080_table_numbers_003_v1_20261112/seal.json`, sha256 `d1738804…`: bảng mất số in thật 58 (heuristic 39, tableformer 19), bảng có số không in 5, dòng OCR có số không in 4, không quyết được 5. Quyết định ghi `tool_files_dirty: true`.
3. Quyết: chuẩn hóa `ƣ`→`ư`; chính sách dòng confidence thấp; dùng khóa 20261113-001 làm baseline; các đề xuất trong hồ sơ V8-140 (×2: đo holdout; Vintern: KEEP BASELINE).
4. Holdout: PDF mới và manifest của custodian.
5. Ghim và tải ứng viên REC, LAYOUT, công thức, parser. Gán nhãn 44 trang GT, rồi `label_structured_gt.py export`.
   - Trạng thái 12/11 20:23 (autosave): chỉ AAA có nhãn. Trang 2 đã rà đủ 4 loại, rỗng (ảnh bìa không chữ; layout chưa có `Picture`). Trang 20/32/69/154 có vùng nhưng chưa tick rà; bảng chưa có ô số; trang 69 có bảng chưa có HTML. VIC rỗng; 7 PDF còn lại chưa mở. Chưa export.
   - Người dùng dừng gán nhãn ở mức này (12/11). Không export: chỉ trang 2 được rà, và layout của trang này thiếu vùng `Picture`. GT cấu trúc (V8-060/070/071/080) vẫn `NOT_EVALUATED`. Nhãn nháp giữ ở `autosave/` của phiếu AAA.

## Trạng thái 13/11

- Baseline 006 và candidate 007: 9/9, audit exit 0, identity MATCH. Hồ sơ V8-140 cập nhật.
- Đã xóa theo yêu cầu: `.venv-v62-clean`, `.venv-docling`, cache uv và pip; ổ C còn khoảng 22 GB. Smoke sau dọn đạt.
