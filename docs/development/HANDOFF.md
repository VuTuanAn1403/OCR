# Bàn giao

Cập nhật 13/11/2026, Asia/Bangkok. Nhánh `v8-diacritic-bounds-keyword-challenger`, PR [#1](https://github.com/VuTuanAn1403/OCR/pull/1). HEAD `f31fdee`, hơn upstream cục bộ 10 commit. Khóa hiện hành `BASELINE-V8-20261113-001` (output `v8_006_arena1536_20261112`, arena 1536 MB). Trạng thái: `scripts/check_knowledge_map.py --summary`.

## 12/11 — §4.1, V8-080, V8-140

- **Batch 004 (mã `5d8cbb5`):** giữ dòng A1 bị loại trong `rejected_ocr_lines` và review packet. Ô heuristic dùng bbox dòng nguồn, giữ chữ và ghi token bị bỏ. Bảng model nhận dòng khi chồng bảng heuristic.
- **Audit 004:** 9/9 PDF, identity MATCH. Dòng mất 3.652→0, ô số không truy được 292→2, bỏ 333 dòng trùng, DSER dev và keyword trùng 003. Có 69 khác biệt do Docling crash không tất định. [Hồ sơ candidate](../../cai%20tien%20v2/bao_cao/CANDIDATE_SELECTION_DOSSIER.md).

- **V8-011:** đo dev khóa v7 trùng v6. Phiếu v7 `scratch/v8/adjudication/v8_011_dev_003_v7_20261112/` nhận 4.525 quyết định v6 (ảnh cắt và A/B khớp, `migrate_adjudication_decisions.py --leave-changed`); còn 5.208 mục.
- **V8-012:** holdout cần khoảng 680.000 slot (`scratch/v8/holdout/HOLDOUT_PREP_20261112.md`).
- **V8-095:** protocol ở `benchmark/challengers/parsers/README.md`.
- **Crop cố định (V8-065/050/030):** 3.000 dòng dev (`scratch/v8/recognition_crops/v8_065_dev_004_3000_20261112/`, tham chiếu là text layer, không phải GT).
  - So với crop gốc: `upscale2` 132 sửa / 13 sai; `clahe`, `denoise`, `otsu` sai nhiều hơn sửa.
  - V8-030 trên cùng crop: 16 sửa / 0 sai.
- **GT có cấu trúc (V8-060/070/071/080):** 44 trang chọn theo giả thuyết; phiếu rỗng có autosave ở `scratch/gt/structured_dev_004_20261112/` (cấu hình `structured-gt-sheets`).
- **V8-085:** chờ duyệt bộ ngoài (`scratch/v8/V8_085_FORMULA_DATASET_PROPOSAL_20261113.md`).
- **V8-095 (`DONE`):** PP-StructureV3 chạy chỉ trên 35 trang giả thuyết (35/35): đồng thuận thứ tự đọc 0,89 (bảng heuristic 0,80). Pagefile giãn; ổ C còn ~4 GB.
- **Candidate phóng ×2 (V8-050):** `recognition_line_upscale` mặc định tắt. Arena 1024 MB: AAA lỗi 3/3; nâng lên 1536 MB (`4274a49`), lượt 2 hoàn tất. Dev DSER 13.751 → 11.647 / 345.300; 1.781 sửa / 306 sai; keyword 3/0; phiếu 72 số không đổi. `INCONCLUSIVE`, chờ holdout.
- **Vintern (V8-090, `DONE`):** 137/137 trang; DSER VLM 4.647 so với 1.606 trên 90 trang. Đề xuất `KEEP BASELINE`.

## Phát hiện còn mở

- **Chỉ mở phiếu qua `scripts/serve_review_sheets.py`.** Khung trình duyệt của app làm mất localStorage. Mở phiếu để kiểm đã ghi file trạng thái rỗng (0 quyết định) vào `autosave/` của phiếu 72 số và phiếu v7.
- **Chính sách dòng confidence thấp có chữ thật** (cần người dùng): VIC tr.95 "số hóa tài liệu đào tạo…" (0,535) nằm ngoài `result.md`, nên keyword "Số hóa" không được đếm (`scratch/v8/v8_100_retained_line_keywords_004_20261112.json`).
- Ô rỗng của bảng ảnh mang bbox cấp bảng, nên audit báo 45 số "vắng"; không mất chữ.

## Bước kế tiếp (cần người dùng)

1. Push nhánh khi muốn.
2. Chấm phiếu v7: nạp `migrated-f2cd97ad29f6fa25.jsonl`, chấm 5.208 mục, rồi `seal`. Kiểm lại mù từ 17/11.
   - Phiếu bảng 72 số đã seal 12/11. Worklist audit 003: mất 58 số in (heuristic 39, TableFormer 19), thêm 5 ở bảng và 4 ở dòng OCR, 5 chưa quyết. `tool_files_dirty: true`. Đã kiểm SHA-256 tệp quyết định `review-d1738804cf8b3b06.jsonl` theo `scratch/v8/table_review/sealed/v8_080_table_numbers_003_v1_20261112/seal.json`.
3. Quyết: chuẩn hóa `ƣ`→`ư`; chính sách dòng confidence thấp; dùng khóa 20261113-001 làm baseline; các đề xuất trong hồ sơ V8-140 (×2: đo holdout; Vintern: KEEP BASELINE).
4. Holdout: PDF mới và manifest của custodian.
5. Ghim và tải ứng viên REC, LAYOUT, công thức, parser. Gán nhãn 44 trang GT, rồi `label_structured_gt.py export`.
   - Trạng thái 12/11 20:23 (autosave): chỉ AAA có nhãn. Trang 2 đã rà đủ 4 loại, rỗng (ảnh bìa không chữ; layout chưa có `Picture`). Trang 20/32/69/154 có vùng nhưng chưa tick rà; bảng chưa có ô số; trang 69 có bảng chưa có HTML. VIC rỗng; 7 PDF còn lại chưa mở. Chưa export.
   - Người dùng dừng gán nhãn ở mức này (12/11). Không export: chỉ trang 2 được rà, và layout của trang này thiếu vùng `Picture`. GT cấu trúc (V8-060/070/071/080) vẫn `NOT_EVALUATED`. Nhãn nháp giữ ở `autosave/` của phiếu AAA.

## Tiếp quản 13/11

- So với `verified_head bcb5be4`, HEAD chỉ đổi backlog, registry và tài liệu. Map check đạt. Kiểm lại receipt 006/007: mỗi lượt 9/9 PDF, 938 trang, `MATCH` theo khóa `20261113-001/002`. Audit cũ: `NEEDS_REVIEW` cho cả 9 PDF mỗi lượt.
- 48 test map, reading order, keyword đạt. Lệnh, giới hạn và bước tiếp theo ở [nhật ký tiếp quản](../../scratch/dev_sessions/20261113-project-takeover/session.md). Độ chính xác và cổng dấu vẫn `NOT_EVALUATED`.
- Đã cài PP-StructureV3 và smoke GPU đạt. [Lệnh chạy, bằng chứng và cảnh báo cuDNN](../../scratch/v8/ppstructurev3-install/session.md).
