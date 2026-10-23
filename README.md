# OCR — Xử lý PDF tiếng Việt và thống kê từ khóa

Chuyển PDF tiếng Việt thành **Markdown, JSON và Excel từ khóa**, dành cho báo cáo thường niên, báo cáo tài chính và tài liệu có bảng biểu.

Repository: [VuTuanAn1403/OCR](https://github.com/VuTuanAn1403/OCR) · Phiên bản mã nguồn: **`6.3.0.dev1`** (đang phát triển).

Pipeline mặc định V6.3 nhận dạng toàn bộ trang trên GPU, dựng cấu trúc bằng Docling, xuất kết quả từng PDF và cập nhật ma trận từ khóa có trạng thái SQLite. Máy không có NVIDIA CUDA có thể sử dụng backend `legacy` trên CPU.

## Mục lục

- [1. Chọn cách chạy](#1-chọn-cách-chạy)
- [2. Yêu cầu](#2-yêu-cầu)
- [3. Clone và tạo môi trường](#3-clone-và-tạo-môi-trường)
- [4. Chạy thử trên CPU](#4-chạy-thử-trên-cpu)
- [5. Thiết lập V6.3 GPU](#5-thiết-lập-v63-gpu)
- [6. Chạy một PDF hoặc cả thư mục](#6-chạy-một-pdf-hoặc-cả-thư-mục)
- [7. Từ khóa và đếm lại kết quả](#7-từ-khóa-và-đếm-lại-kết-quả)
- [8. Chạy trên Kaggle](#8-chạy-trên-kaggle)
- [9. Kết quả đầu ra](#9-kết-quả-đầu-ra)
- [10. Cấu trúc và phát triển](#10-cấu-trúc-và-phát-triển)
- [11. Lỗi thường gặp](#11-lỗi-thường-gặp)
- [12. Quản lý mã nguồn trên GitHub](#12-quản-lý-mã-nguồn-trên-github)

## 1. Chọn cách chạy

| Nhu cầu | Cách chạy | Cài đặt |
| --- | --- | --- |
| Thử nhanh một vài trang bằng CPU | `--backend legacy --profile fast --device cpu` | Extra `legacy`; không cần Docling |
| OCR tiếng Việt bằng VietOCR trên CPU | `--backend legacy --profile local --device cpu` | Extra `legacy` và trọng số VietOCR |
| OCR toàn bộ tài liệu trên GPU | Backend mặc định V6.3 | Extra `app`, hai worker GPU và model đã khóa |
| Chạy trên GPU của Kaggle | Notebook `ocr_pdf_v63_kaggle.ipynb` | Bật GPU, Internet và thêm dataset PDF |
| Đếm từ khóa trên output V6.3 đã có | `--analysis-from` | Extra `app`; không chạy lại OCR |
| Chỉ đếm từ output legacy đã có | `scripts/run_count_only.py` | Extra `reporting` |

**V6.3 yêu cầu CUDA và xử lý nguyên tài liệu với một worker.** Các tùy chọn `--pages`, `--limit`, `--files`, `--shard` và nhiều worker thuộc CLI legacy. Chọn `--output-mode legacy` chỉ thay định dạng JSON, không chuyển backend.

## 2. Yêu cầu

| Thành phần | Yêu cầu |
| --- | --- |
| Python | Khuyến nghị **3.11**. Metadata hỗ trợ `>=3.10,<3.13`; lock GPU yêu cầu Python 3.11 |
| Git | Dùng để clone và cập nhật mã nguồn |
| CPU | Backend legacy; có thể thử trước mà không cần GPU |
| GPU V6.3 | NVIDIA CUDA, driver phù hợp với wheel CUDA 12.6; `nvidia-smi` hoạt động |
| Hệ điều hành GPU | Có lock cho Windows và Linux; macOS không hỗ trợ backend NVIDIA CUDA này |
| Internet và dung lượng | Cần tải dependency, trọng số và cache nhiều GB; dung lượng thực tế tùy bộ model/PDF |

Trọng số, PDF đầu vào và output thực tế **không đi kèm repository**. Người dùng tự chuẩn bị PDF; các ví dụ dưới dùng tên `inputs/bao_cao.pdf`.

Test phần mềm và validator kiểm hành vi/hợp đồng dữ liệu. Độ chính xác OCR trên ground truth độc lập và khả năng chạy tải dài 500 PDF chưa được nghiệm thu. Kết quả cần kiểm tra có thể mang trạng thái `NEEDS_REVIEW`.

## 3. Clone và tạo môi trường

### Windows — PowerShell

```powershell
git clone https://github.com/VuTuanAn1403/OCR.git
cd OCR
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

Nếu PowerShell chặn kích hoạt venv, có thể gọi trực tiếp `.\.venv\Scripts\python.exe` thay cho `python`. Với phần GPU, `uv` cũng cần có trong `PATH` hoặc được gọi bằng đường dẫn `.\.venv\Scripts\uv.exe`.

### Linux — Bash

```bash
git clone https://github.com/VuTuanAn1403/OCR.git
cd OCR
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

Tiếp tục với **mục 4 cho CPU** hoặc **mục 5 cho GPU**. Chạy các lệnh từ thư mục gốc repository. Không dùng Python 3.13 trở lên cho dự án này.

## 4. Chạy thử trên CPU

### 4.1. Cài và xử lý trang đầu

```powershell
python -m pip install -e ".[legacy]"
python -c "from pathlib import Path; Path('inputs').mkdir(exist_ok=True)"
```

Chép PDF của bạn thành `inputs/bao_cao.pdf`, rồi chạy:

```powershell
python run_ocr.py inputs/bao_cao.pdf --backend legacy --profile fast --device cpu --pages 1 --assets none --output output/quickstart
```

Đọc `output/quickstart/bao_cao/result.md`, `validation.json` và `count_keywords.xlsx`. Profile `fast` dùng RapidOCR CPU với model trong package; không cần tải VietOCR hoặc Docling cho bước này. Với PDF có text layer đủ chất lượng, backend legacy ưu tiên trích xuất chữ có sẵn.

### 4.2. Dùng VietOCR cho tiếng Việt

```powershell
python scripts/setup_vietocr_model.py
python run_ocr.py inputs/bao_cao.pdf --backend legacy --profile local --device cpu --pages 1-3 --output output/local
```

Trọng số được chuẩn bị trong `models/vietocr/`; lần tải đầu cần Internet. Có thể kiểm tra đầy đủ stack legacy bằng `python scripts/setup_models.py` và `python scripts/check_installation.py`.

### 4.3. Chạy lô CPU

```powershell
python run_batch.py --backend legacy --input inputs --output output/legacy_batch --profile local --device cpu --workers 1 --limit 3
python run_batch.py --backend legacy --help
```

Profile legacy `balanced` và `accuracy` bật Docling, cần thiết lập thêm môi trường Docling riêng. Để thử trên CPU, bắt đầu bằng `fast` hoặc `local`. Tên profile `accuracy` không phải chứng nhận độ chính xác.

## 5. Thiết lập V6.3 GPU

### 5.1. Tách supervisor và hai worker

| Môi trường | Vai trò |
| --- | --- |
| `.venv` | CLI, điều phối CPU, SQLite, đếm từ khóa và xuất Excel |
| `.venv-v62/text` | Detector ONNX CUDA, VietOCR và layout |
| `.venv-v62/docling` | Docling TableFormer/CodeFormula trên CUDA |

Tên `.venv-v62` được giữ vì V6.3 tái sử dụng runtime GPU V6.2. Supervisor không cần cài Torch hoặc Docling. Hai worker phải dùng dependency lock riêng; không cài lẫn `onnxruntime`, `onnxruntime-gpu` và `rapidocr-onnxruntime` trong chúng.

```powershell
python -m pip install -e ".[app]" uv
nvidia-smi
python scripts/setup_v62.py --python 3.11 --env-root .venv-v62
```

Script dùng `uv`, chọn lock Windows/Linux trong [requirements/v62](requirements/v62), kiểm hash package và chạy phép toán CUDA. Nếu lượt cài trước dang dở, chạy lại với `--sync`. Tùy chọn `--http1-downloads` hỗ trợ tải qua wheelhouse có kiểm hash khi proxy gây lỗi.

Dependency supervisor được mô tả trong [pyproject.toml](pyproject.toml); lock CPU theo hệ điều hành ở [requirements/v63](requirements/v63). `pip install -e ".[app]"` ở trên cài theo khoảng phiên bản của extra, không tự áp dụng lock CPU.

### 5.2. Tải trọng số đúng revision

Nguồn chuẩn là [models/v62/runtime-models.json](models/v62/runtime-models.json): đường dẫn, revision và SHA-256 từng file. Git chỉ giữ cấu hình/registry, không giữ trọng số.

```powershell
python scripts/setup_vietocr_model.py
python -m pip download --no-deps --only-binary=:all: rapidocr-onnxruntime==1.4.4 --dest scratch/model-wheels
```

Lệnh `pip download` chỉ lấy wheel để trích detector, không cài RapidOCR CPU vào worker GPU. Lưu đoạn Python sau thành **`scratch/download_gpu_models.py`**:

```python
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

from huggingface_hub import snapshot_download

root = Path.cwd()
registry = json.loads((root / "models/v62/runtime-models.json").read_text(encoding="utf-8"))
wheels = list((root / "scratch/model-wheels").glob("rapidocr_onnxruntime-1.4.4-*.whl"))
if len(wheels) != 1:
    raise RuntimeError("Can dung mot wheel RapidOCR 1.4.4 trong scratch/model-wheels")
with ZipFile(wheels[0]) as archive:
    candidates = [name for name in archive.namelist()
                  if name.endswith("/ch_PP-OCRv4_det_infer.onnx")]
    if len(candidates) != 1:
        raise RuntimeError("Khong tim thay duy nhat detector trong wheel")
    detector = root / registry["text_detector"]["model_path"]
    detector.parent.mkdir(parents=True, exist_ok=True)
    detector.write_bytes(archive.read(candidates[0]))

hub = root / "models/docling/huggingface/hub"
for role, model in registry["snapshots"].items():
    snapshot_download(model["repo"], revision=model["revision"], cache_dir=str(hub))
    ref = hub / ("models--" + model["repo"].replace("/", "--")) / "refs"
    ref = ref / ("v2.3.0" if role == "table" else "main")
    ref.parent.mkdir(parents=True, exist_ok=True)
    ref.write_text(model["revision"], encoding="utf-8")

for relative, expected in registry["files"].items():
    path = root / relative
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise RuntimeError(f"Model hash mismatch: {relative}")
print("All locked model files verified")
```

Chạy bằng Python của **worker Docling**, nơi đã có `huggingface_hub`:

```powershell
# Windows
.\.venv-v62\docling\Scripts\python.exe scratch/download_gpu_models.py
```

```bash
# Linux
.venv-v62/docling/bin/python scratch/download_gpu_models.py
```

Các snapshot layout, bảng và công thức có thể chiếm nhiều GB. Script xác minh file theo registry hiện có; nếu hash không khớp, kiểm tra đúng file/revision và tải lại. `scripts/prepare_v62_models.py` chỉ ghi registry từ các model đã có, không tải model; tạo lại registry làm thay đổi nhận dạng runtime và cần output batch mới.

### 5.3. Kiểm tra trước khi chạy

```powershell
python scripts/preflight_v62.py --device cuda --env-root .venv-v62 --output scratch/gpu-preflight.json
```

Preflight kiểm môi trường CUDA/provider. Nó không thay thế inference trên PDF thật hoặc phép đo độ chính xác. V6.3 cần chạy từ checkout/editable install; wheel độc lập chưa hỗ trợ backend GPU này.

## 6. Chạy một PDF hoặc cả thư mục

Sau khi hoàn tất mục 5:

```powershell
# Một PDF, xử lý toàn bộ trang.
python run_ocr.py inputs/bao_cao.pdf --output output/mot_tai_lieu

# Mọi PDF nằm trực tiếp trong inputs/.
python run_batch.py --input inputs --output output/v63

# Giảm dung lượng ảnh xuất ra.
python run_batch.py --input inputs --output output/v63_no_assets --assets none
```

V6.3 nhận `.pdf`/`.PDF`, không quét thư mục con. Stem tên PDF phải khác nhau sau chuẩn hóa Unicode và hoa/thường. Cùng nội dung PDF có thể có hàng riêng, với metadata `duplicate_of`.

Sau khi cài editable, `ocrpdf` và `ocrpdf-batch` tương đương hai script; `ocrpdf-gpu` là alias của CLI một PDF.

Để mỗi lượt GPU tự tạo thư mục output mới, dùng:

```powershell
python scripts/run_gpu_pipeline.py --input inputs
```

Script in đường dẫn output đã chọn. Tiếp tục lượt đó bằng `--output <thu_muc_da_in> --resume`; các tùy chọn V6.3 khác được chuyển tới CLI chính.

### Tiếp tục hoặc thử lại

```powershell
python run_batch.py --input inputs --output output/v63 --resume
python run_batch.py --input inputs --output output/v63 --resume --retry-failed
python run_batch.py --input inputs --output output/v63 --resume --force-ocr
```

Batch khóa input, cấu hình, keyword, mã nguồn và runtime/model ở lần đầu. Khi resume, giữ nguyên chúng và truyền lại tùy chọn đã dùng như `--assets none` hoặc `--env-root`. `--force-ocr` không thay `--retry-failed` đối với tài liệu đã lỗi. Thêm PDF, đổi code/model hoặc đổi cấu hình thì chọn output mới.

Kiểm tra tính toàn vẹn, số trang và nguồn OCR của một batch đã có:

```powershell
python scripts/audit_batch_outputs.py --output output/v63 --report scratch/v63-audit.json --validate
```

Báo cáo phải nằm ngoài thư mục batch. Công cụ chỉ đọc batch, không sửa receipt/SQLite hoặc chạy OCR; kiểm tra này không đo độ chính xác nhận dạng.

| Tùy chọn V6.3 | Mặc định / ý nghĩa |
| --- | --- |
| `--backend` | `gpu_two_phase` |
| `--config` | `config/profiles-v63.yaml` |
| `--profile` | `unified_gpu_full_ocr` |
| `--device` | `cuda` |
| `--env-root` | `.venv-v62` trong repository |
| `--output` | `output/v63` trong repository |
| `--workers` | `1` |
| `--max-attempts` | `2`, cho lỗi worker được phân loại có thể thử lại |
| `--assets` | `png`; có thể chọn `jpeg` hoặc `none` |
| `--output-mode` | `compact`; `legacy` nhúng toàn bộ trang trong `result.json` |

Xem toàn bộ tham số bằng `python run_batch.py --help` và `python run_ocr.py --help`. Nên ghi rõ `--backend legacy` khi dùng profile/lệnh CPU cũ.

## 7. Từ khóa và đếm lại kết quả

Bộ mặc định [config/keywords.txt](config/keywords.txt) có **88 vị trí hiển thị, 87 cụm từ duy nhất**: `Internet di động` xuất hiện hai lần. Hai vị trí này có cùng số đếm.

Chính sách `literal_v1` đọc `result.md`, chuẩn hóa NFC và `casefold`, sau đó đếm chuỗi con chính xác, không chồng lấn trong từng keyword. Nó giữ dấu và khoảng trắng, không fuzzy, stemming, LLM hoặc tự gộp `hóa` với `hoá`. Toàn bộ Markdown, kể cả tiêu đề, bảng và đường dẫn ảnh, thuộc nguồn đếm.

Excel riêng giữ 88 dòng keyword; ma trận có 88 cột keyword và một cột tên PDF. Tổng theo keyword duy nhất (`total_canonical_matches`) có thể khác tổng theo vị trí hiển thị (`total_display_matches`).

### Dùng bộ từ khóa riêng

Tạo file UTF-8, mỗi dòng một cụm từ, rồi đặt version khác `v1`:

```powershell
python run_batch.py --input inputs --output output/custom_keywords --keywords-file config/tu_khoa_rieng.txt --keyword-set-version custom-v1
```

### Đếm lại batch V6.3 với bộ keyword đã khóa

```powershell
python run_batch.py --output output/v63 --recount
```

Lệnh giữ OCR hợp lệ nhưng kiểm nhận dạng runtime/source và có thể cần phục hồi artifact. Giữ PDF gốc và môi trường cũ; nếu code đã đổi, dùng analysis run dưới đây.

### Đổi keyword trên output V6.3, không OCR lại

```powershell
python run_batch.py --analysis-from output/v63 --output output/analysis_moi --keywords-file config/tu_khoa_rieng.txt --keyword-set-version custom-v1
```

Analysis run cần extra `app`, không cần worker/model GPU. Nguồn có thể là thư mục batch, tài liệu hoặc analysis run trước. Lệnh kiểm receipt/hash và bằng chứng hoàn tất, giữ nguyên thư mục nguồn, xuất bộ kết quả mới cùng `source.json` ghi nguồn gốc. Output nguồn phải còn đầy đủ artifact; một file Markdown rời không đủ cho đường này.

### Chỉ đếm từ output legacy

```powershell
python -m pip install -e ".[reporting]"
python scripts/run_count_only.py output/quickstart/bao_cao
```

Nếu target khai báo V6.3, script chuyển sang recount toàn batch với snapshot đã khóa.

## 8. Chạy trên Kaggle

- GPU V6.3: [kaggle/ocr_pdf_v63_kaggle.ipynb](kaggle/ocr_pdf_v63_kaggle.ipynb).
- Legacy/CPU: [kaggle/ocr_pdf_kaggle.ipynb](kaggle/ocr_pdf_kaggle.ipynb).

Với notebook V6.3:

1. Import notebook vào Kaggle, bật **Internet** và chọn **GPU**.
2. Add Input dataset PDF; kiểm tra `INPUT_ROOT`, `PDF_FILES` và `FILE_LIMIT` ở cell cấu hình.
3. Giữ `REPO_URL = "https://github.com/VuTuanAn1403/OCR.git"`, `REPO_REF = "main"`.
4. Lần đầu nên đặt `FILE_LIMIT = 1` và chọn `RESULTS_DIR` riêng để thử một tài liệu; chạy các cell từ đầu theo thứ tự.
5. Để chạy đủ dataset, đặt `FILE_LIMIT = None`, `PDF_FILES = []`, `RUN_FULL_BATCH = True` và chọn thư mục kết quả mới.
6. Tải ZIP hoặc Save Version trước khi phiên kết thúc.

Notebook tự chuẩn bị runtime/model. Kết quả mặc định ở `/kaggle/working/ocr_pdf_v63_results/`; batch và ma trận ở thư mục con `documents/`; ZIP là `/kaggle/working/ocr_pdf_v63_results.zip`. Runtime/model nằm ngoài ZIP. Notebook dùng một GPU/worker, không tự chia qua hai GPU.

`STAGED_INPUT` được tạo khi cell chọn input thành công. Nếu gặp `NameError`, chạy lại từ cell cấu hình bằng **Run All** và xử lý lỗi chọn PDF trước. Khi đổi code, dùng `REFRESH_SOURCE = True` với output mới; batch cũ khóa nhận dạng mã nguồn. Resume qua lúc Kaggle xóa runtime chưa được bảo đảm.

## 9. Kết quả đầu ra

```text
output/v63/
├── batch_state.sqlite
├── batch_input_manifest.json
├── batch_config.json
├── keyword_dictionary.snapshot.json
├── batch_report.json
├── MA_TRAN_DEM_TU_KHOA_<N>_FILES.xlsx
├── logs/
└── <ten_pdf>/
    ├── result.md                    # Nguồn đếm từ khóa
    ├── result.json                  # Chỉ mục trang hoặc dữ liệu đầy đủ
    ├── document.md
    ├── extraction.json              # Phần tử, tọa độ, nguồn/bằng chứng
    ├── structure.json               # Cây mục
    ├── document.json                # Sections, chunks, bảng, tham chiếu
    ├── quality.json
    ├── validation.json
    ├── manifest.json
    ├── ocr_receipt.json
    ├── keyword_counts.json
    ├── keyword_validation.json
    ├── keyword_receipt.json
    ├── count_keywords.xlsx
    ├── COMPLETED.json
    ├── pages/
    ├── images/
    └── structures/
```

Ma trận có các sheet `Ma trận từ khóa`, `Trạng thái`, `Tệp lỗi`, `Tổng quan`, `Thông tin`.

| Trạng thái / giá trị | Ý nghĩa |
| --- | --- |
| `PENDING`, ô trống | Chưa công bố kết quả |
| `FAILED_DOCUMENT`, ô trống | Tài liệu lỗi; xem sheet lỗi/log |
| `SUCCEEDED`, số `0` | Đã đếm, không tìm thấy keyword đó |
| `validation: PASS` | Artifact hợp lệ theo validator |
| `validation: NEEDS_REVIEW` | Có vùng/chất lượng cần kiểm tra |
| `quality_acceptance: NOT_EVALUATED` | Chưa nghiệm thu trên ground truth độc lập |

Sau mỗi tài liệu, pipeline ghi và đọc kiểm Excel rồi xác nhận revision SQLite trước khi xử lý PDF kế tiếp. Lỗi xuất workbook chặn batch; đóng file Excel đang mở trước khi resume. Nếu Docling fallback, kết quả được giữ cùng trạng thái cần review.

Sao lưu cả thư mục batch, gồm SQLite, receipt và manifest, khi không còn tiến trình ghi. Không chỉ sao chép file Excel nếu cần resume hoặc kiểm nguồn gốc.

## 10. Cấu trúc và phát triển

```text
OCR/
├── run_ocr.py / run_batch.py   # CLI
├── pyproject.toml             # Package, extras, import contracts
├── src/
│   ├── ocr_contracts/         # Model/schema/protocol
│   ├── ocr_artifacts/         # Hash, ghi nguyên tử, completion
│   ├── ocr_text/              # Unicode và numeric guard
│   ├── ocr_keywords/          # Từ điển và đếm literal
│   ├── ocr_reporting/         # Excel
│   ├── ocr_runtime/           # Config, paths, model/runtime identity
│   ├── ocr_pdf_io/            # Inspect, render, crop PDF
│   ├── ocr_recognition/       # Detector, VietOCR, chất lượng chữ
│   ├── ocr_layout/            # Layout adapters
│   ├── ocr_structure/         # Docling client, bảng/công thức
│   ├── ocr_document/          # Ghép trang, cấu trúc, export
│   ├── ocr_pipeline/          # Supervisor CPU, batch, analysis
│   ├── ocr_workers/           # Các pha GPU và Docling server
│   └── ocr/                   # Legacy và alias src.ocr.*
├── config/                   # Profile và keyword
├── models/                   # Cấu hình/registry; trọng số cục bộ
├── assets/fonts/             # Font tiếng Việt cho PDF trung gian
├── requirements/v62/         # Lock hai worker GPU
├── requirements/v63/         # Lock CPU app
├── scripts/                  # Setup, preflight, kiểm thử, benchmark
├── tests/                    # Unit, scientific, integration, golden
├── benchmark/                # Metric, protocol, evidence chọn lọc
└── kaggle/                   # Notebook
```

Luồng V6.3: **PDF → worker nhận dạng GPU → kết thúc pha A → worker Docling GPU → export CPU → đếm keyword → Excel riêng → xác nhận ma trận → PDF tiếp theo**. Hai pha GPU chạy tuần tự và phải kết thúc cây tiến trình trước khi bàn giao tài nguyên.

Hướng dẫn từng package: [pipeline và CLI](src/ocr_pipeline/README.md), [runtime và cấu hình](src/ocr_runtime/README.md), [đếm từ khóa](src/ocr_keywords/README.md), [xuất Excel](src/ocr_reporting/README.md).

### Kiểm thử

```powershell
# Package nhẹ và reporting; không cần model/GPU.
python -m pip install -e ".[reporting]" pytest
python scripts/run_pytest_scratch.py tests/unit/contracts tests/unit/artifacts tests/unit/text tests/unit/keywords tests/unit/reporting -q

# Pipeline/analysis dùng fixture, không inference GPU.
python -m pip install -e ".[app,dev]" pytest
python scripts/run_pytest_scratch.py tests/unit/document tests/unit/runtime tests/unit/test_v63_pipeline.py tests/unit/test_analysis_run.py tests/unit/test_import_contracts.py -q

# Regression đầy đủ: cần stack legacy/test.
python -m pip install -e ".[legacy,test]"
python scripts/run_pytest_scratch.py tests/unit tests/scientific tests/legacy_compat -q -ra
```

Wrapper đặt log, JUnit và thư mục tạm dưới `scratch/runs/<run_id>/`. Integration/golden phụ thuộc PDF/prediction có thể được skip khi thiếu dữ liệu. Xem [workflow CI](.github/workflows/tests.yml): kiểm CPU/package/wheel trên Windows và Ubuntu; model integration và GPU runner cần chọn riêng qua `workflow_dispatch`. GPU runner phải cấu hình `OCR_GPU_SAMPLE_PDF` tới PDF một trang có sẵn ngoài checkout, cùng runtime/model được chuẩn bị trước; CI không tải kèm tài liệu đầu vào.

Công cụ [run_scientific_benchmark.py](scripts/run_scientific_benchmark.py) và [scientific_evaluation](benchmark/scientific_evaluation) hỗ trợ đánh giá OCR, số, bảng, layout và thứ tự đọc. Cần ground truth độc lập và protocol rõ ràng trước khi công bố chỉ số chất lượng.

## 11. Lỗi thường gặp

| Hiện tượng | Cách xử lý |
| --- | --- |
| Cài lỗi với Python 3.13/3.14 | Tạo venv Python 3.11 |
| Không nhận `uv` | Kích hoạt `.venv` hoặc gọi `.venv/Scripts/uv.exe` trên Windows |
| `Missing locked GPU environment` | Chạy `setup_v62.py`, kiểm `--env-root` và hai worker |
| `Torch CUDA unavailable`, thiếu `CUDAExecutionProvider` | Kiểm driver, `nvidia-smi`, lock và preflight; loại dependency ORT CPU cài nhầm trong worker |
| `MODEL_LOCK_MISMATCH`, thiếu snapshot | Kiểm path/revision/hash trong registry, tải đúng model |
| `IdentityMismatch`, `Source changed`, `INPUT_CHANGED` | Giữ môi trường/input cũ để resume, hoặc tạo output mới cho phiên bản mới |
| `Batch already exists` | Thêm `--resume` với cấu hình cũ hoặc chọn output mới |
| Lỗi ghi/replace Excel | Đóng workbook đang mở; kiểm quyền và dung lượng rồi resume |
| `GPU_LEASE_BUSY` hoặc batch bị khóa | Kiểm tiến trình đang chạy GPU/output trước khi chạy lại |
| Không nhận `--pages`/`--limit` | Dùng `--backend legacy` và profile CPU tương ứng |
| Không thấy PDF trong thư mục con | Đặt PDF trực tiếp vào input; notebook Kaggle có bước chọn đệ quy riêng |
| Linux báo thiếu `torch` dù đã setup worker | Cập nhật source/notebook, dùng output mới và kiểm đúng Python trong venv worker |

## 12. Quản lý mã nguồn trên GitHub

Remote chính của dự án là `https://github.com/VuTuanAn1403/OCR.git`. Sau khi clone, kiểm tra bằng:

```powershell
git remote -v
git status --short
```

Nếu đang dùng checkout từ repository cũ và `origin` đã tồn tại:

```powershell
git remote set-url origin https://github.com/VuTuanAn1403/OCR.git
```

[.gitignore](.gitignore) loại venv, cache, `inputs/`, `output/`, `scratch/`, `tmp/`, `docs/`, log, biến môi trường và trọng số (`.pth`, `.pt`, `.onnx`, `.safetensors`...). Cấu hình model/registry và font kèm giấy phép vẫn là tài nguyên cần thiết của mã nguồn. Các fixture/evidence chọn lọc trong `tests/` và `benchmark/` phục vụ kiểm thử.

Khi cập nhật dự án, kiểm danh sách staged trước khi commit/push:

```powershell
git add README.md .gitignore pyproject.toml setup.py MANIFEST.in .gitattributes .github src config requirements scripts tests benchmark kaggle assets run_ocr.py run_batch.py pytest.ini requirements*.txt
git diff --cached --stat
git diff --cached --check
git commit -m "docs: update setup and usage instructions"
git push origin main
```

Chỉ commit các file thuộc thay đổi định đưa lên. File đã được Git theo dõi từ trước không tự bị loại khi thêm quy tắc `.gitignore`; với dữ liệu/trọng số đã tracked, cần xử lý danh sách tracked trước khi publish. GitHub có thể yêu cầu đăng nhập hoặc token để push.

Phần keyword được tích hợp có chọn lọc từ [OCR_pdf_backup](https://github.com/nkatu0704dataengineer/OCR_pdf_backup/tree/05d396763e0c1a099d87adb93661b3f1c9ab48b8). Giấy phép thư viện, model và font theo nguồn tương ứng; repository không gắn nhãn giấy phép khi chưa có file giấy phép dự án.
