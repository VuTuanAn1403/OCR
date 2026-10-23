# Cấu hình, đường dẫn và dữ liệu

Tài liệu này chốt nguồn cấu hình, thứ tự ưu tiên khi resolve đường dẫn, các nhóm dữ liệu cùng cách sao lưu và dọn của dự án (giai đoạn P12). Bảng ưu tiên được test trong `tests/unit/runtime/test_config_and_paths.py`; khi đổi hành vi, sửa cả hai nơi.

Lệnh chẩn đoán chỉ đọc hiển thị toàn bộ lựa chọn đang có hiệu lực:

```powershell
python -m ocr_runtime.diagnose          # bảng dễ đọc
python -m ocr_runtime.diagnose --json   # cho script
python -m ocr_runtime.diagnose --verify-models   # băm thêm mọi file model trong registry (chậm)
```

Lệnh không ghi file, không sửa môi trường và không nạp thư viện model (chỉ dò bằng `importlib.util.find_spec`).

## Nguồn cấu hình

Mỗi loại thông tin có một nguồn được sửa tay. Bản trong wheel (`ocr_runtime/resources`) được chép lúc build từ chính các nguồn này, không sửa riêng.

| Loại | Nguồn | Có mặt trong identity |
| --- | --- | --- |
| Pipeline V6.3 và stage | `config/profiles-v63.yaml`, profile `unified_gpu_full_ocr` | Dict profile trong `ocr_identity`, `generation`, stage key |
| Profile legacy V6.1 | `config/profiles.yaml` | `config_hash` của cache trang legacy |
| Profile V6.2 GPU legacy | `config/profiles-v62.yaml` | Như V6.3, qua `gpu_runner` |
| Phần cứng (batch legacy) | `config/hardware/*.yaml` | Qua cấu hình đã resolve |
| Dependency | `requirements/v62/*-gpu.lock` (worker GPU), `requirements/v63/*-cpu-app.lock` (CPU app) | Hash lock của worker GPU |
| Model registry | `models/v62/runtime-models.json` (revision và sha256 từng file) | `model_hashes`, theo pha trong stage key |
| Font bridge | `assets/fonts/NotoSans-Regular.ttf` hoặc `OCR_BRIDGE_FONT` | Hash trong `model_hashes`, `config.bridge_font` |
| Từ điển keyword | `config/keywords.txt` (v1: 88 dòng, 87 cụm) hoặc `--keywords-file` | `snapshot_sha256` của batch, identity analysis |
| Chính sách đếm | `ocr_contracts.processing` (`literal_v1`, `POLICY_VERSION`) | Identity keyword |
| Analysis run | `run_batch.py --analysis-from ... --output ...` | `source.json`, `keyword_receipt` |
| Đường dẫn lưu trữ | Biến môi trường và tham số CLI bên dưới, không nằm trong profile | Không (trừ đường dẫn tuyệt đối của model/interpreter, xem dưới) |

Phiên bản dependency (lock) và phiên bản model (registry) là hai lớp quản lý tách nhau: đổi lock không đổi registry và ngược lại.

### Khai báo trong file profile

Mỗi file profile khai báo ở đầu file:

```yaml
config_schema: ocr-profiles-v1
pipeline: v6.3        # v6.3 | v6.2 | legacy
profiles:
  ...
```

CLI chọn nhánh theo khai báo, không theo tên file. Thứ tự: `--backend`, rồi `pipeline` của file `--config`. File chưa có khai báo (tạo trước P12) theo quy tắc cũ: tên profile khác `unified_gpu_full_ocr` thì đi legacy, còn tên file có `profiles-v63` thì đi V6.3. Giá trị `config_schema`/`pipeline` không hợp lệ là lỗi. Backend V6.3 từ chối file khai báo pipeline khác. Khai báo nằm ngoài dict profile nên không đổi identity nào.

## Thứ tự ưu tiên đường dẫn

Quy tắc chung: tham số CLI, rồi biến môi trường, rồi mặc định. Giá trị tương đối của CLI và biến môi trường tính theo thư mục làm việc của process đọc nó. Supervisor V6.3 đổi mọi biến đường dẫn sang tuyệt đối trước khi khởi chạy document owner và worker, vì các process này chạy với thư mục làm việc là checkout (`ocr_runtime.paths.absolute_path_env`). Tên Unicode và khoảng trắng được hỗ trợ.

| Mục | Ưu tiên | Mặc định |
| --- | --- | --- |
| Gốc dự án | `OCR_PROJECT_ROOT` | Checkout chứa mã (tìm marker), nếu là wheel thì thư mục làm việc |
| File profile, CLI legacy | `--config` > `OCR_CONFIG_PATH` | `<checkout>/config/profiles.yaml`; wheel: bản đóng gói |
| File profile, CLI V6.3 | `--config` | `<gốc dự án>/config/profiles-v63.yaml`. V6.3 không đọc `OCR_CONFIG_PATH`; notebook V6.3 xoá biến này |
| Từ điển | `--keywords-file` | `config/keywords.txt` khi đang ở checkout, ngược lại bản đóng gói |
| Input/output, CLI legacy | `--input`/`--output` > `OCR_DATA_DIR`/`OCR_OUTPUT_DIR` | `inputs`, `output` theo thư mục làm việc |
| Input/output, CLI V6.3 | `--input`/`--output` | `<gốc dự án>/inputs`, `<gốc dự án>/output/v63` |
| Cache trang legacy | `--cache-dir` > `OCR_CACHE_DIR` | `.cache` theo thư mục làm việc |
| Checkpoint và stage cache V6.3 | `OCR_CACHE_DIR` | `<gốc dự án>/.cache` (`v62-jobs/`, `v63-stages/`) |
| Job Docling | `OCR_CACHE_DIR` | `.cache` của worker, tức `<checkout>/.cache` |
| Model | `OCR_MODELS_DIR` | `<gốc dự án>/models`; VietOCR: `VIETOCR_MODEL_DIR`, mặc định `<models>/vietocr`. Docling hub luôn là `<models>/docling/huggingface`: client đặt `HF_HOME` này cho server Docling, nên `HF_HOME` thừa hưởng không có tác dụng |
| GPU lease | `OCR_GPU_LEASE_DIR` | `<gốc dự án>/.cache/gpu-leases` |

GPU lease không đi theo `OCR_CACHE_DIR`: mọi process dùng chung một GPU phải thấy cùng một thư mục lease, nếu không lease không loại trừ nhau. Khi chạy nhiều checkout hoặc nhiều cache trên cùng máy, đặt cùng một `OCR_GPU_LEASE_DIR` cho tất cả.

### Model đặt ngoài checkout

Registry là nguồn duy nhất của phiên bản model.
- Mỗi file trong registry (`models/...`) được ghim tại đúng chỗ engine nạp nó (`ocr_runtime.paths.registry_model_path`): file `models/vietocr/*` theo `VIETOCR_MODEL_DIR`, các file `models/*` khác theo `OCR_MODELS_DIR`. Engine VietOCR dùng cùng resolver, nên file được băm là file được nạp.
- Chuyển model ra kho ngoài chỉ hợp lệ khi nội dung trùng sha256 trong registry. Nội dung khác bị từ chối ngay trong `prepare_backend` (`MODEL_LOCK_MISMATCH`), trước khi nạp thư viện model hay chạy inference.
- Thiếu file thì lỗi sớm (`MODEL_MISSING`), không fallback và không tự tải model.
- Muốn dùng model khác thì cập nhật registry. Khi đó hash model mới vào `ocr_identity` và stage key của các pha nạp nó, rồi lan xuống các pha sau qua receipt.
- Registry phải bao phủ detector và toàn bộ file trong các snapshot layout/table/formula được chọn, gồm cấu hình processor/tokenizer. File có trên đĩa nhưng chưa được pin bị từ chối bằng `MODEL_REGISTRY_INCOMPLETE`, cả lúc tạo backend, kiểm runtime và trước khi worker nạp model. Thêm một file vào snapshot cần cập nhật registry có chủ đích.
- File chọn revision của Hugging Face cũng là input model: `refs/main` của layout/formula và `refs/v2.3.0` của TableFormer phải có trong registry và trỏ đúng revision khai báo. Registry phải khai báo đúng repo mà Docling đã khóa thực sự nạp; khai báo một repo khác không thay lựa chọn của engine. Thiếu ref bị từ chối `MODEL_REGISTRY_INCOMPLETE`; ref/repo lệch bị từ chối `MODEL_SELECTION_CHANGED`, kể cả khi mọi hash được khai báo đều khớp. Đổi họ model cần đổi adapter/runtime có chủ đích, không chỉ thay metadata registry.
- Docling worker chốt `HF_HOME`, `HF_HUB_CACHE`, `HUGGINGFACE_HUB_CACHE` và các alias cache Transformers vào kho `<models>/docling/huggingface`. `DOCLING_ARTIFACTS_PATH` thừa kế bị loại bỏ để không chuyển sang model chưa pin. Chính sách offline của scheduler được giữ nguyên. Quy tắc cache chung này cũng áp dụng client legacy; không nâng model hoặc thay thuật toán.
- `python -m ocr_runtime.diagnose --verify-models` kiểm các file theo cùng resolver hiệu lực, kể cả `OCR_MODELS_DIR`/`VIETOCR_MODEL_DIR` ngoài checkout; trường `selected_files` cho biết từng đường dẫn được kiểm.
- Lựa chọn model thuộc snapshot của batch. `prepare_backend` ghi thư mục model hiệu lực (`model_env`) và file được chọn cho từng mục registry (`model_selection`); document owner và worker được khởi chạy với các thư mục này chứ không với môi trường lúc đó.
- `verify_runtime` (trước mỗi tài liệu và trước khi nhận kết quả) và worker (trước khi chạy pha) giải lại lựa chọn. Đổi `VIETOCR_MODEL_DIR`/`OCR_MODELS_DIR` sau snapshot thì bị từ chối (`MODEL_SELECTION_CHANGED`), kể cả khi các file đã ghim vẫn còn nguyên. Hash của mọi model đã ghim cũng được kiểm lại ở hai chỗ này.

### Thuộc tính thuật toán và đường dẫn triển khai

- Trong identity: dict profile đã resolve (thuật toán), hash model/lock theo đường dẫn tuyệt đối, đường dẫn tuyệt đối của interpreter, hash PDF. Stage key có thêm các biến chọn file model (`OCR_MODELS_DIR` cho cả hai pha, `VIETOCR_MODEL_DIR` cho pha A).
  - Hệ quả có chủ đích: chuyển checkout hoặc venv sang chỗ khác làm cache cũ không còn được dùng lại.
  - P12 không đổi điều này. Muốn thay bằng nhận dạng theo nội dung thì đó là thay đổi identity riêng, cần test và ghi chú tương thích.
- Ngoài identity: vị trí output, cache, input, job và log. Đổi chúng không làm mất hiệu lực cache, và không có thuộc tính ảnh hưởng output nào bị bỏ ra để tăng cache hit.

## Nhóm dữ liệu

| Nhóm | Ví dụ | Lưu ở đâu | Tái tạo được |
| --- | --- | --- | --- |
| Mẫu nhỏ | `examples/sample.pdf`, `tests/fixtures/`, `config/`, registry, font | Git | Có trong Git |
| Ground truth | `benchmark/ground_truth/`, `benchmark/accuracy_first_manifest.json` | Git, kèm provenance | Không; hiện chưa có GT người gán |
| PDF nguồn lớn | `inputs/*.pdf` | Kho ngoài, trỏ bằng `--input`/`OCR_DATA_DIR`; Git bỏ qua | Không, phải sao lưu ở nguồn |
| Model | `models/` (`*.pth`, `*.onnx`, `models/docling/`) | Tải bằng script setup, kiểm sha256 theo registry; Git bỏ qua | Có (tải lại, cùng revision) |
| Output cần giữ | `output/<batch>/`: tài liệu, báo cáo keyword, Excel, ma trận, `batch_state.sqlite`, `batch_report.json` | Sao lưu | Chỉ bằng cách chạy lại OCR |
| Cache | `.cache/v62-jobs`, `.cache/v63-stages`, `.cache/docling-structure`, cache trang legacy, `.cache/backend-probes`, `.cache/uv-setup` | Máy cục bộ hoặc `OCR_CACHE_DIR` | Có |

`.gitignore` và cache không phải cơ chế sao lưu.

## Sao lưu và khôi phục kết quả batch

Đơn vị sao lưu là cả thư mục output của batch. Ledger SQLite (`batch_state.sqlite`, chế độ WAL) phải đi cùng các file mà nó ghi nhận: ma trận, báo cáo keyword và receipt tài liệu.

1. Chỉ sao lưu khi không có tiến trình đang chạy trên batch đó. Supervisor giữ `batch.lock` trong suốt lượt chạy.
2. Chép nguyên thư mục, gồm `batch_state.sqlite` và các file `-wal`/`-shm` nếu còn, `batch_input_manifest.json`, `batch_config.json`, `keyword_dictionary.snapshot.json`, thư mục từng tài liệu và các file Excel.
3. Kiểm bản sao mà không ghi vào nó: chạy analysis run với bản sao làm nguồn chỉ đọc, ra một thư mục mới:

   ```powershell
   python run_batch.py --analysis-from D:\backup\batch-2026-10 --output D:\verify\batch-2026-10
   ```

   Mọi tài liệu phải `SUCCEEDED` và số đếm phải trùng `batch_report.json` của bản sao. Analysis run kiểm receipt, completion marker và extraction nguồn.
4. Khôi phục: chép lại nguyên thư mục vào chỗ cũ, không ghép file từ hai bản sao khác nhau. Chỉ `--resume` batch đã khôi phục khi mã và runtime còn khớp với batch (`verify_runtime` từ chối nếu khác). Muốn đếm lại bằng mã mới thì dùng analysis run.

## Chính sách dọn

Phần này chỉ mô tả; chưa có lệnh dọn tự động và không có dữ liệu nào bị xoá ở P12.

| Có thể xoá | Điều kiện | Hệ quả |
| --- | --- | --- |
| `.cache/v63-stages/<phase>/*.tmp-*`, `*.replaced-*` | Không có batch V6.3 đang chạy | Không mất gì: thư mục attempt dở hoặc bản cũ bị thay, không bao giờ được dùng lại |
| `.cache/docling-structure/<uuid>/page-*.pdf` | Như trên | PDF một trang tạm; giữ `worker.log` vì output tham chiếu nó qua `log_path` |
| `.cache/backend-probes/` | Bất kỳ lúc nào | Profiling detector tạo lại ở lượt sau |
| `.cache/v63-stages/<phase>/<key>/` | Không có batch đang chạy | Mất khả năng `--resume` dùng lại pha đó |
| `.cache/v62-jobs/<generation>/` | Không có batch đang chạy | Mất log pha và audit scheduler dùng cho chẩn đoán |

Không xoá: output batch đã công bố, ledger, `inputs/`, `models/`, các venv.

## DVC

Chưa dùng. Nhu cầu version dataset hay model chưa được xác nhận trong kế hoạch: model đã khoá bằng registry có revision và sha256, còn GT người gán chưa có. Khi cần, chỉ đưa vào tập mẫu được phép; không thêm `inputs/`, `models/` hay `output/`, không upload dữ liệu, không đưa credential vào Git.
