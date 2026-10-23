# Phát triển từng module

Tài liệu vận hành cho kiến trúc package hiện tại. Bất biến và tiêu chí nghiệm thu nằm trong [thiết kế](PROMPTS_TAI_CAU_TRUC_MODULE_OCR_PDF.md); trạng thái cùng bằng chứng nằm trong [MIGRATION_PLAN.md](MIGRATION_PLAN.md). Việc thêm hướng dẫn và job CI thuộc P13, chưa tự chứng minh toàn bộ migration đã được nghiệm thu.

## Chọn môi trường tối thiểu

Một distribution `ocr-pdf`, các package `ocr_*` ở `src/`. Cài editable từ gốc checkout; Python 3.11 là môi trường tham chiếu. Tạo venv riêng cho phần đang phát triển để phát hiện dependency vô tình bị kéo vào. Không đồng bộ venv đang được một batch sử dụng.

| Phần phát triển | Cài vào venv mới | Nhóm test chính |
| --- | --- | --- |
| contracts, artifacts, keywords | `python -m pip install -e . pytest` | `tests/unit/contracts`, `tests/unit/artifacts`, `tests/unit/keywords` |
| text | `python -m pip install pytest` rồi dùng `PYTHONPATH=src` | `tests/unit/text` (mã package chỉ dùng thư viện chuẩn) |
| reporting | `python -m pip install -e ".[reporting]" pytest` | `tests/unit/reporting` |
| runtime, document, pipeline | `python -m pip install -e ".[app,dev]" pytest` | `tests/unit/runtime`, `tests/unit/document`, `test_analysis_run.py`, `test_v63_pipeline.py`, các test protocol/cache |
| pdf_io, recognition, layout, legacy | `python -m pip install -e ".[legacy,test]"` | `tests/unit/pdf_io`, `tests/unit/recognition`, test layout và `tests/legacy_compat` |
| structure | CPU client dùng `.[app]`; Docling thực ở worker riêng | `tests/unit/structure`, `test_docling_structures.py`; phân biệt double với inference |
| workers | Supervisor dùng `.[app]`; engine chạy trong hai runtime GPU đã khóa | `test_worker_protocol.py`, `test_stage_cache.py`, `test_v63_worker_acceptance.py` |

`test` gồm công cụ đánh giá khoa học, không chỉ pytest. Vì vậy job package nhẹ cài pytest trực tiếp và chỉ các dependency runtime cần dùng. `legacy` có Torch/VietOCR/OpenCV/ONNX Runtime CPU; không cài extra này vào worker GPU. `ocr_pdf_io` hiện dùng NumPy/OpenCV/Pillow qua các module render/crop; extra `app` chưa phải môi trường đầy đủ cho mọi API của package đó.

Ví dụ chạy nhóm nhẹ từ checkout:

```powershell
python -m pytest tests/unit/contracts tests/unit/artifacts tests/unit/text tests/unit/keywords -q -p no:cacheprovider
python -m pytest tests/unit/reporting -q -p no:cacheprovider
python -m pytest tests/unit/test_import_contracts.py -q -p no:cacheprovider
```

Lệnh cuối cần `import-linter` (`.[dev]` hoặc `.[test]`). Nếu cần bằng chứng có thể lưu lại, chạy qua `python scripts/run_pytest_scratch.py <đối số pytest>`: mỗi lần tạo `scratch/runs/<run_id>/` mới với basetemp, log, `evidence/junit.xml` và `run.json`, tắt cache/bytecode, và trả đúng exit code của pytest. Không dùng output, cache hoặc venv sản xuất làm thư mục test.

Fixture tài liệu dùng chung ở `tests/unit/document_test_helpers.py` chỉ phụ thuộc contracts. Test pipeline/analysis không import cả module test engine để lấy fixture. Hai ca kiểm forward/device Torch ở `test_v62_gpu_scheduler.py` chạy trong job legacy có Torch; job subprocess/contract của CPU app loại đúng hai ca này, không cài stack OCR để che dependency bị kéo nhầm.

## Ownership và điểm mở rộng

| Package | API/trách nhiệm chính | Runtime |
| --- | --- | --- |
| `ocr_contracts` | Model trang/tài liệu, trạng thái, lỗi, `protocol` JSON | Mọi process; chỉ pydantic/thư viện chuẩn |
| `ocr_artifacts` | Digest có tên, SHA-256, ghi nguyên tử, marker dữ liệu chung | CPU và worker |
| `ocr_text` | Unicode, làm sạch chữ, bảo vệ số | Thư viện chuẩn |
| `ocr_keywords` | `counter`, snapshot/report trong `contract`, `validation` | CPU; không Excel/OCR |
| `ocr_reporting` | Workbook từng tài liệu/ma trận và đọc kiểm lại | CPU; nhận report đã đếm |
| `ocr_runtime` | Paths/config, lock/model, fingerprint, lease/process tree | CPU orchestration; thư viện model chỉ được nạp có chủ đích trong probe con |
| `ocr_pdf_io` | Inspect/render/crop PDF và biến đổi tọa độ | Worker hoặc công cụ PDF |
| `ocr_recognition` | Detector/recognizer, đánh giá chữ và bước nhận dạng | Text worker; độc lập model layout |
| `ocr_layout` | Adapter model layout và bước áp layout | Text worker; độc lập recognizer |
| `ocr_structure` | Docling client, bridge, bảng/công thức/sơ đồ | Client CPU; model ở Docling server riêng |
| `ocr_document` | Ghép trang, reading order/furniture, export, validation | CPU; không engine hoặc keyword |
| `ocr_pipeline` | CLI, backend, batch/ledger, publication, analysis và scheduler | Supervisor/document owner CPU |
| `ocr_workers` | Composition root engine, entry point A/B/export và Docling server | Text/Docling worker; mỗi process có vòng đời giới hạn |

Import submodule cần dùng, tránh re-export cả stack trong `__init__.py`. Ma trận import có thể thực thi nằm trong `pyproject.toml`; tên package và đường dẫn lịch sử nằm trong [module_map.json](module_map.json). Kiểm cả import trong hàm: lazy import không phải cách bỏ qua ranh giới. Chỉ dùng tên công khai của package khác. Module hoặc tên bắt đầu bằng `_` là implementation riêng của package sở hữu, kể cả khi package được phép import package đó. `test_packages_use_only_public_names_of_other_packages` kiểm cả import lẫn truy cập `module._x`; ngoại lệ còn giữ nằm ở khoá `private_import_exceptions` của `module_map.json`, kèm lý do.

Thêm recognizer/detector hoặc layout adapter tại package sở hữu, khai báo capability và kiểm cấu hình. Lắp engine tại `ocr_workers.page_engines`; truyền engine vào các bước thay vì tạo model trong pipeline. Chỉ mock tên tại nơi factory tra cứu (ví dụ `ocr_workers.page_engines.VietnameseSeq2SeqEngine`), không patch alias cũ rồi vô tình nạp model thật. Test double phải được đặt tên và ghi rõ phạm vi bằng chứng.

Thêm processor ở cấp đúng: nhận dạng trang ở recognition/layout; bảng/công thức ở structure; thứ tự đọc/renderer ở document; keyword policy ở keywords. Processor nhận contracts và metadata nguồn, không tự tạo confidence, bbox hoặc bằng chứng GPU không đo được. Renderer mới không được điều khiển engine OCR.

Thêm backend mới cần interface/capability và policy riêng nếu không đáp ứng `gpu_ocr_only_v1`. Không gắn nhãn VietOCR/Docling cho bước model khác, và không nới validator hiện có để nhận một nguồn chữ khác. Dependency xung đột cần runtime/lock riêng cùng entry point, preflight, fingerprint và kiểm kết thúc cây process.

## Fixture và hợp đồng dữ liệu

Fixture nhỏ ở `tests/fixtures/`; `tests/fixtures/migration/v63_sample` giữ trang được trích xuất từ lượt GPU baseline. Test export dùng fixture chứng minh hồi quy phần mềm, không phải lượt GPU mới hoặc ground truth. `examples/sample.pdf` là mẫu để smoke; không OCR toàn bộ `inputs/` để kiểm thay đổi module nhỏ.

Khi đổi schema/model wire:

1. Ghi rõ field/alias/default/serialization và consumer bị tác động. Di chuyển file không được tự đổi schema hay digest.
2. Giữ đọc fixture cũ hoặc từ chối có lỗi/version rõ ràng. Không sửa hash/receipt của output cũ để làm qua kiểm.
3. Cập nhật JSON protocol/schema và validator cùng consumer trong cùng thay đổi. Worker trao đổi JSON/artifact reference, không pickle hoặc object GPU.
4. Thêm fixture hợp lệ và ca lỗi có ý nghĩa: version cũ, thiếu file, receipt bị sửa, sai request/attempt hoặc nguồn không đáp ứng policy.
5. Kiểm round-trip, baseline và đường alias/legacy còn dùng API đó.

`literal_v1` giữ nguyên đếm literal NFC + casefold trên Markdown đã xuất. Semantics mới phải có policy/version mới; thay cách format Markdown cũng có thể thay số đếm, nên so vector keyword cùng baseline.

## Dependency, model và lock

Metadata/extras ở `pyproject.toml`, resource wheel được tạo từ nguồn duy nhất qua `setup.py`. Không sửa bản sao resource sau build. CPU app có lock theo hệ điều hành ở `requirements/v63`; text và Docling có lock riêng ở `requirements/v62`. Đọc README/input/constraints của runtime tương ứng trước khi cập nhật; không hợp nhất lock hoặc nâng model cùng một refactor.

Chỉ tái tạo lock khi input dependency thay đổi. Giữ platform/CUDA index/hash đúng, kiểm resolver ở môi trường mới ngoài batch hiện hữu, sau đó chạy preflight và test runtime chịu tác động. Model version/revision/hash thuộc `models/v62/runtime-models.json`, không suy từ phiên bản dependency. Model ngoài checkout vẫn phải trùng nội dung registry và đúng file engine sẽ nạp. Xem [cấu hình và dữ liệu](CAU_HINH_VA_DU_LIEU.md) để chọn path và chẩn đoán chỉ đọc.

Đổi package/resource cần build wheel thật, cài vào venv mới từ CWD ngoài checkout, chạy `python -I` và `pip check`. Test copy tree trong `test_packaging.py` có phạm vi khác với build/install thật. Wheel hỗ trợ keyword/reporting/analysis/legacy CPU; V6.3 GPU vẫn yêu cầu checkout và chủ động từ chối wheel bằng `NOT_SUPPORTED`.

## Fingerprint và cache

`ocr_runtime.fingerprint` phân loại extraction, analysis và publication; worker kiểm membership của mã đã nạp. Stage key A/B/export còn có closure của stage, mã coordinator dựng request, schema/config, model/lock, file nguồn và receipt upstream. Bỏ thành phần ảnh hưởng output khỏi key là lỗi đúng đắn dữ liệu, kể cả khi cache hit tăng.

Sau thay đổi liên quan identity/cache, dùng call counter trong `tests/unit/test_stage_cache.py` và `test_analysis_run.py` để chứng minh:

| Thay đổi | Hành vi cần chứng minh |
| --- | --- |
| Excel/publication | Không gọi OCR |
| Từ điển keyword | Đếm/xuất lại trên extraction hợp lệ; không gọi OCR |
| Mã chỉ pha B | Dùng lại A, chạy lại B và downstream |
| VietOCR/detector hoặc mã pha A | Chạy lại pha bị tác động và downstream |
| Coordinator dựng request/runtime chung | Mất hiệu lực mọi stage bị ảnh hưởng |
| Receipt/artifact hỏng hoặc process tree chưa xác nhận thoát | Không dùng lại cache và không công bố thành công |

Không chỉ kiểm file tồn tại. Receipt stage chỉ đủ điều kiện tái dùng khi hash/key/input receipt đúng và `exited.json` ràng buộc receipt với cây process đã thoát. Thời gian của stage được dùng lại là thời gian lịch sử, không phải inference của lượt hiện tại. Cache có thể tái tạo; chính sách dọn không cho phép xóa output/model thật đang được dùng.

## Tương thích và batch đã có

Alias `src.ocr.*` chuyển đến cùng object module mới, không chứa implementation thứ hai. [module_map.json](module_map.json) là bảng máy đọc được; [MIGRATION_PLAN.md](MIGRATION_PLAN.md) có bảng import cũ → mới, consumer, điều kiện gỡ và hai ngoại lệ worker V6.2 còn giữ. Chỉ gỡ khi không còn consumer và đã có bằng chứng smoke phù hợp. V6.3 dùng orchestrator mới; `ProcessPageUseCase` vẫn phục vụ legacy.

Đọc output qua `result.md`, manifest/validation và receipt; trạng thái `NEEDS_REVIEW` không phải điểm chính xác. Không resume batch bằng code/runtime/model mới: giữ snapshot gốc hoặc dùng output mới. Giữ nguyên cả batch gồm SQLite, revision workbook và receipt khi sao lưu; xem quy trình kiểm bản sao ở tài liệu P12.

Muốn đếm bằng keyword mới trên kết quả cũ:

```powershell
python run_batch.py --analysis-from output/batch-cu --keywords-file config/keywords.txt --output output/analysis-moi
```

Nguồn phải vượt completion/receipt/extraction/GPU policy trước khi analysis chấp nhận; provenance tự khai không đủ. Nguồn hỏng/thiếu `result.md` hoặc manifest phải có hàng `FAILED_DOCUMENT`, counts `null`, không bị bỏ và không thay bằng số 0. `--recount` giữ snapshot keyword của batch cũ; không dùng nó để đổi policy hay model.

## CI và các mức bằng chứng

Job legacy chạy toàn bộ regression phần mềm (`tests/unit`, `tests/scientific`, `tests/legacy_compat`) cùng integration PDF native/keyword (PDF tạo trong thư mục test) ở mỗi push/PR, không tải model. Các job tách theo dependency chỉ chứng minh từng nhóm chạy được với dependency tối thiểu; chúng không thay cho lượt đầy đủ này. `tests/unit/test_ci_workflow.py` hỏng nếu một thư mục regression rời khỏi các job mặc định, hoặc nếu job mặc định bắt đầu tải model. Job CPU kiểm toàn bộ `tests/unit/runtime`, gồm packaging/config/import; hai ca import runtime worker thật được ghi SKIP nếu máy không có runtime đó. Mọi SKIP cần giữ lý do trong JUnit, không quy thành inference thành công.

[tests.yml](../../.github/workflows/tests.yml) tách package nhẹ, CPU document/pipeline, import/subprocess, wheel ngoài checkout, legacy facade và các job model/GPU được kích hoạt riêng. Job nhẹ không cài Torch hoặc tải model. Process cleanup và venv symlink chạy trên Windows/Linux; test symlink thực dành cho Linux có thể skip trên Windows.

Chọn **Run workflow → run_models** để tải model legacy và chạy regression/integration có model trên runner CPU. PDF/prediction BHN/CLW không có trong checkout vẫn là `NOT_RUN` khi test skip. Chọn **run_gpu** chỉ sau khi có runner Linux mang nhãn `ocr-pdf-gpu`, Python supervisor/worker và model ngoài checkout đã được chuẩn bị. Cấu hình repository variables `OCR_GPU_SUPERVISOR_PYTHON`, `OCR_GPU_ENV_ROOT`, `OCR_GPU_MODELS_DIR`, `OCR_GPU_LEASE_DIR` bằng đường tuyệt đối (lease dùng chung máy, ngoài checkout); job không cài/sync môi trường này. Thiếu runner hoặc job bị bỏ qua không được ghi thành nghiệm thu GPU. Bằng chứng GPU chỉ bao phủ sample fresh/resume đã kiểm artifact/receipt; không thay cho tải dài hoặc chất lượng.

Đọc JUnit, log và artifact của từng job, không chỉ ô màu tổng hợp. Báo cáo nghiệm thu phải tách hoàn thiện mã, test CPU, inference GPU thật, kiểm Docker/Kaggle và chất lượng trên GT. Công cụ `run_scientific_benchmark.py`/`run_regression.py` cần prediction/GT đúng định danh cùng protocol chốt trước. Không có GT người gán nhãn độc lập thì chất lượng giữ `NOT_EVALUATED`; fixture/double/readiness không bổ sung GT.

GitHub Actions trên cả hai hệ điều hành, GPU runner, Docker và phiên Kaggle thực phải có kết quả chạy riêng trước khi ghi đạt. Thêm workflow chưa phải bằng chứng workflow đã chạy.
