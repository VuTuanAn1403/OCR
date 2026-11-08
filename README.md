# OCR PDF v7.0 — Pipeline Xử Lý Báo Cáo Tài Chính & Thống Kê Từ Khóa Đa Tầng

Dự án xử lý và chuyển đổi Báo cáo Tài chính (BCTC) PDF tiếng Việt quét/chụp thành **Markdown cấu trúc**, **JSON có bằng chứng tọa độ/nguồn gốc (provenance)**, và **Ma trận Excel thống kê từ khóa đa tầng**.

Kiến trúc v7.0 kế thừa pipeline toàn trang có gia tốc GPU và tích hợp toàn diện các cải tiến từ hồ sơ **Cải Tiến V7.0** (Tài liệu 12, 13, 14).

```text
PDF Đầu Vào 
   │
   ▼
[Pha A: OCR GPU] ──► (PP-OCRv4 ONNX Detection + VietOCR Seq2Seq + Heron Layout)
   │
   ▼ (Giải phóng hoàn toàn tiến trình Pha A & VRAM)
[Pha B: Cấu Trúc Bảng Docling GPU] ──► (TableFormer + CodeFormula trên Bridge PDF bảo toàn chữ)
   │
   ▼ (Giải phóng hoàn toàn tiến trình Pha B & VRAM)
[Pha C: Xuất Bản & Phân Tích CPU] ──► (Markdown, JSON, Plain Text, Ghép bảng an toàn)
   │
   ▼
[Đếm Từ Khóa 3 Luồng] ──► (Tier 1 Literal + Tier 2 Global Alias + Pending Queue)
   │
   ▼
[Xuất Ma Trận Excel & Đồng Bộ SQLite] ──► Chuyển sang PDF tiếp theo
```

---

## 🌟 Điểm Mới và Các Cải Tiến Nổi Bật Ở Phiên Bản v7.0

### 1. Tự Động Hóa Global Alias Rules & Thống Kê 3 Luồng (Tài liệu 14)
- **Tách bạch 3 luồng đếm rõ ràng**:
  - **Tier 1 (Literal)**: Đếm chuỗi con chính xác nguyên bản, bất biến (bảo toàn tuyệt đối 165 matches trên 9 BCTC chuẩn).
  - **Tier 2 (Auto-Whitelist)**: Tự động nhận diện và tính điểm các biến thể từ khóa hợp lệ thông qua bộ quy tắc toàn cục [`config/alias_rules.json`](config/alias_rules.json) với chuẩn hóa Unicode NFC + casefold (khôi phục các biến thể viết hoa, viết thường, hoặc tổ hợp chuẩn như *Trí tuệ nhân tạo*).
  - **Pending Queue (Chờ duyệt)**: Tự động trích xuất các biến thể nghi vấn (lỗi gõ phím, ngắt dòng giữa từ, dấu mờ) vào file [`new_suspicions_queue.json`](config/alias_rules.json) kèm số trang, tọa độ và ngữ cảnh lân cận (±10 từ) để người vận hành kiểm duyệt an toàn, không suy diễn bừa bãi.
- **Ma trận Excel 6 Sheet Hoàn Chỉnh**:
  - Xuất file `MA_TRAN_DEM_TU_KHOA_<N>_FILES.xlsx` gồm: `Ma trận từ khóa`, `Dem_Tier2`, `Cho_duyet`, `Tong_sau_duyet`, `Trich_dan_chi_tiet` (in đậm từ khớp), và `Trich_dan_Tier2`.

### 2. Tối Ưu Hóa Docker Siêu Tốc (2-Layer Caching & Headless)
- **Kiến trúc Cache 2 Tầng**:
  - **Layer 1 (Dependencies)**: Copy các file manifest (`requirements*.txt`, `scripts/setup*`) và cài đặt môi trường. Các lần build sau được cache hoàn toàn, không phải tải lại các thư viện nặng.
  - **Layer 2 (Application Code)**: Chỉ copy mã nguồn dự án và cài editable với cờ `--no-deps`. Thời gian rebuild khi sửa code giảm ngoạn mục từ **15–20 phút xuống chỉ còn ~2 giây**.
- **Loại bỏ phụ thuộc giao diện (Headless)**: Sử dụng các gói OpenCV headless, triệt tiêu hoàn toàn lỗi crash thiếu thư viện đồ họa hệ thống (`libGL.so.1`).
- **Cờ bypass kiểm tra build-time**: Bổ sung cờ `--no-device-check` và `--no-cuda-check` giúp build image thành công trên bất kỳ môi trường Docker CI/CD nào mà không yêu cầu có sẵn GPU lúc đóng gói.

### 3. Cải Tiến Bridge Cấu Trúc Bảng Docling (Table Structure Bridge)
- **Khắc phục lỗi mất tiêu đề cột**: Nhận diện nguyên nhân gốc rễ của việc mất header bảng phân trang (như trang 37 AGR và 110 ASM) do bridge cũ chỉ đọc các khối nhìn thấy (`visible_blocks`), bỏ sót các mảnh chữ OCR đóng băng.
- **Cơ chế Bridge Ẩn (`visible-and-frozen-ocr-v1`)**: Bổ sung toàn bộ nguồn OCR ẩn vào lớp PDF trung gian mà không làm biến dạng ảnh raster 180 DPI gốc.
- **Hiệu quả downstream vượt trội**:
  - Khôi phục 100% các ô tiêu đề cột tài chính: `Mã số`, `Thuyết minh`, `VND`, các năm so sánh (`31/12/2022`, `31/12/2021`).
  - Số lượng mảnh chữ OCR khớp chính xác vào ô bảng tăng từ **166 lên 218 mảnh** (+52 mapping trên AGR), tỷ lệ chữ bị đẩy vào diện cần review giảm mạnh từ **53 xuống còn 1**.

### 4. Bảo Toàn Tuyệt Đối Số Liệu Tài Chính (Financial Numeric Guard)
- **Quy tắc bất biến**: Tuyệt đối không cho phép AI/LLM tự ý sửa đổi hoặc đoán mò các con số tài chính (`numeric_guard.py`).
- **Bảo toàn bằng chứng**: Mọi chữ số thô (`text_raw`), bounding box, mã định danh nguồn (`source_id`) và góc xoay đều được khóa nguyên vẹn.
- **Xử lý token ngắn khó phân biệt (DC-01: O2O vs 020)**: Các trường hợp chữ số có nguy cơ nhầm lẫn do font in mờ được retry ở độ phân giải 400 DPI và đánh dấu yêu cầu người duyệt (`IMAGE_PROPOSAL_REQUIRES_REVIEW`), không tự ý sửa số liệu trong sổ sách.

### 5. Hạ Tầng Kaggle & Đóng Gói Nguồn Độc Lập
- **Tự động đóng gói sạch (`scripts/build_kaggle_source.py`)**: Đóng gói mã nguồn sạch (loại bỏ Git history, file tạm `output/`, `scratch/` và model weights) thành `scratch/kaggle_source.zip` gọn nhẹ.
- **Notebook Kaggle Chuẩn Hóa (`kaggle/ocr_pdf_kaggle.ipynb`)**:
  - Hỗ trợ chạy trực tiếp từ `SOURCE_ARCHIVE` đính kèm qua Kaggle Input hoặc clone tự động từ GitHub.
  - Tích hợp cờ cấu hình `GLOBAL_ALIASES = True`, tự động áp dụng luật alias và xuất gói kết quả `results.zip`.
  - Hỗ trợ phục hồi và chạy tiếp trên dữ liệu lớn (`PREVIOUS_RESULTS_DIR`) cho các batch từ 100 đến 1.000 PDF.

---

## 🛠️ 1. Yêu Cầu Hệ Thống & Cài Đặt

- **Hệ điều hành**: Windows 10/11 hoặc Linux (Ubuntu 22.04+ khuyến nghị).
- **Python**: Phiên bản **3.11** cho môi trường supervisor và các worker GPU.
- **Phần cứng**: NVIDIA GPU (khuyến nghị tối thiểu 8GB VRAM) có cài đặt NVIDIA Driver tương thích CUDA 12.x.
- **Kiến trúc môi trường cô lập**: Nhằm tránh xung đột phụ thuộc giữa các thư viện AI nặng, dự án tách làm 3 môi trường ảo:
  - `.venv`: Supervisor điều phối, CLI, SQLite, đếm từ khóa, xuất Excel (CPU).
  - `.venv-v62/text`: Worker OCR Pha A (ONNX Runtime CUDA, VietOCR, Heron Layout).
  - `.venv-v62/docling`: Worker cấu trúc Pha B (Docling TableFormer, CodeFormula CUDA).

### Cài đặt trên Windows (PowerShell):

```powershell
# 1. Tạo môi trường supervisor
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[app]" uv

# 2. Cài đặt các worker GPU
.\.venv\Scripts\python.exe scripts/setup_v62.py --python 3.11 --env-root .venv-v62
```

### Cài đặt trên Linux / Docker:

```bash
# Sử dụng Docker (khuyến nghị cho môi trường máy chủ)
docker build -t ocr-pdf:v7.0 -f docker/Dockerfile .
docker run --gpus all -it --rm -v $(pwd)/inputs:/app/inputs -v $(pwd)/output:/app/output ocr-pdf:v7.0
```

---

## 📦 2. Chuẩn Bị Trọng Số Model

Cấu hình model và revision chuẩn được khai báo tại [`models/v62/runtime-models.json`](models/v62/runtime-models.json).

```powershell
# Tải và chuẩn bị trọng số VietOCR
.\.venv\Scripts\python.exe scripts/setup_vietocr_model.py

# Tải detector ONNX và các snapshot Docling TableFormer
.\.venv-v62\docling\Scripts\python.exe scratch/download_gpu_models.py
```

---

## 🚀 3. Hướng Dẫn Vận Hành CLI

### Kiểm tra tính sẵn sàng (Preflight):
```powershell
.\.venv\Scripts\python.exe scripts/preflight_v62.py --device cuda --env-root .venv-v62 --output scratch/preflight.json
```

### Xử lý một file PDF duy nhất:
```powershell
.\.venv\Scripts\python.exe run_ocr.py inputs/bao_cao.pdf --output output/unified_one
```

### Xử lý hàng loạt (Batch processing):
Đặt tất cả các file PDF cần chạy vào thư mục `inputs/`:
```powershell
.\.venv\Scripts\python.exe run_batch.py --input inputs --output output/unified_batch
```

### Tiếp tục batch bị gián đoạn (Resume) hoặc thử lại file lỗi:
```powershell
# Chạy tiếp các file chưa hoàn tất
.\.venv\Scripts\python.exe run_batch.py --input inputs --output output/unified_batch --resume

# Thử lại các file có trạng thái FAILED
.\.venv\Scripts\python.exe run_batch.py --input inputs --output output/unified_batch --resume --retry-failed
```

---

## 📊 4. Phân Tích Từ Khóa & Cập Nhật Rules Không Cần OCR Lại

Một trong những ưu điểm lớn nhất của kiến trúc V7.0 là tính năng **Tách rời OCR và Phân tích (Decoupled Analysis)**. Khi bạn muốn đổi bộ từ khóa, cập nhật `config/alias_rules.json`, hoặc đổi quy tắc đếm: **hoàn toàn KHÔNG cần chạy lại OCR tốn GPU**.

```powershell
# Phân tích lại từ khóa trên kết quả đã có bằng CPU (chỉ mất vài giây):
.\.venv\Scripts\python.exe run_batch.py --analysis-from output/unified_batch --output output/analysis_moi --alias-rules config/alias_rules.json
```

File Excel ma trận tổng hợp `MA_TRAN_DEM_TU_KHOA_<N>_FILES.xlsx` và các hàng đợi nghi vấn `new_suspicions_queue.json` sẽ được sinh mới hoàn toàn tại thư mục đầu ra mới.

---

## ☁️ 5. Chạy Thử Nghiệm Trên Kaggle

Notebook duy nhất và chính thức: [`kaggle/ocr_pdf_kaggle.ipynb`](kaggle/ocr_pdf_kaggle.ipynb).

### Quy trình chạy:
1. Đóng gói mã nguồn hiện tại từ máy cục bộ:
   ```powershell
   .\.venv\Scripts\python.exe scripts/build_kaggle_source.py --output scratch/kaggle_source.zip
   ```
2. Tạo một Notebook mới trên Kaggle, bật **GPU T4 x2** hoặc **GPU P100** và bật **Internet: On**.
3. Thêm dataset chứa các file PDF cần xử lý vào `/kaggle/input/...`.
4. (Tùy chọn) Thêm file `kaggle_source.zip` làm Input Dataset và điền đường dẫn vào biến `SOURCE_ARCHIVE`.
5. Đặt cấu hình trong Cell 1 & 2:
   - `GLOBAL_ALIASES = True`: Bật đếm từ khóa theo luật toàn cục.
   - `ASSETS = "none"`: Tiết kiệm ổ đĩa (hoặc `"jpeg"` nếu cần lưu ảnh cắt).
   - `RUN_FULL_BATCH = True`: Thực thi toàn bộ batch.
6. Chọn **Run All**. Kết quả trích xuất, ma trận Excel và file nén `results.zip` sẽ được tạo tự động tại thư mục `/kaggle/working/`.

---

## 📂 6. Cấu Trúc Đầu Ra Chuẩn

Mỗi đợt chạy batch sinh ra cấu trúc thư mục minh bạch và có khả năng truy vết nguồn gốc (provenance):

```text
output/unified_batch/
  ├── batch_state.sqlite                 # Sổ cái SQLite theo dõi trạng thái từng PDF
  ├── batch_input_manifest.json          # Danh sách file đầu vào kèm mã băm SHA-256
  ├── batch_config.json                  # Cấu hình runtime và tham số đã sử dụng
  ├── batch_report.json                  # Báo cáo tổng hợp số lượng trang, lỗi, cảnh báo
  ├── MA_TRAN_DEM_TU_KHOA_<N>_FILES.xlsx # Ma trận Excel tổng hợp 6 sheet đa tầng
  ├── new_suspicions_queue.json          # Hàng đợi các biến thể từ khóa mới chờ duyệt
  ├── logs/                              # Log chi tiết của từng worker và tiến trình
  └── <ten_file_pdf>/
        ├── result.md                    # Nội dung trích xuất Markdown chuẩn (nguồn đếm)
        ├── result.txt                   # Nội dung Plain Text thuần túy (dễ tìm kiếm)
        ├── document.md                  # Markdown kèm cấu trúc cây đề mục
        ├── extraction.json              # Dữ liệu JSON gốc kèm bounding box và source ID
        ├── structure.json               # Cấu trúc bảng biểu và phân vùng tài liệu
        ├── ocr_receipt.json             # Biên lai xác thực phần cứng, thời gian, mô hình
        ├── keyword_counts.json          # Kết quả đếm từ khóa chi tiết của tài liệu
        ├── count_keywords.xlsx          # Bảng Excel đếm và trích dẫn theo trang của riêng file
        └── COMPLETED.json               # Khóa hoàn tất tài liệu (chống ghi đè)
```

---

## 🧪 7. Kiểm Thử & Đảm Bảo Chất Lượng

Dự án duy trì bộ kiểm thử hồi quy nghiêm ngặt với hơn 2.200 unit tests, contract tests và scientific evaluations:

```powershell
# Chạy toàn bộ test unit, khoa học và tương thích ngược
.\.venv\Scripts\python.exe scripts/run_pytest_scratch.py tests/unit tests/scientific tests/legacy_compat -q -ra
```

### Các nguyên tắc vận hành cốt lõi:
- **Nguyên tắc dữ liệu bất biến**: Không can thiệp sửa đổi các file receipt, hash hoặc kết quả đã công bố trong lịch sử.
- **Nguyên tắc không suy đoán số**: Nghiêm cấm mọi hành vi tự động đoán hoặc sửa chữ số trên Báo cáo Tài chính nếu không có sự xác nhận của con người.
- **Giới hạn kiểm thử**: Số lượng test pass hay cờ SUCCEEDED chỉ chứng minh tính toàn vẹn của mã nguồn phần mềm, không thay thế cho việc đánh giá độ chính xác thực tế trên tập Ground Truth (GT) độc lập.

---

## 📜 Tài Liệu Tham Khảo Thêm

- [Bản đồ cấu trúc dự án](docs/development/PROJECT_MAP.md)
- [Quy trình phát triển và kiểm chứng](docs/development/README.md)
- [Hồ sơ bàn giao phiên gần nhất](docs/development/HANDOFF.md)
- [QA Registry offline: import review, kiểm bằng chứng và revision](benchmark/qa/README.md)
- [Hướng dẫn Commit & Push GitHub an toàn](docs/development/HUONG_DAN_COMMIT_VA_PUSH_GITHUB.md)
- [Quy trình tự động hóa Alias Rules và kiểm thử Kaggle](cai%20tien%20v2/09_LUU_TRU_CAI_TIEN_V7.md#ct-14)
