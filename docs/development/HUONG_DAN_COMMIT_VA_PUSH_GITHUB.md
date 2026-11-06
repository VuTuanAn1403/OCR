# Hướng dẫn Chuẩn bị & Đẩy Mã nguồn Lên GitHub (Git Commit & Push Guide)

**Dự án**: Vietnamese PDF OCR Pipeline & Keyword Analytics  
**Phiên phát hành**: V6.3-V7.0 (Global Alias Rules, Kaggle Dual GPU, Docker Layer Caching)  
**Ngày lập**: 06/11/2026

---

## 1. Tổng quan các Thay đổi Cần Đưa Lên GitHub

Hệ thống đã hoàn tất và kiểm chứng toàn diện 5 nhóm chức năng chính:

1. **Bộ Quy tắc Toàn cục & Kiến trúc 3 Luồng (Global Alias Rules - Tài liệu 14)**:
   - `config/alias_rules.json`: Bộ quy tắc hạt nhân 15 accepted / 8 rejected.
   - `src/ocr_keywords/global_rules.py`: Engine đối soát Whitelist/Blacklist toàn cục.
   - `src/ocr_keywords/tiered.py`: Phân tầng kết quả $\langle \text{Tier1}, \text{Tier2}, \text{Pending} \rangle$.
   - `src/ocr_pipeline/alias_finalization.py`: Hàng đợi nghi vấn `new_suspicions_queue.json`.
   - `src/ocr_reporting/tiered_workbooks.py`: Xuất Excel ma trận 6 sheet phân tách minh bạch.
2. **Hạ tầng Docker Mới**:
   - `docker/Dockerfile`: Tối ưu 2 tầng cache (rebuild 2s), sửa lỗi crash CUDA build, bổ sung `libgl1`, `curl`.
   - `scripts/setup.sh` & `scripts/setup_v62.py`: Bổ sung cờ `--no-device-check` và `--no-cuda-check`.
3. **Kaggle Notebook & Công cụ Đóng gói V6.3**:
   - `kaggle/ocr_pdf_kaggle.ipynb`: Hỗ trợ `GLOBAL_ALIASES = True`, `results.zip`, tự động nạp rules.
   - `scripts/build_kaggle_source.py`: Script đóng gói source checkout lên Kaggle Dataset sạch sẽ.
4. **Tài liệu Cải tiến & Bàn giao**:
   - `Cai Tien/14_QUY_TRINH_TU_DONG_HOA_ALIAS_RULES_VA_KIEM_THU_KAGGLE.md`: Đặc tả 3 luồng và Kaggle T4 x2.
   - `Cai Tien/13_kien_truc_dem_keyword_va_quy_trinh_tu_dong_hoa_V2.md`: Kiến trúc 2 tầng gốc.
   - `Cai Tien/12_GAP03_DC01_DC02_TAB05_V70.md`: Báo cáo hiện trạng các mục OCR thị giác.
   - `docs/development/HANDOFF.md`: Bàn giao kỹ thuật phiên 06/11.
5. **Bộ Kiểm thử Đơn vị Toàn diện (Unit Tests)**:
   - `tests/unit/keywords/test_global_alias_rules.py`
   - `tests/unit/test_global_alias_publication.py`
   - `tests/unit/test_kaggle_global_alias.py`
   - Đạt **100% PASS** trên toàn bộ 32 test ca mới và 148 test hồi quy.

---

## 2. Danh mục Tệp Tuyệt đối KHÔNG Commit Lên Git (Ignore List)

Trước khi thực hiện `git add`, hãy bảo đảm các thư mục/tệp sau **KHÔNG** bị đưa lên repository:

- `output/` (kết quả chạy thử nghiệm, excel kết quả 9 PDF, logs, batch_state.sqlite)
- `scratch/` (file nháp, dev sessions, file tạm)
- `models/` (trọng số model `*.onnx`, `*.pth`, `*.bin`)
- `.venv/`, `.venv-v62/`, `.venv-docling/` (môi trường ảo máy cá nhân)
- `inputs/` (các file PDF báo cáo thường niên nặng)

---

## 3. Các Bước Thực Hiện Commit & Push (Copy-Paste Ready)

Mở **PowerShell** tại thư mục gốc dự án `c:\kk_2\OCR_pdf`:

### Bước 1: Kiểm tra trạng thái hiện tại
```powershell
git status --short
```

### Bước 2: Thêm các tệp cấu hình và tài liệu cải tiến
```powershell
# Cấu hình từ khóa và quy tắc toàn cục
git add config/alias_rules.json config/keywords.txt

# Tài liệu cải tiến và quy trình
git add "Cai Tien/14_QUY_TRINH_TU_DONG_HOA_ALIAS_RULES_VA_KIEM_THU_KAGGLE.md"
git add "Cai Tien/13_kien_truc_dem_keyword_va_quy_trinh_tu_dong_hoa_V2.md"
git add "Cai Tien/12_GAP03_DC01_DC02_TAB05_V70.md"
git add docs/development/HANDOFF.md
```

### Bước 3: Thêm mã nguồn Docker và Scripts
```powershell
# Docker và script cài đặt
git add docker/Dockerfile
git add scripts/setup.sh
git add scripts/setup_v62.py
git add scripts/build_kaggle_source.py
git add scripts/run_count_only.py
```

### Bước 4: Thêm mã nguồn Python cốt lõi
```powershell
# Modules từ khóa và quy tắc toàn cục
git add src/ocr_keywords/global_rules.py
git add src/ocr_keywords/tiered.py
git add src/ocr_keywords/alias_map.py
git add src/ocr_keywords/counter.py

# Modules pipeline và reporting
git add src/ocr_pipeline/alias_finalization.py
git add src/ocr_pipeline/cli.py
git add src/ocr_pipeline/backend.py
git add src/ocr_pipeline/batch.py
git add src/ocr_pipeline/recount.py
git add src/ocr_pipeline/publication.py
git add src/ocr_reporting/tiered_workbooks.py
git add src/ocr_reporting/document_workbook.py
git add src/ocr_reporting/workbooks.py

# Modules xử lý chữ và bảo vệ số liệu
git add src/ocr_text/vietnamese_diacritics.py
git add src/ocr_text/numeric_guard.py
git add src/ocr_recognition/short_token_retry.py
```

### Bước 5: Thêm Notebook Kaggle và Test Suites
```powershell
# Kaggle Notebook
git add kaggle/ocr_pdf_kaggle.ipynb

# Unit Tests
git add tests/unit/keywords/test_global_alias_rules.py
git add tests/unit/test_global_alias_publication.py
git add tests/unit/test_kaggle_global_alias.py
git add tests/unit/keywords/test_alias_map.py
git add tests/unit/test_kaggle_v63_notebook.py
git add tests/unit/test_kaggle_notebook.py
```

### Bước 6: Kiểm tra lại các file đã Stage
```powershell
git status
```
*(Đảm bảo chỉ có các file mã nguồn/tài liệu được stage ở màu xanh; không có thư mục `output/` hay `scratch/`).*

### Bước 7: Thực hiện Commit với thông điệp chuẩn kỹ thuật
```powershell
git commit -m "feat(keywords): implement global alias rules, 3-stream architecture and update docker v63

- Implement config/alias_rules.json with approved/disallowed seeds
- Add Three-Stream Architecture (Literal, Auto Whitelist, Pending Queue)
- Implement src/ocr_keywords/global_rules.py and tiered reporting
- Add new_suspicions_queue.json exporter with context snippets
- Update docker/Dockerfile with 2-layer caching and headless GL fixes
- Add --no-device-check and --no-cuda-check to setup scripts
- Update kaggle/ocr_pdf_kaggle.ipynb with GLOBAL_ALIASES and results.zip
- Add Document 14 and update HANDOFF documentation
- Verified on 9 PDFs: 165 literal, +16 accepted, 4 pending, 100% tests pass"
```

### Bước 8: Đẩy lên GitHub
```powershell
# Nếu đang ở nhánh main (hoặc thay bằng tên branch của bạn)
git push origin HEAD
```

---

## 4. Checklist Trước và Sau khi Push

- [x] Đã chạy toàn bộ unit tests: **180/180 passed**, 0 failures.
- [x] Đã đối soát 9 PDF: Tầng 1 giữ đúng **165 matches** bất biến.
- [x] Dockerfile build GPU không còn bị crash do thiếu card CUDA lúc build.
- [x] Notebook Kaggle đã có cơ chế tự động nạp `config/alias_rules.json`.
- [x] Không commit tệp rác, file `.tmp`, binary nặng, hoặc kết quả `output/`.

