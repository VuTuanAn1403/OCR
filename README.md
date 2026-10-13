# Pipeline Trích Xuất PDF Sang Markdown & JSON Tiếng Việt (Hybrid OCR Architecture V6.0)

[![Python 3.10 | 3.11 | 3.12](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests: 425 Passed](https://img.shields.io/badge/tests-425%20passed-brightgreen.svg)](tests/)
[![Architecture: Clean Architecture](https://img.shields.io/badge/architecture-Clean%20Architecture-orange.svg)](src/ocr/)

Hệ thống xử lý tài liệu thông minh (**Intelligent Document Processing - IDP**) và trích xuất chuyên sâu dành cho tài liệu, báo cáo thường niên, báo cáo tài chính tiếng Việt từ PDF sang Markdown chuẩn hóa cùng hệ thống hợp đồng dữ liệu JSON bảo toàn triệt để nguồn gốc dữ liệu (provenance).

Hệ thống áp dụng kiến trúc **Clean Architecture**, cơ chế định tuyến lai **Native-first / OCR-fallback**, tích hợp mô hình cấu trúc bảng và công thức toán học **Docling TableFormer & CodeFormula**, cùng hệ thống rào chắn bất biến số liệu tài chính (**Numeric Guard**) và cây mục phân cấp toàn tài liệu (**Section Tree**).

---

## 1. Điểm Mới Trên Phiên Bản V6.0

Phiên bản **V6.0** nâng cấp toàn diện pipeline trích xuất đáp ứng các tiêu chuẩn nghiên cứu khoa học và vận hành thực tế:

- **Hợp Đồng Dữ Liệu Cấp Toàn Tài Liệu (Document Contracts):**
  - Xuất song song định dạng Markdown theo trang truyền thống (`result.md`, `pages/page-NNNN.md`) và Markdown cấp toàn tài liệu (`document.md`).
  - Hệ thống JSON hợp đồng chuẩn hóa tuân thủ **JSON Schema Draft 2020-12**:
    - `extraction.json`: Chi tiết từng phần tử bóc tách theo trang kèm tọa độ bounding box, `text_raw`, `text_corrected`, nguồn gốc sửa đổi và chuỗi biến đổi hình học.
    - `structure.json`: Cây mục phân cấp (H1, H2, H3, H4) và quan hệ cha-con của tài liệu.
    - `document.json`: Mô hình tri thức hoàn chỉnh cấp tài liệu tích hợp sections, chunks, tables với spans định vị chính xác xuyên trang và định danh ổn định (`doc_sha16:pNNNN:kindNNNN`).
    - `COMPLETED.json`: Chứng thực hoàn tất xử lý nguyên tử kèm mã băm PDF, cấu hình, mã nguồn và trọng số mô hình.
- **Rào Chắn Số Liệu Tài Chính (Numeric Evidence Guard):**
  - Bảo vệ tuyệt đối các con số, dấu âm/dương (`-`, `−`, `+`), ngoặc kế toán biểu thị số âm `(1.234.567)`, phân cách hàng nghìn/thập phân, tỷ lệ `%`, ngày tháng, mã số văn bản và đơn vị tiền tệ liền kề (`đồng`, `VND`, `USD`, `tỷ`, `triệu`...).
  - Ngăn chặn triệt để hiện tượng OCR lại vùng hoặc hậu xử lý làm thay đổi hay sai lệch số liệu tài chính.
- **Cây Mục Phân Cấp Toàn Tài Liệu (Document Section Tree):**
  - Tự động nhận diện cấu trúc tiêu đề từ mục lục (TOC), đặc trưng font chữ và mẫu đánh số phân cấp.
  - Hỗ trợ tiêu đề song ngữ Anh - Việt, nối các đoạn văn bị ngắt qua trang mà vẫn bảo toàn ngữ nghĩa phục vụ phân đoạn (chunking) cho RAG.
- **Độ Tin Cậy Trung Thực (Honest Confidence):**
  - Loại bỏ hoàn toàn giá trị gán cứng `0.90`. Đối với các mô hình không cung cấp độ tin cậy phân phối (như TableFormer hoặc trang native không qua OCR), hệ thống ghi nhận `confidence = null` đi kèm `confidence_source = "unavailable"`.
- **Bộ Điều Hợp Bố Cục Độc Lập (ONNX Layout Adapters):**
  - Cung cấp adapter chuẩn cho cả **Raw YOLO** (hỗ trợ NMS theo lớp) và **RT-DETR / Heron** (không dùng NMS), chuẩn hóa phép biến đổi ngược tọa độ từ ảnh pixel về điểm tọa độ PDF gốc.
- **Hỗ Trợ Xử Lý Phân Mảnh Lô (Deterministic Sharding):**
  - Hỗ trợ tham số `--shard I/N` và `--merge-shards N` trong công cụ xử lý lô, cho phép phân chia công việc tất định giữa nhiều máy tính/tiến trình mà không gây xung đột checkpoint hay báo cáo.
- **Quản Lý Cấu Hình & Thiết Bị Tập Trung:**
  - `config/profiles.yaml` là nguồn cấu hình duy nhất. Hỗ trợ tùy chọn thiết bị `--device cpu|cuda|auto` và quản lý linh hoạt chế độ lưu ảnh trích xuất qua `--assets none|jpeg|png`.
- **Môi Trường Docling Cách Ly (Worker Isolation):**
  - Docling 2.137.0 chạy độc lập trong môi trường con `.venv-docling` giao tiếp qua IPC JSON-lines, loại bỏ hoàn toàn xung đột thư viện giữa VietOCR (PyTorch) và Docling.

---

## 2. Kiến Trúc Hệ Thống (Clean Architecture)

```text
                                 Tài liệu PDF Đầu Vào
                                          │
                                          ▼
                               ┌─────────────────────┐
                               │    PDF Inspector    │
                               └──────────┬──────────┘
                                          │
                     ┌────────────────────┴────────────────────┐
                     ▼                                         ▼
            [Trang Native Tốt]                        [Trang Scan / Kém]
                     │                                         │
                     ▼                                         ▼
         Trích xuất Text Vector                      Render ảnh (180 DPI)
         (0.05 - 0.15s / trang)                                │
                     │                                         ▼
                     │                             ┌────────────────────────┐
                     │                             │  RapidOCR DBNet Detect │ (~0.3s)
                     │                             └───────────┬────────────┘
                     │                                         ▼
                     │                             ┌────────────────────────┐
                     │                             │ VietOCR Seq2Seq Batch  │ (~0.09s/dòng)
                     │                             └───────────┬────────────┘
                     │                                         ▼
                     │                             ┌────────────────────────┐
                     │                             │ Cổng Đánh Giá Dấu &    │
                     │                             │ Fallback OCR Vùng      │ (Có Numeric Guard)
                     │                             └───────────┬────────────┘
                     └────────────────────┬────────────────────┘
                                          │
                                          ▼
                               ┌─────────────────────┐
                               │  Layout & Bảng Biểu │
                               │  Heuristic / Docling│ (TableFormer & CodeFormula)
                               └──────────┬──────────┘
                                          │
                                          ▼
                               ┌─────────────────────┐
                               │  Section Tree &     │
                               │  Reading Order      │ (Dựng cây mục & thứ tự đọc)
                               └──────────┬──────────┘
                                          │
                                          ▼
                               ┌─────────────────────┐
                               │  Export & Contract  │
                               │  Validator          │
                               └──────────┬──────────┘
                                          │
                ┌─────────────────────────┴─────────────────────────┐
                ▼                                                   ▼
     [Định dạng Legacy]                                     [Hợp đồng V6 Cấp Tài Liệu]
     - result.md                                            - document.md
     - result.json                                          - document.json
     - quality.json                                         - extraction.json
     - pages/page-NNNN.{md,json}                            - structure.json
     - structures/tables/*.html                             - COMPLETED.json
```

---

## 3. Cấu Trúc Thư Mục Dự Án

```text
OCR_pdf/
├── config/
│   └── profiles.yaml                   # Cấu hình các hồ sơ xử lý (fast, balanced, accuracy)
├── src/ocr/
│   ├── domain/                         # Domain Entities & Models (Pydantic v2)
│   │   ├── models/                     # TextBlock, TableStructure, Region, Schema...
│   │   └── routing/                    # RoutingPolicy, PageType
│   ├── application/                    # Use Cases nghiệp vụ
│   │   ├── convert_document.py         # Use case điều phối toàn tài liệu
│   │   ├── process_page.py             # Pipeline xử lý từng trang tài liệu
│   │   ├── export_document.py          # Xuất dữ liệu đa định dạng & validation
│   │   ├── route_page.py               # Đánh giá native text và phân luồng
│   │   └── reocr_region.py             # OCR lại vùng cục bộ
│   ├── infrastructure/                 # Adapters kỹ thuật ngoại vi
│   │   ├── pdf/                        # PyMuPDF: trích xuất text, renderer, cropper
│   │   ├── ocr/                        # VietOCR (vgg_seq2seq), RapidOCR, Fallback
│   │   ├── layout/                     # DLA engine, Docling IPC client, model_adapters
│   │   ├── structure/                  # Section tree builder, Stable IDs
│   │   ├── postprocessing/             # Numeric guard, reading order, unicode NFC
│   │   ├── quality/                    # Native quality & Vietnamese diacritic gate
│   │   ├── export/                     # Markdown exporter, Document contracts, Validator
│   │   └── cache/                      # ArtifactCache quản lý băm SHA-256
│   ├── runtime/                        # Runtime paths, device, model fingerprint, atomic IO
│   └── cli/                            # run_ocr.py (tài liệu đơn), batch_runner.py (xử lý lô)
├── workers/
│   └── docling/                        # Worker Docling 2.137 chạy độc lập
├── scripts/
│   ├── docling_structure_worker.py     # Worker tiến trình phụ nhận lệnh qua IPC
│   ├── setup_models.py                 # Tải và xác thực trọng số RapidOCR
│   ├── setup_vietocr_model.py          # Tải và cấu hình VietOCR
│   ├── setup_docling.ps1               # Khởi tạo môi trường ảo .venv-docling
│   ├── setup.sh                        # Cài đặt tự động trên Linux / Colab
│   ├── check_installation.py           # Kiểm tra môi trường hệ thống
│   └── smoke_test.py                   # Smoke test kiểm tra toàn trình
├── benchmark/
│   ├── ground_truth/                   # Tập dữ liệu nhãn chuẩn
│   ├── scientific_evaluation/          # Bộ đo khoa học (CER, WER, DER_VN_v1, NumAcc, TEDS...)
│   └── perf/                           # Công cụ đo độ trễ, RAM, throughput (run_perf.py)
├── tests/
│   ├── unit/                           # 36 file kiểm thử đơn vị (~400 test cases)
│   ├── scientific/                     # Kiểm thử giao thức đánh giá khoa học
│   ├── integration/                    # Kiểm thử tích hợp tài liệu thực
│   └── golden/                         # Kiểm thử so khớp chuẩn vàng
├── pyproject.toml                      # Cấu hình dự án & entry points
└── requirements.txt                    # Thư viện phụ thuộc chính
```

---

## 4. Yêu Cầu Hệ Thống & Cài Đặt

### Yêu Cầu Kỹ Thuật
- **Hệ điều hành:** Windows 10/11, Ubuntu 20.04+, macOS
- **Python:** Khuyên dùng **Python 3.11**
- **RAM:** Tối thiểu 4 GB (khuyên dùng 8–16 GB khi xử lý tài liệu lớn hoặc chạy lô)
- **Thiết bị:** Tối ưu hóa sâu cho **CPU** đa nhân thông thường; hỗ trợ tăng tốc **CUDA GPU** khi có sẵn.

---

### Hướng Dẫn Cài Đặt (Từng Bước)

#### 1. Môi trường chính cho OCR Pipeline
```bash
# Clone repository
git clone https://github.com/VuTuanAn1403/OCR.git
cd OCR

# Khởi tạo môi trường ảo Python 3.11
python -m venv .venv

# Kích hoạt môi trường (Windows PowerShell)
.\.venv\Scripts\Activate.ps1
# Hoặc trên Linux / macOS:
# source .venv/bin/activate

# Cài đặt thư viện phụ thuộc
pip install --upgrade pip
pip install -r requirements.txt

# Tải trọng số mô hình OCR (RapidOCR và VietOCR)
python scripts/setup_models.py
python scripts/setup_vietocr_model.py
```

#### 2. Cấu hình môi trường cách ly cho Docling (Bảng & Công thức toán)
Do Docling sử dụng các gói phụ thuộc đặc thù xung đột với VietOCR, Docling chạy trong môi trường ảo riêng biệt:
```powershell
# Trên Windows:
powershell -ExecutionPolicy Bypass -File scripts/setup_docling.ps1

# Kiểm tra worker Docling hoạt động offline
.\.venv\Scripts\python.exe scripts/smoke_docling_structures.py
```

#### 3. Kiểm tra cài đặt và smoke test
```bash
# Kiểm tra môi trường
python scripts/check_installation.py

# Chạy smoke test toàn trình
python scripts/smoke_test.py
```

---

## 5. Hướng Dẫn Sử Dụng (CLI)

### 5.1. Xử Lý Một Tài Liệu (`run_ocr.py`)

Cú pháp:
```bash
python run_ocr.py <ĐƯỜNG_DẪN_PDF> [TÙY_CHỌN]
```

**Các tham số chính:**
| Tham số | Giá trị | Mặc định | Ý nghĩa |
|---|---|---|---|
| `input` | Chuỗi | *Bắt buộc* | Đường dẫn file PDF (tự động tìm tại thư mục hiện hành, `inputs/`, `examples/`) |
| `--profile` | `fast`, `balanced`, `accuracy` | `balanced` | Hồ sơ xử lý tối ưu |
| `--device` | `cpu`, `cuda`, `auto` | Theo profile | Thiết bị tính toán |
| `--pages` | Ví dụ `1-3`, `1,5,10` | Toàn bộ | Chỉ định các trang cần xử lý |
| `--output` | Chuỗi | `output` | Thư mục lưu kết quả xuất ra |
| `--assets` | `none`, `jpeg`, `png` | `png` | Chế độ trích xuất và lưu file ảnh vùng đồ họa |
| `--benchmark` | Cờ bật | `false` | Hiển thị bảng chi tiết thời gian đo đạc |
| `--resume` | Cờ bật | `false` | Bỏ qua các trang đã có trong cache an toàn |
| `--config` | Chuỗi | `config/profiles.yaml` | Đường dẫn file cấu hình tùy biến |

**Ví dụ thực tế:**
```bash
# Xử lý nhanh trang 1 của file mẫu, không xuất file ảnh crop
python run_ocr.py sample.pdf --profile fast --pages 1 --assets none

# Xử lý báo cáo với profile balanced, đo benchmark chi tiết
python run_ocr.py inputs/ADP_Baocaothuongnien_2025.pdf --profile balanced --benchmark

# Chạy trang 1-10 với chế độ accuracy cao nhất
python run_ocr.py inputs/BSI_Baocaothuongnien_2025.pdf --profile accuracy --pages 1-10
```

---

### 5.2. Xử Lý Hàng Loạt & Phân Mảnh Lô (`run_batch.py`)

Cú pháp:
```bash
python run_batch.py --input inputs --output output [TÙY_CHỌN]
```

**Các tham số chạy lô:**
| Tham số | Giá trị | Ý nghĩa |
|---|---|---|
| `--input` | Thư mục | Thư mục chứa các file PDF đầu vào |
| `--output` | Thư mục | Thư mục lưu kết quả toàn bộ tài liệu |
| `--profile` | `fast`, `balanced`, `accuracy` | Hồ sơ xử lý áp dụng cho cả lô |
| `--shard` | `I/N` (ví dụ `0/2`, `1/2`) | Chia lô theo phân mảnh tất định |
| `--merge-shards` | Số nguyên $N$ | Gộp báo cáo tổng hợp từ $N$ phân mảnh |
| `--force` | Cờ bật | Bỏ qua cache, buộc xử lý lại toàn bộ |
| `--limit` | Số nguyên | Giới hạn số lượng tài liệu xử lý |

**Ví dụ chạy song song nhiều phân mảnh:**
```bash
# Worker 1 xử lý nửa đầu danh sách tài liệu
python run_batch.py --input inputs --output output/v6 --profile balanced --shard 0/2

# Worker 2 xử lý nửa sau danh sách tài liệu
python run_batch.py --input inputs --output output/v6 --profile balanced --shard 1/2

# Gộp báo cáo sau khi cả 2 shard hoàn thành
python run_batch.py --output output/v6 --merge-shards 2
```

---

### 5.3. Đo Lường Hiệu Năng Nghiên Cứu (`run_perf.py`)

Công cụ đo đạc độc lập đo lường độ trễ chi tiết (p50, mean, p95), mức tiêu hao RAM/VRAM và xuất file `perf.json`:
```bash
python -m benchmark.perf.run_perf --pdf inputs/ADP_Baocaothuongnien_2025.pdf --pages 1-3 --profile balanced --device cpu --assets none --repeat 3 --output scratch/perf-adp
```

---

## 6. So Sánh Các Hồ Sơ Xử Lý (Profiles)

| Tiêu chí | Fast (`--profile fast`) | Balanced (`--profile balanced`) | Accuracy (`--profile accuracy`) |
|---|:---:|:---:|:---:|
| **Engine OCR chính** | RapidOCR (CPU) | VietOCR (Seq2Seq) | VietOCR (Seq2Seq) |
| **Độ phân giải Render** | 150 DPI | 180 DPI | 180 DPI |
| **Bóc tách Bảng & Công thức** | Tắt Docling | Bật Docling TableFormer + Formula | Bật Docling TableFormer + Formula |
| **Cơ chế Fallback vùng** | Tắt | Chỉ bật khi trang cần review ($\le 15\%$ vùng) | Fallback thích ứng đa pass ($\le 25\%$ vùng) |
| **Thời gian Native (CPU)** | **$\le 0.15$ s / trang** | **$\le 0.15$ s / trang** | $\le 0.20$ s / trang |
| **Thời gian Scan (CPU)** | $\approx 2 - 4$ s / trang | $\approx 8 - 12$ s / trang | $\approx 15 - 20$ s / trang |
| **Phù hợp sử dụng** | Xem trước nhanh, PDF số sạch | Báo cáo thường niên, BCTC chuẩn | Bản scan nghiêng mờ, nhiều bảng phức tạp |

---

## 7. Cấu Trúc Kết Quả Xuất Ra

Sau khi xử lý file `<DOC_ID>.pdf`, hệ thống tạo cấu trúc kết quả tại thư mục `output/<DOC_ID>/`:

```text
output/<DOC_ID>/
├── document.md               # Markdown cấp toàn tài liệu đã dựng cây mục chuẩn
├── document.json             # Hợp đồng V6: sections, chunks, tables kèm spans và block IDs
├── extraction.json           # Dữ liệu trích xuất chi tiết từng trang kèm text_raw / text_corrected
├── structure.json            # Cây mục phân cấp (H1, H2, H3, H4) của tài liệu
├── COMPLETED.json            # Chứng nhận xử lý hợp lệ kèm hash mã nguồn, model và cấu hình
├── result.md                 # Markdown truyền thống theo từng trang (# Trang N)
├── result.json               # Dữ liệu dòng chữ và bounding box legacy
├── quality.json              # Báo cáo đánh giá chất lượng native/OCR và trạng thái review
├── manifest.json             # Metadata tài liệu, phiên bản pipeline, hash SHA-256
├── validation.json           # Báo cáo kiểm định hợp đồng dữ liệu của artifact validator
├── pages/                    # Kết quả chi tiết theo từng trang riêng lẻ
│   ├── page-0001.md
│   ├── page-0001.json
│   └── ...
└── structures/               # Kết quả trích xuất từ Docling
    ├── tables/               # File HTML lưu trữ cấu trúc bảng có rowspan / colspan
    │   └── p0010_table_1.html
    └── formulas/             # Công thức toán học định dạng LaTeX
        └── p0005_formula_1.tex
```

---

## 8. Đảm Bảo Chất Lượng & Kiểm Thử Khoa Học

Dự án sở hữu bộ kiểm thử tự động toàn diện gồm **425 test cases** bao phủ mọi tầng kiến trúc:

```bash
# Chạy toàn bộ kiểm thử đơn vị và khoa học
pytest tests/unit tests/scientific -q
```

Kết quả:
```text
425 passed, 1 warning in ~20s
```

### Các nhóm kiểm thử trọng tâm:
1. **Kiểm thử hợp đồng & schema V6:** Kiểm tra tính toàn vẹn của `document.json`, `extraction.json`, kiểm tra ràng buộc spans, tính duy nhất của ID ổn định (`test_v6_structure.py`, `test_v6_honest_outputs.py`).
2. **Kiểm thử rào chắn số liệu (Numeric Guard):** Bảo đảm không biến đổi các định dạng số âm, ngoặc kế toán, tỷ lệ %, mã văn bản và đơn vị tiền tệ (`test_v6_numeric_guard.py`).
3. **Kiểm thử bộ điều hợp bố cục (Layout Adapters):** Kiểm tra tính đúng đắn về hình học và ma trận chuyển đổi tọa độ của YOLO và RT-DETR (`test_v6_layout_adapters.py`).
4. **Kiểm thử phân mảnh & Runtime:** Kiểm tra phân chia shard, merge shard và ghi nguyên tử (`test_v6_runtime.py`, `test_v6_conversion_timing.py`).
5. **Kiểm thử đo lường khoa học:** Phân biệt tường minh `MEASURED`, `NOT_EVALUATED`, và phạt tối đa đối với `MISSING_OUTPUT` (`test_v6_evaluation_protocol.py`).

---
