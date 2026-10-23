# OCR PDF — Một pipeline xử lý và thống kê từ khóa

Dự án chuyển PDF tiếng Việt thành Markdown, JSON có bằng chứng và Excel từ khóa.
Kiến trúc vận hành duy nhất lấy pipeline V6.3 toàn trang làm nền:

**PDF → OCR GPU → kết thúc pha A → Docling GPU → export CPU → keyword → Excel riêng → SQLite và ma trận → PDF tiếp theo.**

Thiết kế được viết trước cập nhật tại [ARCHITECTURE.md](ARCHITECTURE.md). Một nguồn cấu hình: [config/profiles.yaml](config/profiles.yaml), một profile `unified_gpu_full_ocr`. Các tên file cấu hình theo phiên bản chỉ tham chiếu về file chuẩn. Tên profile/file/hardware không chọn backend khác.

Tài liệu đầy đủ: [bản Word thiết kế và vận hành hợp nhất](docs/Tai_lieu_thiet_ke_va_van_hanh_OCR_PDF_HOP_NHAT.docx). Kết quả kiểm chứng nằm trong [IMPLEMENTATION_REPORT.md](IMPLEMENTATION_REPORT.md) và [evidence có thể đọc bằng máy](benchmark/evidence/unified_architecture_20261023.json). Các báo cáo ghi trạng thái tại thời điểm kiểm thử trước khi tạo commit công bố.

## 1 Yêu cầu và cách cài

- Python **3.11** cho hai worker GPU; metadata hỗ trợ `>=3.10,<3.13`.
- NVIDIA CUDA; driver tương thích wheel CUDA 12.6 đã khóa; `nvidia-smi` hoạt động.
- Windows hoặc Linux với lock tương ứng trong `requirements/v62`.
- Checkout/editable install cho OCR GPU; extra `app` hỗ trợ điều phối/analysis CPU.
- Model và dependency nhiều GB; dung lượng thực tế phụ thuộc PDF/model. Không có định mức tải dài đã nghiệm thu.

CPU chạy điều phối, export, đếm từ khóa và analysis. OCR mới yêu cầu CUDA; thiếu GPU sẽ báo lỗi, không đổi sang native-first/CPU. Hai môi trường model của cùng pipeline được tách để tránh xung đột dependency:

| Môi trường | Công việc |
| --- | --- |
| `.venv` | CLI CPU, SQLite, keyword, Excel |
| `.venv-v62/text` | ONNX detector CUDA, VietOCR và Heron layout |
| `.venv-v62/docling` | Docling TableFormer và CodeFormula CUDA |

Tên `v62` của runtime/lock/model registry được giữ để tái sử dụng tài nguyên đã cài; không phải một pipeline vận hành thứ hai. Không cài ORT CPU/RapidOCR CPU vào worker GPU.

Windows PowerShell từ gốc repository:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[app]" uv
$env:PATH = "$PWD\.venv\Scripts;" + $env:PATH
nvidia-smi
.\.venv\Scripts\python.exe scripts/setup_v62.py --python 3.11 --env-root .venv-v62
```

Linux dùng `python3.11 -m venv .venv` và `.venv/bin/python`. `setup_v62.py` chọn lock theo hệ điều hành, kiểm hash và phép toán CUDA; xem `--sync` khi lượt cài trước dang dở. Lệnh cài extra app theo khoảng phiên bản; lock CPU supervisor ở `requirements/v63`.

## 2 Chuẩn bị model đúng revision


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


## 3 Preflight và chạy

Chuẩn bị PDF trong `inputs/`. V6.3 nhận `.pdf`/`.PDF` trực tiếp trong thư mục, không quét thư mục con. Stem tên phải khác nhau sau NFC/casefold. Cùng nội dung khác tên vẫn có thể có hàng riêng với `duplicate_of`.

```powershell
.\.venv\Scripts\python.exe scripts/preflight_v62.py --device cuda --env-root .venv-v62 --output scratch/preflight.json
.\.venv\Scripts\python.exe run_ocr.py inputs/bao_cao.pdf --output output/unified_one
.\.venv\Scripts\python.exe run_batch.py --input inputs --output output/unified_batch
```

`ocrpdf`, `ocrpdf-batch`, `ocrpdf-gpu` và launcher cũ đều gọi cùng CLI. `--workers` là 1; OCR xử lý toàn bộ tài liệu. Có thể dùng `--assets png|jpeg|none`, `--output-mode compact|legacy`. `legacy` ở output mode chỉ là JSON đầy đủ, không chọn backend. Xem `run_ocr.py --help`/`run_batch.py --help`.

Preflight chỉ kiểm capability. Model/device thật phải được xác nhận trong receipt/metadata inference trên PDF. Không suy độ chính xác từ preflight, PASS artifact hoặc SUCCEEDED.

## 4 Resume và phân tích từ khóa

```powershell
.\.venv\Scripts\python.exe run_batch.py --input inputs --output output/unified_batch --resume
.\.venv\Scripts\python.exe run_batch.py --input inputs --output output/unified_batch --resume --retry-failed
.\.venv\Scripts\python.exe run_batch.py --output output/unified_batch --recount
.\.venv\Scripts\python.exe run_batch.py --analysis-from output/unified_batch --output output/analysis_01 --keywords-file config/tu_khoa_rieng.txt --keyword-set-version custom-v1
```

Resume giữ input/config/keyword/code/model/runtime đã khóa. Truyền lại tùy chọn cũ như assets/env-root. `--force-ocr` không thay `--retry-failed` với hàng lỗi. Sau cập nhật source/config dùng output mới; không sửa receipt hoặc SQLite để ép resume batch cũ.

Analysis dùng CPU, nhận batch/tài liệu/analysis V6.3 có đủ artifact/receipt; tạo output mới và giữ nguồn chỉ đọc. Markdown rời không đủ. Recount tại chỗ giữ dictionary khóa và có thể yêu cầu runtime/source cũ. Recount/analysis không sửa lỗi OCR trên Markdown cũ.

`literal_v1` đếm toàn `result.md`, NFC rồi casefold, chuỗi con chính xác không chồng lấn trong mỗi keyword. Không fuzzy, bỏ dấu, gộp khoảng trắng hoặc gộp `hóa` với `hoá`. Bộ v1 có 88 vị trí và 87 cụm duy nhất; `Internet di động` lặp hai vị trí cùng số đếm. Phân biệt tổng canonical và display. Bộ riêng dùng version khác v1.

## 5 Đầu ra và kiểm tra

```text
output/unified_batch/
  batch_state.sqlite
  batch_input_manifest.json
  batch_config.json
  keyword_dictionary.snapshot.json
  batch_report.json
  MA_TRAN_DEM_TU_KHOA_<N>_FILES.xlsx
  logs/
  <ten_pdf>/
    result.md                 result.json
    document.md               document.json
    extraction.json           structure.json
    layout_order.json         furniture.json
    quality.json              validation.json
    manifest.json             ocr_receipt.json
    keyword_counts.json       keyword_receipt.json
    keyword_validation.json   count_keywords.xlsx
    COMPLETED.json
    pages/ images/ structures/
```

`result.md` là nguồn đếm, `document.md` có cây mục; compact JSON tham chiếu trang. JSON giữ text_raw, bbox, source ID, thiết bị và provenance. HTML bảng/LaTeX công thức giúp kiểm ngoài Markdown. Ảnh/cấu trúc chỉ có khi tương ứng nội dung và tùy chọn.

| Trạng thái | Cách hiểu |
| --- | --- |
| PENDING hoặc FAILED_DOCUMENT, ô trống | Chưa có số đếm được công bố; không thay bằng 0 |
| SUCCEEDED và số 0 | Đã đếm hợp lệ, keyword không xuất hiện |
| validation PASS | Đạt điều kiện artifact mà validator kiểm |
| NEEDS_REVIEW | Có vùng/chất lượng cần người kiểm |
| quality_acceptance NOT_EVALUATED | Chưa nghiệm thu độ chính xác trên GT độc lập |

Sau mỗi tài liệu: đọc kiểm Excel riêng → prepare SQLite → ghi/đọc kiểm ma trận → acknowledge revision rồi mới sang PDF tiếp. Lỗi publication/identity chặn batch. Đóng Excel trước khi resume nếu file đang mở.

```powershell
.\.venv\Scripts\python.exe scripts/audit_batch_outputs.py --output output/unified_batch --report scratch/audit.json --validate
```

Audit chỉ đọc; report phải ngoài batch. Đối chiếu số trang, dấu tiếng Việt, số/đơn vị, bảng, công thức và thứ tự cột với PDF. Sao lưu toàn batch khi đã dừng ghi. Không chỉ giữ Excel nếu còn cần truy vết/resume.

## 6 Thuật toán và giới hạn

- Detector PP OCRv4 ONNX đọc toàn trang, VietOCR VGG seq2seq nhận dạng dòng, Heron phân vùng; có telemetry CUDA thật.
- Retry dấu 300 DPI có ngân sách, CLAHE/candidate score và numeric guard; giữ text_raw. Tập quy tắc dấu nhỏ, không là kiểm chính tả tổng quát.
- Docling đọc bridge ảnh cùng chữ OCR ẩn, không sao chép native layer; TableFormer/CodeFormula có review khi chưa có confidence hiệu chuẩn.
- Region tree và graph giải thứ tự; furniture theo bằng chứng liên trang; cây mục heuristic tối đa bốn cấp.
- Kiểm tài chính chỉ gắn cờ, không sửa số; chưa tự nối bảng nhiều trang thành kết quả đã xác minh.
- Độ chính xác GT độc lập và tải thực dài 500 PDF chưa nghiệm thu. Fixture 500 hàng trong test không là 500 PDF inference.

## 7 Kaggle và chuyển đổi lệnh cũ

Notebook duy nhất để chạy là [kaggle/ocr_pdf_kaggle.ipynb](kaggle/ocr_pdf_kaggle.ipynb). Bật Internet/GPU, thêm dataset, kiểm INPUT_ROOT/FILE_LIMIT/RESULTS_DIR rồi Run All. Nó dùng cùng config/CLI/receipt, một GPU/worker. Notebook tên v63 cũ chỉ giữ hướng dẫn chuyển đổi. Đổi code chọn output mới; tải ZIP hoặc Save Version trước khi phiên kết thúc.

Backend `legacy`, profile `fast/local/balanced/accuracy/unified_gpu`, chọn trang và launcher V6.2 không còn chọn đường native-first. Dùng CLI chuẩn và `unified_gpu_full_ocr`. Cấu hình baseline/nghiên cứu cũ ở [benchmark/baselines](benchmark/baselines); không dùng làm runtime default. API ConvertDocumentUseCase cũ chỉ nhận baseline chỉ định rõ để kiểm hồi quy.

## 8 Phát triển và kiểm thử

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[legacy,test,dev]"
.\.venv\Scripts\python.exe scripts/run_pytest_scratch.py tests/unit tests/scientific tests/legacy_compat -q -ra
```

Extra legacy trong lệnh kiểm thử chỉ cấp dependency cho thuật toán baseline, không mở backend legacy. Không cài extra đó vào worker GPU. Wrapper lưu evidence dưới scratch/runs. Integration/golden cần dữ liệu thật và có thể skip khi thiếu. CI GPU/model vẫn cần runner/runtime/model được chuẩn bị riêng.

Ranh giới package được kiểm bằng import-linter; workers không được import src.ocr hoặc finalizer keyword. Xem ARCHITECTURE.md, README từng package và báo cáo kiểm chứng sau cập nhật.
