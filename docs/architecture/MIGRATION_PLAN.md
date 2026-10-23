# Kế hoạch migration kiến trúc module OCR_pdf

Tài liệu trạng thái của đợt tái cấu trúc theo [PROMPTS_TAI_CAU_TRUC_MODULE_OCR_PDF.md](PROMPTS_TAI_CAU_TRUC_MODULE_OCR_PDF.md). Cả hai file nằm trong `docs/architecture/` từ P01. Quyết định D1–D4, kiến trúc đích, quy tắc phụ thuộc và chính sách legacy nằm trong tài liệu đó; file này ghi trạng thái thực tế, bản đồ đường dẫn đã chốt, ngoại lệ và bằng chứng.

## Nhận dạng baseline

| Mục | Giá trị |
| --- | --- |
| HEAD | `e6a219024c47fa461b7900ce35d3918c18af7175` |
| Thay đổi cục bộ của chủ dự án trước đợt migration | `scratch/migration/baseline_user_changes.patch`, SHA-256 `3bcbdaf16061d6d0d152b8c648ab6df62b2d700e3834bf07adff8b99293e9f16` (profiles-v63.yaml, gpu_phase_worker.py, v63_backend.py, xoá run_auto_loop.py) |
| Test trước migration | `tests/unit tests/scientific`: 823 passed, 1 skipped (110 s), JUnit `scratch/migration/junit-baseline.xml` |
| Môi trường | Windows 11, `.venv` Python 3.11.16, `.venv-v62/{text,docling}`, GPU NVIDIA GeForce RTX 2050 4 GB |

Không commit trong đợt migration (theo Prompt nền). Mỗi giai đoạn lưu patch của toàn bộ thay đổi so với HEAD vào `scratch/migration/after-<giai đoạn>.patch` để có thể quay lại.

## Trạng thái giai đoạn

| Giai đoạn | Trạng thái | Kết quả mong đợi | Kiểm tra chính |
| --- | --- | --- | --- |
| P00 Kiểm kê | DONE | File này; đồ thị import; bản đồ đường dẫn; closure; consumer | Đối chiếu đồ thị import với mục "Điểm nối" |
| P00b Cổng nhận kết quả worker | DONE | Một hàm kiểm chứng cho mọi nhánh nhận result; chính sách fallback Docling có test | test_v63_pipeline, worker lifetime, test cổng mới |
| P01 Baseline | DONE | Digest baseline, legacy_compat, docs/architecture vào Git | Test digest baseline, smoke legacy |
| P02 contracts + artifacts + cơ chế di chuyển | DONE | `ocr_contracts`, `ocr_artifacts`, fingerprint phủ `src/`, PYTHONPATH chung, alias, import-linter | Toàn bộ unit/scientific, digest baseline, import-linter |
| P03 keywords | DONE | `ocr_keywords`; validator tài liệu không import keyword | Test keyword, V6.3 pipeline |
| P04 reporting | DONE | `ocr_reporting`; hợp đồng extraction ↛ keywords/reporting/publication | Test Excel, publication |
| P11a Identity extraction/analysis | DONE | Fingerprint theo closure; analysis run | Call counter: đổi từ điển/Excel không OCR |
| P05a runtime + text | DONE | `ocr_runtime`, `ocr_text`; resolver gốc | Test runtime, Docling venv import |
| P05b pdf_io | DONE | `ocr_pdf_io`; hình học dùng chung | Test geometry/crop |
| P06 recognition + layout | DONE | `ocr_recognition`, `ocr_layout` | Test process_page, routing, numeric guard |
| P07 structure | DONE | `ocr_structure`; pha B không nạp VietOCR | Test Docling fixture, bridge |
| P08 document | DONE | `ocr_document`; completion vào artifacts | Test export/validator, JSON Schema |
| P09 pipeline + workers | DONE | `ocr_pipeline`, `ocr_workers`; orchestrator V6.3 | Test V6.3 pipeline, lifetime, protocol |
| P10 Đóng gói | DONE | Một distribution, extras, wheel | Ma trận cài/import/build |
| P11b Cache theo stage | DONE | Stage key pha A/B/export | Call counter theo pha |
| P12 Cấu hình | DONE (GPU Windows, hợp đồng CPU/path Windows và Linux) | Nguồn cấu hình, thứ tự ưu tiên | Test resolver/precedence/model selection/ref |
| P13 CI + nghiệm thu | IN_PROGRESS (mã xong, kiểm Windows/Linux cục bộ; target remote/Kaggle chưa chạy) | CI theo job, báo cáo nghiệm thu | CI cục bộ, báo cáo |

## Kết quả kiểm kê P00

### Batch V6.3 hiện có

Không có thư mục batch V6.3 đang dở trên đĩa (tìm `batch_state.sqlite` ngoài `.venv*`: chỉ có thư mục tạm của pytest). Batch V6.3 duy nhất đã được nén thành `output/v63.zip` (7,15 GiB). Việc fingerprint đổi từ P02 không làm mất khả năng hoàn tất batch nào. Muốn đếm lại trên batch này sau migration, giải nén vào một thư mục riêng và dùng analysis run (P11a); không resume trực tiếp.

### Phân loại module theo luồng (đồ thị import tĩnh, gồm import trong hàm)

Script: `scratch/migration/import_graph.py`; kết quả: `scratch/migration/import_graph_p00.json` (116 module trong `src/ocr` + `scripts.preflight_v62`, `scripts.docling_structure_worker`).

- Chỉ V6.3: `application.{process_batch,process_document,publish_keyword_matrix,recount_document}`, `cli.unified`, `infrastructure.pdf.ocr_bridge`, `infrastructure.state.batch_store`, `runtime.{dependency_lock,gpu_phase_worker,torch_placement,v63_backend,v63_document_worker}`, `scripts.docling_structure_worker`, `scripts.preflight_v62`.
- Chỉ legacy: `application.convert_document`, `cli.{batch_runner,collect,gpu_runner,run_ocr}`, `collect.catalog`, `runtime.{document_pool,hardware,run_manifest}`.
- Dùng chung: 85 module, gồm `application.process_page` và toàn bộ infrastructure còn lại.
- Không được import: `domain.models.subpage`.

Đối chiếu mục "Điểm nối" của tài liệu prompt: cả 15 điểm vẫn đúng tại baseline. Vòng import mức module: 0. Vòng qua import trong hàm: 2 (`document_contracts ↔ markdown_exporter ↔ structure.ids ↔ section_tree`; `artifact_validator ↔ completion ↔ keyword_validator ↔ gpu_scheduler`).

### Ownership hạ tầng dùng chung

| Trách nhiệm | Hiện tại | Đích |
| --- | --- | --- |
| Hash file SHA-256 | `gpu_scheduler.sha256`, `completion._sha256`, `artifact_cache`, `models.model_file_sha256` (có cache theo stat), `run_manifest`, `collect.catalog` | `ocr_artifacts.hashing.sha256_file`; bản legacy (`run_manifest`, `catalog`) giữ nguyên |
| Canonical JSON digest | `keyword_contract.digest` (compact, không ASCII, 64 hex); generation trong `run_document` (ASCII, separator mặc định); `config_hash`, `model_fingerprint` (không ASCII, separator mặc định, 16 hex); `resolve_document_layout` (24 hex); `ProcessPageUseCase._build_cache_key` (ASCII, 16 hex); `DoclingStructureExtractor.cache_fingerprint` (băm luồng nhiều phần) | `ocr_artifacts.digest`: `sha256_json_compact`, `sha256_json_ascii`, `sha256_json_unicode`; Docling fingerprint giữ băm luồng tại chỗ |
| Ghi nguyên tử | `runtime/atomic_io.py` | `ocr_artifacts.atomic_io` |
| Completion marker | `export/completion.py` (gọi validator tài liệu) | `ocr_artifacts.completion` sau khi tách validator (P08) |
| Validation | `export/artifact_validator.py` (gọi `keyword_validator`), `keyword_validator.py` (gọi `keyword_v63.verify_document`) | Tài liệu: `ocr_document`; JSON keyword: `ocr_keywords`; workbook: `ocr_reporting`; ghép ở pipeline |
| Ledger/publication | `state/batch_store.py`, `application/{process_batch,publish_keyword_matrix}.py` | `ocr_pipeline` |

### Bản đồ đường dẫn đã chốt

Đường dẫn cũ tương đối với `src/ocr/`. Module đã chuyển để lại alias `sys.modules` ở đường dẫn cũ.

| Đường dẫn cũ | Đích | Giai đoạn |
| --- | --- | --- |
| `domain/models/{accuracy,confidence,diagram,document,evidence_block,formula,keyword,page,processing,quality,region,schema,subpage,table,text_block}.py` | `ocr_contracts.<cùng tên>` | P02 |
| `domain/routing/page_type.py` | `ocr_contracts.page_type` | P02 |
| `runtime/atomic_io.py` | `ocr_artifacts.atomic_io` | P02 |
| `infrastructure/postprocessing/{keyword_counter,keyword_contract}.py` | `ocr_keywords.{counter,contract}` | P03 |
| `infrastructure/export/keyword_validator.py` | `ocr_keywords.validation` + `ocr_reporting.validation`; đường dẫn cũ giữ hàm ghép | P03/P04 |
| `infrastructure/export/{keyword_exporter,keyword_v63}.py` | `ocr_reporting.{document_workbook,workbooks}` | P04 |
| `runtime/{paths,config,models,fingerprint,dependency_lock,process_tree,device,torch_placement,backend_probe,structured_logging}.py` | `ocr_runtime.<cùng tên>` | P05a |
| `GPULease`, `gpu_snapshot`, `lease_for_gpu` trong `runtime/gpu_scheduler.py` | `ocr_runtime.gpu_lease` | P05a |
| `scripts/preflight_v62.py` (`inspect_environment`, `resolve_benchmark_policy`) | `ocr_runtime.preflight` | P05a |
| `infrastructure/postprocessing/{unicode_normalizer,numeric_guard,text_cleaner}.py` | `ocr_text.<cùng tên>` | P05a |
| `infrastructure/pdf/{coordinate_transform,native_text_extractor,pdf_inspector,pdf_renderer,region_cropper,scan_image}.py` | `ocr_pdf_io.<cùng tên>` | P05b |
| `block_is_covered` trong `layout/docling_structure.py` | `ocr_contracts.geometry` | P05b |
| `infrastructure/ocr/*`, `infrastructure/quality/*`, `domain/routing/routing_policy.py`, `application/route_page.py` | `ocr_recognition.<cùng tên>` | P06 |
| `infrastructure/layout/{dla_engine,page_content_analyzer,model_adapters,torch_layout}.py` | `ocr_layout.<cùng tên>` | P06 |
| `infrastructure/layout/{document_layout_engine,diagram_builder}.py`, `infrastructure/table/hidden_text_layer.py`, `infrastructure/pdf/ocr_bridge.py` | `ocr_structure.<cùng tên>` | P07 |
| `infrastructure/layout/docling_structure.py` | `ocr_structure.docling_client` | P07 |
| `ProcessPageUseCase._enrich_structures` | `ocr_structure.enrichment.enrich_structures` | P07 |
| `infrastructure/layout/region_tree.py`, `infrastructure/postprocessing/{reading_order,reading_order_graph,xy_cut,document_furniture,legacy_furniture,page_association}.py`, `infrastructure/structure/*`, `infrastructure/table/financial_checks.py`, `infrastructure/export/{artifact_validator,contract_schema,document_contracts,json_exporter,manifest_exporter,markdown_exporter,output_contract,result_reader}.py`, `application/{export_document,resolve_document_layout,resolve_document_furniture}.py` | `ocr_document.<cùng tên>` | P08 |
| `infrastructure/export/completion.py` | `ocr_artifacts.completion` | P08 |
| `runtime/gpu_phase_worker.py` | `ocr_workers.phases` | P09 |
| `scripts/docling_structure_worker.py` | `ocr_workers.docling_server` (script cũ là wrapper) | P09 |
| `cli/unified.py`, `application/{process_batch,process_document,publish_keyword_matrix,recount_document}.py`, `infrastructure/state/batch_store.py`, `runtime/{v63_backend,v63_document_worker}.py`, phần còn lại của `runtime/gpu_scheduler.py` | `ocr_pipeline.<tên>` | P09 |
| `application/{convert_document,count_keywords,reocr_region,process_page}.py`, `cli/{batch_runner,run_ocr,gpu_runner,collect}.py`, `runtime/{document_pool,run_manifest,hardware}.py`, `infrastructure/cache/artifact_cache.py`, `collect/` | Ở lại (legacy đóng băng) | — |

Khác biệt so với bảng trong tài liệu prompt:

- Hằng keyword trong `processing.py` (`KEYWORD_SCHEMA`, `POLICY`, `POLICY_VERSION`, `KEYWORD_ARTIFACTS`) ở lại `ocr_contracts.processing`. Đây là định danh của hợp đồng wire. Chuyển chúng sang `ocr_keywords` sẽ buộc `ocr_contracts` phụ thuộc ngược hoặc làm alias không còn là cùng một module.
- `block_is_covered` đặt ở `ocr_contracts.geometry` vì là hàm thuần Python.

### Closure dùng cho P04/P11a

Analysis/publication (loại khỏi closure extraction): `ocr_keywords`, `ocr_reporting`, `application/{process_batch,publish_keyword_matrix,recount_document,count_keywords}.py`, `infrastructure/state/batch_store.py`, alias cũ của các module keyword/reporting, phần finalize keyword của `process_document` (tách ở P11a).

Extraction: mọi file mã còn lại trong vùng băm (gồm legacy, scheduler, backend, worker, Docling worker, preflight). Tính bảo thủ: sửa legacy cũng đổi `ocr_identity` của lần chạy mới.

### Consumer của đường dẫn cũ

- Test: 115 đường dẫn `src.ocr.*` khác nhau; 97 lời gọi `monkeypatch.setattr`; `patch("src.ocr.application.process_page.<Class>")` cho 9 lớp; `src.ocr.runtime.gpu_scheduler.{sha256,GPULease,valid_receipt,committed_receipt,validate_policy}`.
- Notebook `kaggle/ocr_pdf_v63_kaggle.ipynb`: `keyword_contract`, `ocr_bridge`, `keyword_v63`, `completion`, `artifact_validator`, `process_document`; gọi `scripts/setup_v62.py`, `scripts/preflight_v62.py`, `scripts/setup_vietocr_model.py`, `run_batch.py`.
- Scripts: 22 file import `src.ocr`, trong đó `setup_v62.py`, `prepare_v62_models.py`, `preflight_v62.py` dùng `gpu_scheduler.{sha256,gpu_snapshot,lease_for_gpu}`.
- `pyproject.toml`: entry point `src.ocr.cli.unified:{run_one,run_batch}`, `src.ocr.cli.collect:main`, version động `src.ocr.infrastructure.export.manifest_exporter.PIPELINE_VERSION`.
- `setup.py`: resource đóng gói vào `src/ocr/resources`.
- Worker: `-m src.ocr.runtime.gpu_phase_worker`, `-m src.ocr.runtime.v63_document_worker`, `scripts/docling_structure_worker.py`, preflight `python -c "from src.ocr.infrastructure.pdf.ocr_bridge import load_bridge_font"`.

### Ảnh hưởng và cách quay lại

- Source fingerprint đổi ngay ở P02 (vùng băm mở rộng). Mọi batch/page cache cũ sẽ bị coi là khác identity khi resume; không batch nào đang dở.
- Wheel: P02–P09 giữ cấu hình đóng gói cũ (`src*`); package `src/ocr_*` được bootstrap qua `src/ocr/__init__.py` để chạy được cả từ checkout lẫn wheel cũ. P10 đã đổi sang top-level `ocr_*` (xem "Kết quả P10").
- Quay lại một giai đoạn: áp `git apply -R` patch của giai đoạn đó lên cây hiện tại, hoặc khôi phục cây từ HEAD rồi áp `scratch/migration/baseline_user_changes.patch` và patch của giai đoạn trước. Không động vào inputs/output/models/venv.

## Kết quả P00b

- `supervised_run` phát `PhaseExitError` (có `returncode`) và `ProcessTreeSurvived` (có `pids`); cả hai là `RuntimeError` với thông điệp cũ.
- `GPUProcessor` dùng một hàm kiểm chứng duy nhất, `verify_document_result`: lượt thử khớp `attempt_id`, schema, thư mục output, `ocr_receipt` đúng identity, hash report/marker, nguồn GPU, report keyword. Cây process không xác minh được → `PublicationError`. Exit code khác 0 sau khi có result → `PublicationError`, trừ mã có trong `ACCEPTED_NONZERO_EXIT_CODES` (đang rỗng). Response không parse được → `PublicationError`.
- `v63_document_worker` gửi lại `attempt_id`. Pha B dùng `phase_b_status_accepted`, giữ đúng chính sách của diff cục bộ (fallback chấp nhận `FAILED_FALLBACK` và `success` kèm `errors`; validator đánh dấu `NEEDS_REVIEW`).
- README mục 7 ghi chính sách fallback và cổng nhận kết quả.

## Kết quả P01

- Baseline = HEAD + thay đổi cục bộ được giữ + P00b.
- Cổng cần giữ (đã có test): nguồn GPU từng trang (`validate_gpu_source`), đủ trang, cầu nối pha B, receipt OCR/keyword, marker hoàn tất, prepare → publish → đọc lại → acknowledge, khoá batch, phát hiện input/từ điển/mã đổi (`test_v63_pipeline.py`), cổng nhận kết quả worker (`test_v63_worker_acceptance.py`).
- Phân loại kiểm tra: CPU (unit/scientific/legacy_compat), GPU thật (lượt baseline trên sample; slot GPU khác chưa chạy), phụ thuộc model (legacy fast cần RapidOCR/VietOCR), phụ thuộc ground truth (chưa có, `NOT_EVALUATED`).

## Kết quả P02

- Package `src/ocr_contracts` (15 model domain + `page_type`), `src/ocr_artifacts` (`hashing.sha256_file`, `digest.sha256_json_{compact,ascii,unicode}`, `atomic_io`). Đường dẫn cũ là alias `sys.modules`.
- `src/ocr/__init__.py` thêm `src/` vào `sys.path` cho mọi consumer của namespace cũ; `pytest.ini` dùng `pythonpath = . src`.
- `paths.code_roots()`/`worker_pythonpath()` là nguồn duy nhất cho PYTHONPATH của worker (scheduler, document owner, preflight cầu nối, Docling client) và vùng băm. `fingerprint.source_files()` băm toàn bộ `src/**/*.py` cùng `scripts/docling_structure_worker.py`, `scripts/preflight_v62.py`. `assert_loaded_code_fingerprinted()` chạy cuối mỗi pha GPU và trước khi document owner ghi result; lỗi `UNFINGERPRINTED_CODE` là lỗi hạ tầng.
- Nơi gọi digest dùng hàm có tên: `keyword_contract.digest` = `sha256_json_compact`; generation và cache key trang = `sha256_json_ascii`; `config_hash`, `model_fingerprint`, ID dẫn xuất của layout = `sha256_json_unicode`; `gpu_scheduler.sha256`, `completion._sha256` = `sha256_file`. Runtime/pipeline lấy digest từ `ocr_artifacts`, không từ keyword. `DoclingStructureExtractor.cache_fingerprint` giữ băm luồng tại chỗ.
- Import-linter 2.5.2 cài trong `.venv` và extra `test`; cấu hình `[tool.importlinter]` trong `pyproject.toml`; `tests/unit/test_import_contracts.py` chạy nó. Vi phạm cài thử (`ocr_contracts.schema -> numpy`) bị phát hiện rồi gỡ: `scratch/migration/importlinter-planted-violation-p02.txt`.
- Hệ quả đã biết: source fingerprint đổi (vùng băm mở rộng), nên page cache và batch tạo trước P02 không resume được. Logger của module đã chuyển có tên mới (`ocr_contracts...`).

## Kết quả P03

- Package `src/ocr_keywords`: `counter` (literal_v1), `contract` (snapshot, report, `digest` = `sha256_json_compact`), `validation.validate_keyword_group` (file, report, receipt của nhóm keyword; không đọc workbook).
- Hằng keyword ở lại `ocr_contracts.processing` (định danh wire, xem mục khác biệt).
- Cắt phụ thuộc ngược của mã extraction:
  - `document_validation.validate_document` là validator tài liệu thuần. Nhóm artifact được manifest khai báo (`keyword_contract`) phải có validator do caller truyền vào, nếu không thì FAIL.
  - `artifact_validator.validate_document_artifacts` ở đường dẫn cũ là hàm ghép (tài liệu + nhóm keyword), giữ API cho notebook, script và test.
  - `completion.mark_completed(..., group_validators=...)`; `finalize_keywords` truyền `keyword_validator.GROUP_VALIDATORS`.
  - `DocumentExporter` (`application/document_export.py`) xuất và kiểm tài liệu mà không đếm keyword. `ExportDocumentUseCase` ở đường dẫn cũ là lớp con ghép, giữ `count_keywords=True` mặc định cho legacy.
  - Pha export V6.3 dùng `DocumentExporter`. Đường V6.2 legacy (`finalize_document=True`) vẫn đếm trong pha export qua `ExportDocumentUseCase` (import trong hàm, có chú thích).
- Khác biệt có chủ đích, chỉ ở trường hợp dùng sai: export một output có policy V6.3 với `count_keywords=True`. Trước đây validation báo FAIL "keyword_contract is missing". Nay validation tài liệu qua, rồi `CountKeywordsUseCase` từ chối với ValueError. Kết quả cuối vẫn là lỗi.
- Test package `tests/unit/keywords` (25 test: hoa/thường, NFC/NFD, dấu, ký tự regex, khoảng trắng/xuống dòng, chuỗi con, không chồng lấn, keyword trùng, report bị sửa, mất từng file của nhóm) chạy trong venv tối thiểu cùng contracts/artifacts: 34 passed.

## Kết quả P04

- Package `src/ocr_reporting`: `document_workbook` (Excel riêng), `workbooks` (`export_document`, `verify_document`, `matrix_bytes`, `verify_matrix`), `validation.validate_document_workbook`. Không đếm lại, không đọc ledger; prepare/publish/acknowledge vẫn do `publish_keyword_matrix`/`process_batch` điều phối.
- `keyword_validator` ghép `ocr_keywords.validation` với `ocr_reporting.validation`.
- 13 thư mục con của `src/ocr` trước đây là namespace package lồng trong package thường; grimp không thấy module của chúng. Đã thêm `__init__.py` chỉ có docstring; đồ thị import-linter giờ phủ 254 file.
- Hợp đồng `extraction` (import-linter): `src.ocr.runtime.gpu_phase_worker` và toàn bộ closure import của nó không chạm `ocr_keywords`, `ocr_reporting`, ledger/publication, validator ghép và lớp export ghép. Ngoại lệ duy nhất: đường V6.2 legacy `gpu_phase_worker -> application.export_document`. Vi phạm gián tiếp cài thử bị phát hiện (`scratch/migration/importlinter-planted-violation-p04.txt`). Điều kiện tiên quyết của P11a đã đạt.
- Venv chỉ có pydantic, openpyxl, pytest: test `reporting` + `keywords` 34 passed (`scratch/migration/reporting-env-p04.txt`).

## Kết quả P11a (thay đổi hành vi có chủ đích)

- `fingerprint.closure_files()`: closure `extraction` (mọi file mã trừ danh sách analysis/publication), `analysis` (`ocr_keywords`, finalize keyword, analysis run, validator ghép, alias keyword + contracts/artifacts), `publication` (`ocr_reporting`, ledger, publication, alias reporting + analysis + contracts/artifacts). `code_fingerprints()` trả cả ba; `extraction_fingerprint()` dùng cho `ocr_identity` (`v63_backend.ocr_identity`, khoá `source_fingerprint`), generation của scheduler và kiểm tra trong pha GPU. `source_fingerprint()` (toàn bộ) giữ cho cache trang và manifest legacy.
- Batch V6.3 mới ghi `code_fingerprints` vào backend; `verify_runtime` kiểm cả ba nên một batch không trộn phiên bản mã. Batch tạo trước P11a không có khoá này: so toàn bộ fingerprint như cũ, nên vẫn bị từ chối khi mã đổi.
- `application/keyword_finalization.py` tách khỏi `process_document.py` (vẫn re-export `finalize_keywords` cho notebook). `keyword_receipt.json` ghi `analysis_fingerprint`; report chỉ được dùng lại khi mã đếm không đổi.
- `application/analysis_run.py` + `run_batch.py --analysis-from SOURCE... --output NEW`. Nguồn: batch/tài liệu V6.3 hoặc output analysis run. Kiểm chứng chỉ đọc: marker, `ocr_receipt` khớp file/manifest, `validate_gpu_source`, validator tài liệu. Sao chép nguyên byte `result.md`, đếm (hoặc dùng lại report khi analysis không đổi), xuất Excel, `source.json` (nguồn gốc, `inference_by_this_run: false`), công bố qua `process_batch` (prepare → publish → đọc lại → acknowledge). `process_batch` nhận `snapshot_inputs` và kiểm "input đổi" trên `input_path`/`input_sha256`.
- Test `tests/unit/test_analysis_run.py` (16): call counter chứng minh đổi từ điển → 0 OCR; đổi mã reporting → 0 lần đếm; đổi mã keyword → đếm lại, 0 OCR; đổi mã extraction → `ocr_identity` đổi; nguồn bị sửa/giả mạo nhất quán hash (synthetic probe, text native, thiếu trang) → `FAILED_DOCUMENT`; nguồn không bị ghi; lỗi ghi ma trận giữa chừng → resume hoàn tất.
- Dữ liệu thật: 5 tài liệu giải nén từ `output/v63.zip` (batch V6.3 đã công bố revision 57) → analysis run với từ điển v1 → 5/5 SUCCEEDED, vector 88 cột trùng khớp ma trận đã công bố (gồm tài liệu có tổng 4 và 1). Bằng chứng: `scratch/migration/v63-real/analysis-p11a-comparison.json`.

## Kết quả P05a

- `src/ocr_runtime`: `paths`, `config`, `models`, `fingerprint`, `dependency_lock`, `process_tree`, `device`, `torch_placement`, `backend_probe`, `structured_logging`, `gpu_lease` (tách `GPULease`, `gpu_snapshot`, `lease_for_gpu` khỏi `gpu_scheduler`; `gpu_scheduler` re-export), `preflight` (`CHILD_PROBE`, `inspect_environment`, `resolve_benchmark_policy` từ `scripts/preflight_v62.py`; script giữ CLI và re-export). `__init__` không import submodule.
- `src/ocr_text`: `unicode_normalizer`, `numeric_guard`, `text_cleaner`.
- Resolver gốc thư mục: `OCR_PROJECT_ROOT`, nếu không thì tìm ngược lên thư mục chứa đủ `pyproject.toml`, `config/profiles-v63.yaml`, `src/ocr_runtime/paths.py`; fallback cho bố cục cài đặt là thư mục chứa `src/`. `is_checkout()` thay cho kiểm riêng `pyproject.toml` trong `paths`. `gpu_scheduler.ROOT` và `docling_structure.ROOT` lấy từ `PROJECT_ROOT`. Còn hai nơi kiểm `pyproject.toml` theo cách cũ: `count_keywords` (legacy, đóng băng) và `ocr_bridge` (chuyển ở P07).
- `v63_backend.prepare_backend` gọi `ocr_runtime.preflight`/`ocr_runtime.gpu_lease`, không import `scripts/`. `RUNTIME_SCRIPTS` chỉ còn Docling worker; worker này import thẳng `ocr_runtime.dependency_lock`/`torch_placement`.
- Test: `tests/unit/runtime` (resolver từ CWD khác, override, import supervisor không nạp Torch/ONNX Runtime/NumPy/PyMuPDF, import `ocr_runtime` trong `.venv-v62/docling` và `.venv-v62/text` thật); `tests/unit/text` (chỉ stdlib; numeric guard theo hành vi hiện tại, gồm dấu phẩy đi kèm). `test_venv_interpreter_paths` vá theo nơi tra cứu mới.
- Import-linter: 7 hợp đồng KEPT (thêm `runtime`, `text`; `keywords` cấm `ocr_text`).

## Kết quả P05b

- `src/ocr_pdf_io`: `coordinate_transform`, `native_text_extractor`, `pdf_inspector`, `pdf_renderer`, `region_cropper`, `scan_image` (chuyển nguyên văn; import `ocr_text`/`ocr_contracts`). `ocr_bridge` để lại cho P07.
- `block_is_covered` chuyển sang `ocr_contracts.geometry`; `docling_structure` re-export tên này, `resolve_document_layout` import trực tiếp từ geometry nên tài liệu không còn phụ thuộc Docling client.
- Test `tests/unit/pdf_io` (kích thước render theo DPI, chuỗi tọa độ xoay 0/90/180/270 thuận-nghịch, ma trận suy biến bị từ chối, IoU/coverage, import không nạp thư viện model); test geometry/scan_image/region_cropper hiện có qua. Import-linter 8 KEPT.

## Kết quả P06

- `src/ocr_recognition`: `candidate_scorer`, `fallback_engine`, `primary_engine` (`BaseOCREngine`), `rapidocr_engine`, `text_detector`, `vietnamese_seq2seq_engine`, `native_quality`, `ocr_layer_agreement`, `ocr_quality`, `vietnamese_quality`, `routing_policy`, `route_page`; mới: `hallucination` (`classify_ocr_hallucination`, `calculate_vn_lexicon_ratio`, từ điển), `orientation` (`is_readable_ocr_layout`, `is_glyph_noise`, `orientation_candidate_score`).
- `src/ocr_layout`: `dla_engine`, `page_content_analyzer`, `model_adapters`, `torch_layout`; mới: `steps` (`apply_layout_model(engine, renderer, config, ...)`, `link_blocks_to_regions`).
- `ProcessPageUseCase` vẫn điều phối cả V6.3 và legacy; các bước trên được di chuyển nguyên văn và lớp chỉ uỷ quyền (giữ tên phương thức/hằng cho test và legacy). Bản đồ chức năng trước → sau: file 1788 → khoảng 1530 dòng; `classify_ocr_hallucination` 57 → 2, `_orientation_candidate_score` 57 → 1, `_is_glyph_noise` 29 → 1, `_calculate_vn_lexicon_ratio` 14 → 2, `_is_readable_ocr_layout` 7 → 1, hằng từ điển 21 → 3, `_apply_layout_model` 65 → 4, `_link_blocks_to_regions` 36 → 1. `_execute_page` (điều phối trang) chưa tách; orchestrator V6.3 riêng làm ở P09.
- Test: `tests/unit/recognition` (kết quả hallucination/orientation ghi từ mã trước khi chuyển, so cả hàm mới lẫn phương thức lớp; double của recognizer luôn `NOT_EXERCISED`, `require_inference` báo lỗi). Import-linter 10 KEPT (`recognition` và `layout` độc lập với nhau).

## Kết quả P07

- `src/ocr_structure`: `document_layout_engine` (bảng heuristic/vector), `diagram_builder`, `hidden_text_layer` (thử nghiệm), `ocr_bridge` (`is_checkout()` thay kiểm `pyproject.toml`), `docling_client` (từ `layout/docling_structure.py`); mới: `enrichment.enrich_structures(extractor, doc_page, page_num, page_type, blocks, tables, regions, meta)` (di chuyển nguyên văn từ `ProcessPageUseCase._enrich_structures`; phương thức lớp uỷ quyền).
- Pha B (`gpu_phase_worker.run_structure`) gọi `enrich_structures` với extractor tường minh, không còn `SimpleNamespace`/`ProcessPageUseCase`. `tests/unit/structure` chạy `run_structure` thật trong subprocess (Docling thay bằng double rỗng, không phải bằng chứng model): sau pha B, `vietocr`, `ocr_recognition`, `process_page`, `torch` đều không có trong `sys.modules`; cầu nối `raster-plus-gpu-text-v1`, `native_text_layer_copied=False`.
- Interface: `DoclingStructureExtractor` (`extract_page`, `cache_fingerprint`, `warmup`, `close`, `enabled`, `options`) là cài đặt hiện có; một backend khác cài cùng các thành viên này là thay được qua `enrich_structures`. `cache_fingerprint` đổi giá trị vì byte của file client đổi (dự kiến).
- Import-linter 11 KEPT (`structure` cấm recognition, layout, Docling, VietOCR, Torch, ONNX Runtime).

## Kết quả P08

- `src/ocr_document` (23 module, chuyển nguyên văn): `region_tree`, `reading_order`, `reading_order_graph`, `xy_cut`, `document_furniture`, `legacy_furniture`, `page_association`, `figures`, `ids`, `section_tree`, `source_identity`, `financial_checks`, `validation` (từ `document_validation`), `contract_schema`, `document_contracts`, `json_exporter`, `manifest_exporter` (`PIPELINE_VERSION`), `markdown_exporter`, `output_contract`, `result_reader`, `export` (`DocumentExporter`), `resolve_document_layout`, `resolve_document_furniture`.
- Completion marker: phần marker thuần (`clear_completed`, `verify_completed`, `write_completion_marker`) chuyển sang `ocr_artifacts.completion` và không import validator nào. `src.ocr.infrastructure.export.completion.mark_completed` ở đường dẫn cũ là hàm ghép: kiểm bằng `ocr_document.validation.validate_document` cộng các nhóm artifact do caller truyền, rồi mới ghi marker. Cổng giữ nguyên: không ghi marker khi validation FAIL hoặc nhóm khai báo thiếu validator.
- Version động: `pyproject.toml` đọc `PIPELINE_VERSION` tĩnh từ `src/ocr_document/manifest_exporter.py` (setuptools AST, không import; đã kiểm `read_configuration` trả `6.3.0.dev1`).
- JSON Schema sinh từ `contract_schema` (21 model và `contract_json_schemas()`) trùng hoàn toàn trước và sau khi chuyển (`scratch/migration/contract_schema_before_p08.json`).
- `tests/unit/document`: xuất fixture trang V6.3 thật thành tài liệu trong subprocess; không nạp Torch, VietOCR, ONNX Runtime, Docling, recognition, layout, structure, keywords, reporting hay `process_page`. Test hồi quy export (`test_migration_v63_export_baseline.py`) vẫn trùng từng byte. Import-linter 12 KEPT.

## Kết quả P09a

- `src/ocr_pipeline` (CPU): `cli` (`main_v63`; facade `src.ocr.cli.unified` giữ dispatch legacy), `backend`, `scheduler` (`run_document` khởi chạy `-m ocr_workers.phases`), `document_owner` (khởi chạy `-m ocr_pipeline.document_owner`), `batch`, `document`, `keyword_finalization`, `publication`, `recount`, `analysis_run`, `batch_store`, `artifact_validation`, `keyword_validation`, `completion` (hàm ghép `mark_completed`).
- `src/ocr_workers`: `phases` (pha A/B/export), `docling_server` (từ `scripts/docling_structure_worker.py`; script thành wrapper `runpy`, client vẫn khởi chạy theo đường dẫn; `cache_fingerprint` băm thêm file server qua `paths.docling_server_module()`).
- Giao thức có version `ocr_contracts.protocol` (`document-worker-v1`): request có `request_id`, `attempt_id`, cấm field lạ; response được kiểm schema, phải đúng request và attempt; owner trả `infrastructure` khi request sai protocol.
- Danh sách closure fingerprint cập nhật theo đường dẫn mới.
- Import-linter 14 KEPT (thêm `pipeline`, `workers`; `extraction` lấy nguồn `ocr_workers`).
- GPU thật trên sample khớp baseline (`run-p09a.comparison.json`); CLW 32 trang, PJT 21 trang, HTL 26 trang chạy thành công bằng orchestrator cũ để làm baseline cho P09b (`scratch/migration/v63-baseline/{clw,pjt,htl}-p09a`).

## Kết quả P09b

- Tách thêm các bước nội tuyến của `_execute_page` thành hàm dùng chung (di chuyển nguyên văn, lớp legacy uỷ quyền): `ocr_recognition.blocks` (`ocr_results_to_blocks`, `mark_review_regions`), `ocr_recognition.inference.predict_image_counted`, `ocr_recognition.ocr_layer_agreement.page_layer_agreement`, `ocr_pdf_io.scan_image.full_page_image_provenance`, `ocr_structure.enrichment.drop_blocks_inside_tables`, `ocr_document.page_assembly` (`assign_region_statuses`, `build_page_quality`, `build_evidence_blocks`).
- `ocr_workers.page_engines`: composition root duy nhất cho engine trang (`build_page_engines`, `validate_page_config`), dùng bởi cả `ProcessPageUseCase` và orchestrator mới.
- `ocr_workers.text_page.TextPageExtractor`: orchestrator pha A riêng của V6.3; từ chối cấu hình không phải V6.3. `phases.run_text` dùng nó cho `gpu_ocr_only_v1`; đường V6.2 legacy vẫn dùng `ProcessPageUseCase` (ngoại lệ tạm đã khai báo).
- Phản hồi giám sát độc lập (`scratch/codex-review-20261022/REVIEW.md`, không sửa bằng chứng của reviewer):
  - F03 (P2): đúng. Sau khi chuyển phần dựng engine, bốn test (`test_kaggle_worker_failures`, `test_v6_numeric_guard`, `test_v6_scan_table_experiment`, `test_v6_conversion_timing`) vẫn vá tên lớp qua `process_page` nên chạy model/Docling thật; lượt full suite P09b đầu tiên vì thế có 6 lỗi và mất 2 giờ 40 phút. Đã chuyển patch sang `ocr_workers.page_engines`. Test toạ độ hiển thị nay chạy trên cả `ProcessPageUseCase` và `TextPageExtractor`. Thêm guard `test_engine_patches_target_the_composition_root`. Không hạ assertion, không skip.
  - F01 (P1): đúng. Nhánh `source.json` của `verify_source` từng tin provenance tự khai. Nay: đi theo `extraction.source_dir`, chạy lại `verify_extraction_source` trên extraction gốc, buộc hash `result.md` đang đếm bằng hash của extraction đã kiểm, và `ocr_identity`/`manifest_ocr_sha256`/`ocr_receipt_sha256` khớp với lần analysis trước. Thiếu extraction thì `FAILED_DOCUMENT`.
  - F02 (P1): đúng. Discovery nay lấy tập tài liệu kỳ vọng từ `batch_input_manifest.json`. Thiếu `result.md` hay thư mục thì giữ hàng với `source_error`; thiếu manifest/receipt thì thất bại ở bước kiểm. Nguồn standalone hỏng thành một hàng lỗi. Lỗi thiếu file khi kiểm là lỗi tài liệu, không phải lỗi hạ tầng.
  - Hồi quy mới trong `tests/unit/test_analysis_run.py`: nguồn tự khai; nguồn trỏ extraction thật nhưng khác text; text chuỗi bị sửa rồi niêm phong lại hash/marker; chuỗi mất extraction; chuỗi hợp lệ vẫn thành công và chỉ đọc; mất `result.md`/manifest/receipt/cả thư mục giữ đủ 3 hàng; nguồn standalone hỏng. Kịch bản probe của reviewer chạy trên bản sao (`scratch/migration/review-f01-f02/analysis-contract-results.json`): `a` thành `FAILED_DOCUMENT` thay vì bị bỏ; nguồn tự khai `FAILED_DOCUMENT`, không có số đếm.
  - Hệ quả: một tập con giải nén từ batch 50 tài liệu (như thử P11a trên `v63.zip`) nay công bố đủ 50 hàng, trong đó các tài liệu không có trên đĩa là `FAILED_DOCUMENT`.
  - File sửa cho F01/F02: `src/ocr_pipeline/analysis_run.py`, `tests/unit/test_analysis_run.py`. File sửa cho F03: `tests/unit/{test_kaggle_worker_failures,test_v6_numeric_guard,test_v6_scan_table_experiment,test_v6_conversion_timing,test_phase_b_mixed_composition,test_migration_aliases}.py`.
  - Reviewer kiểm lại độc lập lúc 17:39 (`scratch/codex-review-20261022/recheck-1736/{junit.xml,verification.json,analysis-contract-results.json}`): 116 test liên quan PASS, 359 file mã/test/pyproject không đổi trong lúc chạy, hai probe gốc trên fixture mới cho kết quả đúng. Phạm vi xác nhận là F01–F03, không phải nghiệm thu toàn bộ P09–P13.
- Full suite chuẩn sau khi sửa (`tests/unit tests/scientific tests/legacy_compat`): 1087 passed, 1 skipped, 4 phút 42 giây (`scratch/migration/junit-p09b.xml`, `pytest-p09b.log`). Test chậm nhất 10,9 giây, nên không test double nào chạm tới model thật (lượt trước khi sửa F03: 2 giờ 40 phút). Skip duy nhất: `test_real_linux_venv_package_is_lost_only_when_python_symlink_is_resolved` (chỉ chạy trên Linux CI) là NOT_RUN trên máy này.
- GPU thật, orchestrator mới so với orchestrator cũ (P09a) trên cùng PDF: sample 1 trang, CLW 32 trang, PJT 21 trang, HTL 26 trang, tổng 80 trang (`scratch/migration/v63-baseline/{sample,clw,pjt,htl}-p09b`). Mỗi lượt tạo job generation mới, không tái dùng job cũ; pha A detector/recognizer/layout và pha B Docling đều `VERIFIED_INFERENCE` trên CUDA.
  - `compare_runs.py`: `result.md`, `document.md`, `extraction.json`, `structure.json`, `document.json` và `pages/page-*.md` trùng từng byte; JSON trang và JSON pha A trùng từng trường, kể cả thứ tự khoá (trường thời gian/pid loại trừ). Kết quả: `{sample,clw,pjt,htl}-p09b.comparison.json`, cả bốn `identical: true`.
  - Receipt/provenance (`p09b-receipts.comparison.json`): số đếm keyword, hàng batch, `validation.json` trùng. Khác biệt còn lại đều có lý do: `ocr_identity`, `source_fingerprint`, `cache_key` đổi vì mã extraction đổi; `analysis_fingerprint` đổi vì sửa F01/F02 trong `analysis_run.py`; hash file trong receipt/marker đổi theo các file có thời gian; pid, `time_ns`, đường log, `source_file` (thư mục output khác).
  - Không có ground truth người gán: đây là bằng chứng không hồi quy so với mã cũ, không phải đo độ chính xác OCR (NOT_EVALUATED).
- Patch trạng thái cuối P09: `scratch/migration/after-P09.patch`.

## Kết quả P10

- Metadata (`pyproject.toml`): dependency gốc chỉ có pydantic, đủ cho `ocr_contracts`, `ocr_artifacts`, `ocr_keywords`. Extras:
  - `reporting`: openpyxl.
  - `app`: PyMuPDF, PyYAML, psutil, openpyxl (supervisor, document owner, analysis run, CLI V6.3).
  - `inprocess`: Torch, VietOCR, OpenCV và phần còn lại của `requirements.txt`, cùng khoảng phiên bản cũ. Đây là nền chung của `legacy`, `gpu`, `cpu-benchmark`, qua self-reference `ocr-pdf[inprocess]`, nên `.[gpu]` và `.[cpu-benchmark]` vẫn cài đủ như trước.
  - `legacy`: thêm RapidOCR, ONNX Runtime CPU.
  - `test`, `research`, `dev` (import-linter).
  - Không đổi phiên bản dependency hay model nào. Không đưa công cụ soạn tài liệu vào extra sản xuất.
- Wheel (`setup.py`):
  - Các package `ocr_*` cài top-level từ `src/`. Namespace legacy `src.ocr` vẫn cài dưới tên cũ; đây là ngoại lệ chuyển tiếp (D2), bỏ khi không còn consumer import `src.ocr` (entry point `ocrpdf*`, script, notebook, test). `benchmark` là top-level có sẵn từ trước, giữ cho `ocrpdf-perf`.
  - Wheel không còn bản `src.ocr_*` thứ hai, cũng không chứa `egg-info` (`include-package-data = false`).
  - Resource (profile legacy và V6.3, từ điển, font bridge, hardware, wrapper Docling server) chép lúc build từ nguồn duy nhất vào `ocr_runtime/resources`.
  - Version đọc tĩnh từ `ocr_document.manifest_exporter.PIPELINE_VERSION`: wheel `ocr_pdf-6.3.0.dev1`.
- Resolver (`ocr_runtime.paths`):
  - Vị trí mã tách khỏi `PROJECT_ROOT`. `PACKAGE_ROOT` là thư mục chứa `ocr_*`, `LEGACY_ROOT` là thư mục chứa namespace `src`, và `source_tree()` cho biết đang chạy từ checkout hay wheel.
  - `code_roots()` lấy từ vị trí mã, không lấy từ `OCR_PROJECT_ROOT`.
  - Khi cài wheel và không tìm thấy checkout, `PROJECT_ROOT` là thư mục làm việc, giống các đường dữ liệu mặc định.
  - `src/ocr/__init__.py` chỉ thêm `src/` vào `sys.path` khi có package `ocr_*` nằm cạnh.
- Fingerprint (`ocr_runtime.fingerprint`):
  - Băm theo tên tương đối kiểu checkout (`src/ocr_runtime/paths.py`, `scripts/docling_structure_worker.py`) cả khi chạy từ wheel. Cùng mã thì cùng fingerprint ở hai bố cục; bản cài bị sửa thì fingerprint đổi.
  - Trên checkout, thuật toán mới cho đúng giá trị cũ: kiểm trên cùng cây, full/extraction/analysis/publication và danh sách 265 file trùng.
  - Sau P10, analysis và publication giữ nguyên giá trị (`9432cbbff6fd6723`, `299d6661378fd527`), chỉ extraction đổi, vì mọi file P10 sửa đều thuộc closure extraction.
- Cách nạp mã vào worker (quyết định P10.3): giữ `PYTHONPATH` từ checkout, không cài wheel vào `.venv-v62/*`. `prepare_backend` của V6.3 từ chối khi chạy từ wheel (`NOT_SUPPORTED`), vì `PYTHONPATH` lúc đó sẽ đưa site-packages của CPU app vào runtime GPU có lock riêng. Chạy V6.3 GPU từ wheel là khả năng mới, chưa làm.
- Lock CPU app:
  - `requirements/v63/{windows,linux}-cpu-app.lock` có hash, 10 package. Constraints chuyển vào `requirements/v63/cpu-app.constraints.txt` (trước nằm ở `scratch/`, không được Git quản lý). Biên dịch lại cùng cờ: pin và hash không đổi, chỉ đổi dòng chú thích nguồn.
  - `verify_installed_lock` trên `.venv` theo lock Windows: VERIFIED.
  - Lock này chưa thành cổng runtime, vì notebook Kaggle V6.3 cài supervisor theo khoảng phiên bản.
- Ma trận cài/import/build (`scratch/migration/p10_matrix.py`, kết quả `scratch/migration/p10-matrix/matrix.json`): wheel build từ bản sao sạch, venv và thư mục làm việc nằm ngoài checkout, không có `PYTHONPATH`.

  | Slot | Kết quả |
  | --- | --- |
  | keyword-only (gốc) | Chỉ cài pydantic. Đếm với từ điển đóng gói chạy được; import `ocr_reporting` và `ocr_pipeline` lỗi do thiếu openpyxl; không nạp NumPy/Torch/PyMuPDF/YAML/psutil |
  | reporting-only | Thêm openpyxl; xuất và kiểm workbook VERIFIED |
  | CPU app | Import đủ `ocr_runtime` và `ocr_pipeline`, không nạp Torch/ONNX Runtime/NumPy. Analysis run trên hai extraction V6.3 thật (sample, PJT 21 trang) cho số đếm trùng batch gốc. `ocrpdf-batch --help` chạy; backend GPU V6.3 bị từ chối đúng thiết kế |
  | text worker, Docling worker | Không cài wheel: mã nạp từ checkout qua `code_roots()` mới. Lượt GPU thật sau P10: sample và CLW 32 trang trùng P09b (`scratch/migration/v63-baseline/{sample,clw}-p10.comparison.json`); sau khi sửa F04, sample trùng lần nữa (`sample-p10b.comparison.json`). Pha A detector/recognizer/layout và pha B Docling đều `VERIFIED_INFERENCE` trên CUDA |

  Ở mọi slot: `uv pip check` sạch và fingerprint của bản cài trùng checkout. `uv pip install --dry-run "<wheel>[legacy]"` giải được 63 package (torch 2.12.1+cpu, VietOCR, RapidOCR, ONNX Runtime). NOT_RUN: cài thật extra `legacy`/`gpu` từ wheel.
- Test mới `tests/unit/runtime/test_packaging.py`:
  - Dependency gốc tối thiểu.
  - Pin của `cpu-app.in` nằm trong khoảng extra `app` và khớp cả hai lock; lock không trỏ vào `scratch/`.
  - Bố cục cài đặt mô phỏng: cùng fingerprint, `code_roots` một thư mục, resource đúng chỗ, backend V6.3 bị từ chối, sửa file đã cài làm đổi extraction mà không đổi analysis/publication.
  - Trên checkout, tên và thứ tự file không đổi.
- Test sửa theo tên mới (không hạ assertion): `test_closures_partition_the_code` so theo tên tương đối, `test_editing_a_new_package_changes_the_fingerprint` vá `LEGACY_ROOT`.
- Cài đặt đã cập nhật:
  - README: extra `app` cho supervisor; `.[reporting]` cho môi trường đếm độc lập; thêm ghi chú về wheel.
  - CI: một lệnh `-e ".[legacy,test]"` thay cho `requirements-legacy.txt` cộng `.[test]`. Hai cách cho cùng tập dependency. NOT_RUN: chưa có lượt GitHub Actions.
  - Không cần sửa: `scripts/setup.sh` (cài `requirements-legacy.txt` rồi `-e . --no-deps`), `docker/Dockerfile` và notebook Kaggle legacy (cùng gọi `setup.sh`), notebook Kaggle V6.3 (cài supervisor riêng, chạy từ checkout). NOT_RUN: build Docker, Kaggle.
- Phản hồi giám sát F04 (P2, `scratch/codex-review-20261022/packaging-recheck-1806/unrelated-project-probe.json`, không sửa bằng chứng của reviewer): đúng.
  - Nguyên nhân: `CountKeywordsUseCase.resolve_keywords_file` còn kiểm `PROJECT_ROOT/pyproject.toml` theo cách cũ (đã ghi ở P05a là chỗ chưa chuyển). Sau P10, `PROJECT_ROOT` của wheel là thư mục làm việc. Khi CWD là một dự án Python khác, resolver chọn `config/keywords.txt` không tồn tại (`FileNotFoundError`). Nếu dự án kia có file cùng tên thì còn tệ hơn: đếm bằng từ điển lạ mà không báo lỗi.
  - Rà cùng lớp lỗi: mặc định `--keywords-file` của CLI V6.3 (dùng cho `--analysis-from`, không cần GPU) cũng dựng từ `PROJECT_ROOT/config` nên sửa cùng. Các mặc định còn lại dựng từ `PROJECT_ROOT` (`gpu_runner`, `backend`, Docling legacy) thuộc đường GPU cần checkout; V6.3 đã từ chối wheel tường minh.
  - Sửa: resolver chung `ocr_runtime.paths.default_keywords_path()` chỉ chọn `config/keywords.txt` khi `is_checkout()` đúng, còn wheel dùng `runtime_resource("keywords.txt")`. `count_keywords` và CLI V6.3 dùng chung hàm này; `keywords_file` chỉ định tường minh vẫn ưu tiên cao nhất.
  - Hồi quy:
    - `test_another_projects_dictionary_is_never_selected`: dự án lạ có cả `pyproject.toml` lẫn `config/keywords.txt`.
    - `test_checkout_uses_its_config_dictionary`.
    - `test_wheel_uses_bundled_keywords` vá theo resolver mới.
    - `test_installed_layout_in_another_project_counts_with_the_bundled_dictionary`: bố cục cài đặt, subprocess, CWD là dự án khác; kiểm cả legacy, CLI và override.
    - Với resolver cũ chép vào bố cục cài đặt, probe này thất bại đúng `FileNotFoundError` như reviewer báo.
  - Reviewer kiểm lại độc lập trên wheel mới (SHA-256 `37b8f995…d2528`, `python -I -B`; `scratch/codex-review-20261022/f04-recheck-1821/verification.json`): legacy chọn đúng resource đóng gói, override giữ ưu tiên, `--analysis-from` dùng mặc định đúng và vector keyword trùng extraction thật, module đã cài khớp byte với wheel. F04 đóng trong phạm vi đó; kết quả wheel P10 không dùng để nghiệm thu P11b.
  - Wheel thật build lại, `python -I -B`, CWD là dự án khác nằm ngoài checkout, không đặt `OCR_PROJECT_ROOT`: `PROJECT_ROOT` là CWD, `is_checkout` sai, legacy và CLI đều chọn từ điển đóng gói, override thắng, đếm legacy SUCCEEDED (`scratch/migration/p10-matrix/matrix.json`, mục `unrelated_project_cwd`).
- Full suite trên mã P10 cuối (gồm sửa F04): 1095 passed, 1 skipped (`scratch/migration/junit-p10.xml`, `pytest-p10.log`); lỗi khoá file `.xlsx` không lặp lại. Patch: `scratch/migration/after-P10.patch`.
- Quan sát trong full suite P10 lượt đầu: `test_edited_chain_text_is_not_legitimized_by_new_hashes` lỗi một lần, `PermissionError` [WinError 5] khi `os.replace` file ma trận `.xlsx` vừa ghi. Chạy riêng 5/5 lần qua. Mã publication đóng mọi workbook trong `finally`, P10 không sửa `atomic_io` hay publication. Ghi nhận là lỗi khoá file tạm thời của Windows; lần lặp thứ hai ở P11b (commit stage) dẫn tới sửa chung bằng retry có giới hạn trong `ocr_artifacts.atomic_io.replace` (xem "Kết quả P11b").

## Kết quả P11b (thay đổi hành vi có chủ đích)

- Đồ thị stage: PDF → pha A (text) → pha B (structure) → export → báo cáo keyword → Excel/công bố.
  - Pha A và pha B ghi vào thư mục cache đánh địa chỉ theo nội dung `.cache/v63-stages/<phase>/<key>/`. Mỗi thư mục có các file của pha, `done.json` (`stage-receipt-v1`: `key`, `files`, `input_receipt_sha256`) và `exited.json` (ghi sau khi xác minh cây process đã thoát).
  - Export luôn chạy, ghi vào thư mục output.
  - Báo cáo keyword và Excel giữ cơ chế P11a: identity analysis, analysis run, ledger.
- Stage key (`ocr_pipeline.scheduler.stage_key`, `stage-key-v1`) gồm:
  - Fingerprint closure mã của chính pha.
  - Cấu hình hiệu lực:
    - Pha A dùng cấu hình đầy đủ, chỉ `docling.enabled=false` đúng như pha A chạy.
    - Pha B và export dùng cấu hình đầy đủ. Không bỏ khoá cấu hình nào khỏi identity.
  - Model và lock pha đó nạp:
    - Pha A: detector, VietOCR, layout model.
    - Pha B: model Docling (gồm layout model dùng chung), registry, font bridge, lock Docling.
    - Lock text tính cho mọi pha. File không rõ vai trò tính cho mọi pha.
  - Interpreter, thiết bị và protocol.
  - Đầu vào:
    - Pha A: hash PDF và trang chọn.
    - Pha B: hash `done.json` của pha A.
    - Export: hash `done.json` của pha B, cùng `assets`, `output_mode`, `finalize_document`, `config_path`, `keywords_file`.
- Closure mã theo pha (`ocr_runtime.fingerprint.stage_entries`):
  - Bao đóng import tĩnh (cấp module và trong hàm, đọc bằng AST, cùng tên ở checkout và wheel) từ module của pha. Pha A là `ocr_workers.phase_text`, pha B là `phase_structure` cộng `docling_server` và script wrapper, export là `phase_export`; cả ba cộng entry `phases` và `stage_io`.
  - Đường V6.2 legacy khai báo riêng (`LEGACY_STAGE_ROOTS`: `process_page` cho pha A, `export_document` cho export). Không có cài đặt legacy thì phép duyệt dừng ở đó.
  - Kích thước hiện tại: pha A khoảng 82 file, pha B khoảng 20 (không có recognition/layout/document), export khoảng 46 (không có recognition/layout/structure).
  - Chốt an toàn lúc chạy: sau mỗi pha, `assert_loaded_code_in_stage` từ chối mọi module dự án đã nạp nằm ngoài closure (`STAGE_CLOSURE_VIOLATION`). Import mà phân tích tĩnh bỏ sót sẽ làm pha thất bại, không để mã đổi dùng lại kết quả cũ.
  - Worker kiểm closure đang chạy khớp `code` của stage key trước khi chạy.
- Tách `ocr_workers.phases` (di chuyển nguyên văn, chỉ đổi chỗ tra thư mục): `phase_text`, `phase_structure`, `phase_export`, `stage_io` (đọc/ghi receipt; request cũ chỉ có `job_dir` vẫn dùng bố cục cũ). `phases` còn là entry `-m`, nạp pha theo tên và giữ tên cũ (`run_text`, `run_structure`, `run_export`, `phase_b_status_accepted`) qua `__getattr__`. Ngoại lệ import tạm đổi tên theo: `phase_text -> process_page`, `phase_export -> export_document`.
- Chính sách tái dùng:
  - Chỉ khi có `--resume` và không `--force-ocr`, giống cache trang legacy. Khi đó stage có `exited.json`, mọi file còn đúng hash, đúng key và đúng receipt upstream thì được dùng lại.
  - Thư mục `.tmp-*` (đang ghi dở hoặc sót sau crash) không bao giờ được dùng.
  - Chạy không `--resume` thì chạy lại và thay thư mục cùng key.
  - Batch đã khoá mã vẫn từ chối resume sau khi mã đổi (`verify_runtime`). Muốn dùng lại pha A sau khi sửa mã pha B thì chạy batch mới với `--resume`.
- Provenance: `manifest.gpu_runtime.stages.<phase>` có `key`, `reused`, `receipt_sha256`, `produced_by_generation`, `historical_seconds`. Thời gian của pha dùng lại không cộng vào `total_time_seconds`/`startup_seconds` của lượt này. Bằng chứng placement của pha dùng lại là của lần chạy tạo ra nó; `validate_gpu_source` vẫn kiểm.
- Tương thích:
  - `ocr_identity` cấp tài liệu và công thức `generation` không đổi (digest baseline P01 vẫn qua).
  - Job dir cũ `.cache/v62-jobs/<generation>` không được dùng lại theo bố cục mới; không viết lại hash cũ.
  - Batch, analysis run và recount cũ giữ cách đọc/kiểm.
- Test:
  - `tests/unit/test_stage_cache.py`, 22 test. Worker giả chạy bằng subprocess thật và ghi receipt qua `stage_io` thật; call log chứng minh pha nào chạy:
    - lượt đầu và lượt resume (chỉ export);
    - đổi mã export, pha B, pha A;
    - đổi lock Docling hay model Docling (pha A dùng lại);
    - đổi lock text hay model VietOCR (chạy lại hết);
    - đổi cấu hình, trang, PDF; đường legacy;
    - output stage bị sửa; stage chưa commit hoặc thư mục tạm;
    - pha lỗi (không commit downstream; resume bắt đầu lại từ pha lỗi);
    - phân vai model/lock;
    - closure thật theo pha (mã contracts/artifacts dùng chung có trong cả ba);
    - nạp module ngoài closure bị từ chối;
    - worker từ chối khi mã khác stage key.
  - `test_checkpoint_hashes_key_and_predecessor` viết lại cho `valid_stage`/`committed_stage`, giữ đủ thuộc tính cũ.
  - Ca đổi Excel/keyword (không OCR) và crash khi công bố đã có từ P11a/P09 (`test_analysis_run.py`, `test_replace_then_ack_crash_reconciles_without_rewriting_same_revision`).
- Full suite trên mã P11b cuối (gồm F05 và `atomic_io.replace`): 1132 passed, 1 skipped (`scratch/migration/junit-p11b.xml`). Lượt trung gian trước F05: 1117 passed.
- GPU thật nghiệm thu, trên mã P11b cuối (`scratch/migration/v63-baseline/*-p11c*`, tổng hợp `p11c-reuse.provenance.json`):
  - Lượt mới: sample 93 giây, CLW 32 trang 171 giây; trùng P10 (`sample-p11c` so với `sample-p10b`, `clw-p11c` so với `clw-p10`: đều `identical: true`).
  - Cả ba pha chạy, audit `COMPLETED`, `tree_exited` của từng pha là `true`. Cả hai stage commit hợp lệ (`committed_stage` kiểm cả receipt upstream), hash `done.json` trùng `receipt_sha256` trong manifest. Placement pha A/B `VERIFIED_INFERENCE`.
  - Lượt `--resume` vào output mới: sample 23 giây, CLW 37 giây. Pha A/B `resumed` với đúng key của lượt mới, chỉ export chạy (`tree_exited` true), output trùng lượt mới.
  - Stage key khác các lượt trung gian `*-p11b*`, đúng như F05 yêu cầu (key nay có fingerprint điều phối).
  - Chuỗi so sánh về baseline: P11b trùng P10, P10 trùng P09b, P09b trùng P09a, và sample trùng P01 qua các giai đoạn.
  - `validation` giữ `NEEDS_REVIEW` như baseline. Không có GT người gán: độ chính xác NOT_EVALUATED.
- Reviewer kiểm lại độc lập GPU sau F05 (`scratch/codex-review-20261022/p11b-gpu-recheck-1906/`, không chạy thêm model): lượt mới có inference CUDA thật ở pha A/B và cây process thoát đúng thứ tự; lượt resume giữ đúng key, receipt và upstream A/B, chỉ export chạy; completion, receipt OCR, validator, GPU source toàn tài liệu hợp lệ; artifact ổn định khớp byte với P10, vector keyword khớp. Xác nhận cho extraction fingerprint `99b6f8f8940ae24a`; không quy thành inference của mã P12.
- Patch: `scratch/migration/after-P11b.patch` (bản cộng dồn này đã chứa bản nháp `docs/architecture/CAU_HINH_VA_DU_LIEU.md` của P12).
- GPU thật lượt 1 (`scratch/migration/v63-baseline/*-p11b*`, 18:31–18:35) chạy trên mã **trước** sửa F05 và `atomic_io`. Đây là bằng chứng của bản trung gian, không dùng để nghiệm thu P11b; lượt nghiệm thu là `*-p11c*` bên dưới.
  - Lượt mới (không `--resume`) trên sample và CLW 32 trang trùng P10 (`{sample,clw}-p11b.comparison.json`: artifact ổn định, JSON trang, JSON pha A đều `identical: true`). Placement pha A/B `VERIFIED_INFERENCE`. Cả hai stage được commit (`done.json` và `exited.json`).
  - Lượt `--resume` vào thư mục output mới (`{sample,clw}-p11b-reuse`): dùng lại đúng stage key của lượt mới, audit ghi pha A/B `resumed`, chỉ export chạy. Output trùng lượt mới (`*-p11b-reuse.comparison.json`).
  - Thời gian: sample 101 → 23 giây, CLW 167 → 36 giây. `total_time_seconds`/`startup_seconds` của lượt dùng lại là 0, thời gian gốc nằm ở `historical_seconds`.
  - `validation` giữ `NEEDS_REVIEW` như lượt mới (Docling `confidence=null` theo thiết kế). Bằng chứng placement là của lượt tạo stage. Tổng hợp: `p11b-reuse.provenance.json`.
  - Không có GT người gán: chỉ chứng minh không hồi quy và tái dùng đúng, không đo độ chính xác (NOT_EVALUATED).
- Phản hồi giám sát F05 (P1, `scratch/codex-review-20261022/stage-recheck-1836/`, không sửa probe hay baseline của reviewer): đúng.
  - Nguyên nhân: closure theo pha chỉ gồm mã chạy trong process của pha. Mã dựng request và env cho pha chạy ở supervisor/document owner, ngoài mọi process pha, nên sửa `scheduler`/`backend`/`document_owner` đổi extraction fingerprint mà không đổi stage key nào, và resume vẫn dùng lại A/B.
  - Sửa: một fingerprint mã điều phối dùng chung (`ocr_runtime.fingerprint.COORDINATOR_CODE`, `coordinator_fingerprint()`) nằm trong mọi stage key. Danh sách: `ocr_pipeline/{scheduler,backend,document,document_owner}.py` và `src/ocr/cli/gpu_runner.py` (bộ dựng request V6.2 legacy). Chỉ băm chính các file này, không băm closure import của chúng: các import keyword thuộc closure analysis, và phần helper đóng góp đi tới pha dưới dạng trường request vốn đã là thành phần key. Không đưa toàn bộ extraction fingerprint vào key, nên sửa mã chỉ của pha B vẫn dùng lại pha A (test giữ nguyên).
  - Rà request, env và setup policy:
    - Mọi trường request mà mã pha đọc đều là thành phần key (`pdf`/hash, `pages`, `config`, `device`, hash model/lock, interpreter, `assets`, `output_mode`, `finalize_document`, `config_path`, `keywords_file`) hoặc chỉ là provenance (`generation`, `job_dir`, `output`).
    - Env do scheduler đặt (`CUDA_VISIBLE_DEVICES`, `PYTHONPATH`, `OCR_DOCLING_PYTHON`, chế độ offline) do mã điều phối quyết định, nay đã được băm.
    - Env thừa hưởng chọn file model mà pha nạp nhưng trước đây nằm ngoài key: `VIETOCR_MODEL_DIR`, `OCR_MODELS_DIR` (pha A); `OCR_MODELS_DIR` (Docling ở pha B). Nay là phần `env` của key (`scheduler.stage_env`). Bản F05 đầu cũng đưa `HF_HOME` vào key pha B; khi sửa F06 đã bỏ, vì client Docling luôn đặt `HF_HOME=<models>/docling/huggingface` cho server (`docling_client._start`), nên giá trị thừa hưởng không được đọc. Test nay khẳng định đổi `HF_HOME` chỉ chạy lại export.
    - `OCR_BRIDGE_FONT` đã nằm trong `config.bridge_font`. Preflight và chính sách setup không đổi output, chỉ chấp nhận hoặc từ chối.
  - Hồi quy:
    - Với từng file trong 5 file điều phối, sửa bản sao cây nguồn làm đổi fingerprint điều phối, cả ba stage key mất hiệu lực, và call log cho thấy text/structure/export chạy lại.
    - `VIETOCR_MODEL_DIR` và `OCR_MODELS_DIR` chạy lại hết; `HF_HOME` không chạy lại pha nào ngoài export.
    - `stage_env` giải giá trị tương đối như worker.
    - Mã điều phối là mã extraction.
  - Rủi ro còn lại, chưa sửa vì đổi identity của output đã có: `ocr_identity` cấp tài liệu không chứa các biến env chọn model. Dùng lại output cấp tài liệu chỉ xảy ra khi resume đúng thư mục batch đó, và batch đã khoá mã/runtime.
  - Reviewer kiểm lại độc lập F05 (`scratch/codex-review-20261022/f05-recheck-1851/`): 58 test cache/scheduler/protocol/artifacts PASS; 5 ca sửa bản sao từng file điều phối đều đổi key và chạy lại cả ba pha; sửa riêng pha B vẫn dùng lại pha A; các ca env model, receipt, sửa output, process exit và retry nguyên tử đều qua. F05 FIXED_VERIFIED trong phạm vi lỗi identity; không phải bằng chứng inference thật.
- Lỗi khoá file tạm thời của Windows, lần 2: khi commit thư mục stage, `os.replace` thư mục vừa ghi đôi khi bị từ chối (WinError 5); 2 trên 5 lượt chạy `test_stage_cache.py`. Cùng lớp lỗi với `.xlsx` ở P10. Lượt GPU thật trên Windows cũng có thể làm hỏng cả tài liệu vì lỗi này.
  - Sửa ở primitive chung: `ocr_artifacts.atomic_io.replace` thử lại đúng lệnh `os.replace` (vốn nguyên tử) tối đa 7 lần, tổng khoảng 6 giây. Chỉ áp dụng trên Windows và chỉ cho WinError 5/32; lỗi quyền khác và nền tảng khác báo lỗi ngay.
  - Dùng cho mọi ghi nguyên tử và commit stage.
  - Test: `tests/unit/artifacts/test_atomic_replace.py`, chạy được cả trong venv tối thiểu. Sau khi sửa, 4 lượt liên tiếp sạch.
- Lỗi tìm thấy khi kiểm: `test_scheduler_identity_keeps_worker_env_path` truyền `work_dir` riêng nhưng chưa có `stage_cache_dir`, nên tạo thư mục attempt rỗng trong `.cache/v63-stages/text` thật (2 thư mục `.tmp-*` rỗng). Đã sửa test; số mục trong cache thật trước/sau khi chạy test không đổi. Hai thư mục rỗng đó vô hại (thư mục attempt không bao giờ được dùng lại) và được để nguyên, không xoá cache. Chính sách dọn: P12.

## Kết quả P12

- Tài liệu chuẩn: `docs/architecture/CAU_HINH_VA_DU_LIEU.md`. Gồm nguồn cấu hình theo loại, bảng thứ tự ưu tiên CLI > env > mặc định kèm base của giá trị tương đối, phần nào của identity là thuật toán và phần nào là đường dẫn triển khai, nhóm dữ liệu, quy trình sao lưu/khôi phục batch và ledger SQLite, chính sách dọn (chỉ mô tả, không xoá gì), quyết định không dùng DVC.
- Khai báo trong file profile (`config_schema: ocr-profiles-v1`, `pipeline: v6.3|v6.2|legacy`) ở `config/profiles{,-v62,-v63}.yaml`.
  - CLI chọn nhánh theo thứ tự `--backend`, rồi `pipeline` khai báo, rồi quy tắc cũ theo tên profile/tên file (chỉ cho file chưa khai báo).
  - Khai báo sai là `ConfigError`. Backend V6.3 từ chối file khai báo pipeline khác.
  - Khai báo nằm ngoài dict profile nên không đổi identity.
- Đường dẫn:
  - `paths.v63_cache_root()`: checkpoint và stage cache V6.3 theo `OCR_CACHE_DIR`, mặc định `<gốc dự án>/.cache`. Không đặt biến thì vị trí không đổi; notebook Kaggle V6.3, vốn đặt `OCR_CACHE_DIR`, nay giữ checkpoint ở cache runtime.
  - `paths.absolute_path_env()`: supervisor, backend và scheduler giao cho document owner và worker giá trị tuyệt đối của các biến đường dẫn. Worker chạy với thư mục làm việc là checkout; giá trị tương đối sẽ chỉ chỗ khác, và hai thư mục lease khác nhau thì không loại trừ nhau.
  - GPU lease cố ý không đi theo `OCR_CACHE_DIR`.
- F06 (P1, reviewer `scratch/codex-review-20261022/p12-recheck-1911/`, không sửa probe hay baseline của reviewer): đúng.
  - Nguyên nhân: `prepare_backend` ghim hash các file registry dưới checkout, còn engine VietOCR nạp từ `VIETOCR_MODEL_DIR`/`OCR_MODELS_DIR`. Model ngoài checkout có thể được thay mà hash, `ocr_identity`, stage key và `verify_runtime` đều không đổi.
  - Sửa: một resolver chung `paths.registry_model_path()` (VietOCR theo `vietocr_model_dir()`, các model khác theo `models_dir()`, Docling theo `<models>/docling/huggingface` mà client giao cho server). `prepare_backend` ghim và kiểm hash tại đúng chỗ nạp; engine VietOCR (`VIETOCR_FILES`, `vietocr_model_dir()`) và `ocr_runtime.models` dùng cùng hàm.
  - Kết quả của sửa:
    - Nội dung khác registry: `MODEL_LOCK_MISMATCH`.
    - Thiếu file: `MODEL_MISSING`, trước mọi import model, không tải ngầm.
    - Registry thiếu file VietOCR: `MODEL_REGISTRY_INCOMPLETE`.
    - Registry cập nhật hợp lệ thì đổi `ocr_identity` và key của pha nạp model đó.
    - Worker và `verify_runtime` kiểm lại khi model bị thay sau snapshot hoặc giữa hai tài liệu.
    - Không đặt biến thì mọi đường dẫn ghim trùng đường dẫn checkout cũ, nên identity không đổi.
  - Test `tests/unit/test_model_identity.py` (9): đường dẫn ghim là file pha nạp; nội dung mới tại cùng đường dẫn bị từ chối (VietOCR, model bảng Docling) và snapshot cũ từ chối tài liệu tiếp; cập nhật registry hợp lệ đổi identity và key A, còn cập nhật model Docling giữ key A; thiếu model lỗi trước khi nạp Torch/VietOCR/ONNX Runtime/Docling (subprocess); registry thiếu file VietOCR; không override thì đường dẫn bằng checkout; engine dùng resolver chung; worker từ chối model đổi sau snapshot.
  - Probe của reviewer chạy trên bản sao (`scratch/migration/review-f06/`): bị từ chối ngay ở `prepare_backend` đầu tiên với `MODEL_LOCK_MISMATCH` trên file VietOCR ngoài, vì nội dung của nó không phải nội dung registry ghim.
  - Kiểm lại lần 1 của reviewer (`scratch/codex-review-20261022/f06-recheck-1921/`) chạy trên bản trung gian và báo hai lỗi:
    - Hai test fail là lỗi expectation của test, không phải hợp đồng; đã sửa trước khi nhận phản hồi, có lý do. Tập ghim gồm cả font bridge, vì `prepare_backend` ghim nó cùng registry. File registry cố ý thuộc tập model của pha B: chỉ supervisor đọc nó, và để ngoài pha A thì cập nhật model Docling vẫn dùng lại pha A. Assert thay thế kiểm đúng tính chất đó. Test call counter "sửa riêng mã pha B dùng lại pha A" giữ nguyên.
    - Khe hở runtime là thật: đổi `VIETOCR_MODEL_DIR` sau snapshot thì file đã ghim vẫn còn nguyên nên `verify_runtime` vẫn qua, trong khi worker sẽ nạp file khác.
    - Sửa bằng cách gắn lựa chọn với snapshot:
      - `prepare_backend` trả `model_env` (thư mục model tuyệt đối) và `model_selection` (mục registry → file sẽ nạp), suy từ cùng một lần resolve với `model_hashes`.
      - `GPUProcessor` và scheduler khởi chạy document owner và worker với `model_env` của snapshot, đè lên môi trường hiện tại, nên không tiến trình con nào nạp model chưa ghim.
      - `verify_runtime`, vốn được gọi trước mỗi tài liệu và trong `accept` trước khi nhận kết quả, giải lại lựa chọn và từ chối `MODEL_SELECTION_CHANGED`.
      - Worker pha giải lại lựa chọn trong môi trường của nó và từ chối trước khi chạy.
      - Việc nhận kết quả vẫn gắn với các đường dẫn và hash model đã ghim qua `ocr_identity`.
    - Hồi quy thêm vào `test_model_identity.py` (nay 13 test):
      - Đổi `VIETOCR_MODEL_DIR` hay `OCR_MODELS_DIR` sau snapshot trong khi file gốc còn nguyên thì bị từ chối; dưới `model_env` của snapshot (như document owner nhận) thì qua.
      - `GPUProcessor` và scheduler giao `model_env` của snapshot cho tiến trình con, và phần env của stage key dùng giá trị đó.
      - Worker từ chối lựa chọn đã dịch.
    - Probe đổi env của reviewer chạy trên bản sao (`scratch/migration/review-f06b/`): exit 0, `verify_runtime` báo `MODEL_SELECTION_CHANGED`, không nạp thư viện model. Các ca file đổi, file thiếu và cập nhật registry hợp lệ vẫn giữ.
- Lệnh chẩn đoán chỉ đọc `python -m ocr_runtime.diagnose [--json] [--verify-models]`: bố cục mã, gốc dự án và lý do chọn, từng đường dẫn và nguồn giá trị, khai báo của từng file profile, resource, runtime worker, registry, thư viện đã cài. Không ghi file, không nạp thư viện model (test kiểm cả hai).
- Test `tests/unit/runtime/test_config_and_paths.py` (11): khai báo của ba file profile; định tuyến CLI (khai báo thắng tên file, file chưa khai báo giữ quy tắc cũ, `--backend` thắng); khai báo sai; backend V6.3 từ chối file khai báo khác; thứ tự `--config` > `OCR_CONFIG_PATH` > mặc định cho legacy; V6.3 bỏ qua `OCR_CONFIG_PATH`; mặc định và biến lưu trữ với tên Unicode có khoảng trắng; biến tuyệt đối giao cho tiến trình con; scheduler dùng cache root và giao đường dẫn tuyệt đối; chẩn đoán chỉ đọc.
- Không làm (theo thiết kế P12): không chuyển dữ liệu thật, không lập kho cloud, không DVC (nhu cầu chưa được xác nhận), không đổi identity theo đường dẫn tuyệt đối sang nhận dạng theo nội dung.
- Notebook Kaggle V6.3: gom chẩn đoán từ `RUNTIME_ROOT/cache/v62-jobs` (vị trí mới) và `.cache/v62-jobs` (lượt cũ), thêm tên marker `exited.json` của P11b. NOT_RUN: chưa chạy trên Kaggle.

## Hoàn thiện P12 và triển khai P13 — Codex 22/10/2026

Chủ dự án chuyển Codex từ giám sát Claude sang trực tiếp phát triển. Không gửi thêm phản hồi hay giám sát Claude; lịch giám sát cũ đã xoá theo yêu cầu trực tiếp. Các thay đổi có sẵn của Claude và chủ dự án được giữ nguyên. Không commit/push, không cài/sửa runtime GPU, không nâng model và không chạy toàn bộ input.

### P12 và F06 sau kiểm lại

- Bản Claude cuối đã khóa `model_env`/`model_selection`, kiểm đổi đường dẫn sau snapshot, giao thư mục đã pin cho document owner/worker và từ chối worker chọn file khác. Các lỗi fixture font/registry trong hai test symlink venv được sửa bằng dữ liệu model giả đầy đủ, giữ kiểm interpreter lexical path.
- `ocr_runtime.model_registry` là kiểm completeness dùng chung: detector bắt buộc nằm trong registry, các snapshot layout/table/formula phải được khai báo và mọi file có thể nạp trong snapshot được chọn đều phải được pin. Config processor/tokenizer mới chưa có hash bị từ chối khi prepare, verify_runtime và trước model import của phase. Không quét các revision không được chọn.
- Docling client khóa toàn bộ alias cache Hugging Face/Transformers vào store hiệu lực, loại `DOCLING_ARTIFACTS_PATH` thừa kế và giữ offline policy. Thay đổi dùng chung này cũng tác động client legacy; không thay thuật toán, model hoặc runtime.
- Diagnose kiểm đúng các file ngoài checkout qua resolver chung; thêm `selected_files` để đối chiếu đường dẫn thực.
- Full regression: **1175 passed, 1 skipped**, 1 cảnh báo dependency cũ (`scratch/codex-development-20261022/full-suite.xml`, `full-suite.log`). Skip là symlink venv thật chỉ chạy Linux. Sau tách fixture test CPU, 78 test furniture/worker/import liên quan tiếp tục PASS (`final-delta.xml`). Không cộng các nhóm chồng lặp thành tổng mới.
- GPU thật trên bản mới, extraction fingerprint `10b2da91cd9cdd59`: sample fresh, batch resume và stage resume sang output mới với cache có Unicode/khoảng trắng. Cổng receipt/completion/source hợp lệ, A/B đã thoát trước downstream; batch resume không extraction mới; stage resume tái dùng A/B và chỉ export chạy. Sáu artifact ổn định khớp byte baseline P11b sau F05 và vector keyword trùng. Bằng chứng: `scratch/codex-development-20261022/gpu-sample/verification.json`.
- F06 được xác minh bằng unit/subprocess và inference nhỏ trên cấu hình mặc định. Không lấy probe model giả hoặc bản GPU lịch sử để gắn thành inference của mã mới. Validation vẫn `NEEDS_REVIEW`; độ chính xác trên GT vẫn `NOT_EVALUATED`.

### P13 triển khai và phạm vi nghiệm thu

- Workflow chia job package nhẹ (contracts/artifacts/text/keywords/reporting) theo dependency trực tiếp; text không cài pydantic. Tách CPU document/pipeline, import/protocol/cache/process-tree, wheel ngoài checkout, legacy/inprocess và model/GPU opt-in. Các probe forward Torch nằm ở job legacy có Torch, không kéo Torch vào CPU app.
- Bổ sung hai công cụ CI có thể chạy cục bộ: `scripts/ci/check_wheel.py`, `scripts/ci/check_gpu_sample.py`. Chúng dùng work/output/cache mới, không xoá dữ liệu có sẵn. GPU lease vẫn dùng chung máy.
- Siết ma trận import đúng bảng thiết kế; test cấy vi phạm trong cây tạm chứng minh 117 cạnh bị cấm, 52 cạnh được phép, đường vòng gián tiếp, external imports và đúng hai ngoại lệ legacy. Không sửa source để cấy vi phạm.
- Wheel thật build offline từ bản sao, SHA-256 `513a7cc51ab6e92f4617061bbe94fb472da7e5501f2c5fbd6d5dbd8a8b825473`; cài vào ba venv core/reporting/app mới ngoài checkout, dùng `python -I -B` trong dự án khác có dictionary sai. Cả ba PASS, mỗi slot đối chiếu 301 file đã cài với wheel. Bằng chứng `scratch/codex-development-20261022/wheel/verification.json`.
- Kiểm package nhẹ thực: core (contracts/artifacts/keywords) 39 PASS; reporting 9 PASS; text 3 PASS, không có pydantic hoặc stack OCR (`light-isolation.json`, `light-*.xml`). Job CPU/contract trên app tối thiểu: 200 PASS, 1 SKIP Linux, 2 ca Torch chuyển sang job legacy (`isolated-app-accepted.xml`); xem báo cáo nghiệm thu.
- README gốc và README các package mô tả cấu trúc mới. Hướng dẫn module, API/ownership, schema, lock, baseline, fingerprint, xử lý batch cũ và alias nằm ở `HUONG_DAN_PHAT_TRIEN_MODULE.md`; bảng import máy đọc được tiếp tục là `module_map.json`.
- Báo cáo nghiệm thu: `NGHIEM_THU_KIEN_TRUC_20261022.md`. **Chưa chạy** GitHub Actions, image Docker đầy đủ hai runtime hoặc notebook Kaggle. (Lúc viết dòng này Linux cũng chưa chạy; container Linux CPU, symlink venv và process cleanup thực chạy sau đó, xem mục kế tiếp.) P13 giữ IN_PROGRESS cho các bằng chứng môi trường đó; định nghĩa workflow và test double không phải lượt CI/inference thực. Thiếu GT không được đổi thành kết luận chất lượng.

### P13 kiểm tiếp trên Linux và bản sửa ref cuối — Codex

- Phát hiện và sửa thiếu khóa refs Hugging Face/khai báo repo không trùng Docling loader. Trước sửa 5 ca mới FAIL; sau sửa nhóm liên quan 65 PASS, 1 SKIP Linux trên Windows (`ref-before.xml`, `ref-after.xml`). Không sửa model/registry thật.
- Windows runtime/notebook/import 52 PASS; integration native/keyword 5 PASS. Job CPU mở rộng toàn bộ runtime; job legacy chạy cả integration native.
- Linux Python container offline, source mount read-only: **247 PASS, 2 SKIP** (worker GPU chưa cài), 2 ca Torch loại đúng khỏi CPU app. Symlink venv thực, timeout và orphan cleanup đều PASS. Bằng chứng: `scratch/codex-development-20261022/linux-accepted-evidence/`.
- Wheel cuối SHA-256 `1c98038ace13a31a5a3b954bb14eb7b14a6ceb9f64576119c709b47f95955f3d`: core/reporting/app PASS trên Windows và Linux, 301 file/slot đối chiếu bytes ngoài checkout.
- GPU bản cuối extraction `2d3e8784a473b552`: sample mới, batch reuse và stage reuse PASS; bốn placement VERIFIED_INFERENCE; sáu artifact và keyword vector khớp baseline (`gpu-final/verification.json`). Code fingerprint trước/sau Linux và GPU khớp.
- Báo cáo có ma trận 8 yêu cầu P13, dependency thực 13 package và compatibility policy. P13 chưa chốt nghiệm thu target GitHub Actions/image lab đầy đủ/Kaggle; các môi trường đó NOT_RUN. GT NOT_EVALUATED. Không commit/push, không giám sát/liên lạc Claude.

### Kiểm lại bản P12/P13 của Codex — Claude 23/10/2026

Đối chiếu với mục P12, P13, "Quy tắc phụ thuộc" và "Bảng kiểm chung" của thiết kế. Không sửa evidence của Codex hay reviewer; mọi lượt chạy ghi vào `scratch/migration/p13-review/`.

- Kiểm độc lập, đạt:
  - Toàn bộ unit/scientific/legacy_compat trên mã hiện tại: 1180 passed, 1 skipped (symlink venv thật, chỉ Linux) (`junit-full.xml`, `pytest-full.log`).
  - Fingerprint mã hiện tại trùng lượt GPU cuối của Codex: extraction `2d3e8784a473b552`, analysis `ce808ef92e712dc4`, publication `76b4cc9a380b8f99`. Các sửa dưới đây chỉ chạm test, `pyproject.toml` và tài liệu, nên fingerprint không đổi và bằng chứng GPU đó vẫn áp dụng cho mã hiện tại.
  - `compare_runs.py` tự chạy trên output GPU của Codex: lượt mới và lượt stage-resume đều trùng `sample-p11c`, gồm artifact ổn định, page JSON và page JSON pha A từng trường.
  - `validate_registry` nhận registry thật (34 file). Notebook Kaggle tải snapshot đầy đủ theo revision đã ghim và ghi `refs/*`, khớp với cổng mới; vẫn NOT_RUN trên Kaggle.
  - Lượt GPU P12 của Claude (`v63-baseline/sample-p12`, `sample-p12-cachedir`, có cache Unicode/khoảng trắng) trùng P11c. Lượt này chạy trên mã trước `model_registry` của Codex, nên chỉ là bằng chứng trung gian.
- Thiếu so với thiết kế, đã bổ sung:
  - P13 mục 1 yêu cầu chặn "import chéo implementation riêng". import-linter chỉ kiểm cạnh giữa package; một cạnh được phép vẫn mở được `_x` của package kia.
    - Thêm `test_packages_use_only_public_names_of_other_packages`: quét AST mọi import, kể cả trong hàm, và truy cập `module._x` qua module đã import.
    - Thêm `test_private_import_check_catches_controlled_violations`: 6 vi phạm cấy trong cây tạm đều bị bắt; tên công khai, dunder và tên riêng trong cùng package không bị bắt.
    - Một ngoại lệ có lý do (mục "Danh sách alias và ngoại lệ").
  - Cạnh `ocr_document.validation -> benchmark.accuracy_first` chưa được ghi. Đã ghi lý do, và thêm hai hợp đồng `benchmark`/`benchmark-direct` (nay 16 hợp đồng KEPT) cùng hai ca vi phạm có kiểm soát.
  - CI bỏ regression đầy đủ khỏi push/PR: trước P13, `tests/unit tests/scientific` chạy ở mỗi push; bản chia job chỉ còn chạy chúng khi chọn `run_models`.
    - Lượt toàn bộ unit/scientific/legacy_compat với `OCR_MODELS_DIR`/`VIETOCR_MODEL_DIR` rỗng và HF offline: 1182 passed, 1 skipped (`junit-nomodels.xml`), nên regression không cần trọng số tải về. Smoke legacy fast dùng model đóng gói trong `rapidocr-onnxruntime`.
    - Job `legacy` nay cài `.[legacy,test]` và chạy toàn bộ `tests/unit tests/scientific tests/legacy_compat` cùng integration native ở mỗi push/PR, không tải model. `run_models` vẫn là lượt có model kèm integration/golden.
    - `tests/unit/test_ci_workflow.py` hỏng nếu một thư mục regression rời khỏi job mặc định, nếu job mặc định tải model, hoặc nếu job nhẹ cài stack OCR. Test này fail trên bản workflow trước khi sửa.
    - Integration native với model rỗng: 5 passed. Lượt GitHub Actions thực: NOT_RUN.
  - Tài liệu: dời mục Linux của Codex về trước bảng alias, sửa câu "chưa chạy Linux" đã bị mục sau thay thế, và thêm dòng P12/P13 vào nhật ký bằng chứng.
- Không đổi mã nguồn chạy thật trong lượt kiểm này, nên không cần lượt GPU mới. P12 DONE. P13 vẫn IN_PROGRESS, vì GitHub Actions, runner GPU, image Docker đầy đủ hai runtime và Kaggle thật chưa chạy. Chất lượng trên GT: NOT_EVALUATED.

## Danh sách alias và ngoại lệ

Cập nhật ở mỗi giai đoạn.

| Đường dẫn cũ | Trỏ tới | Consumer còn dùng | Điều kiện xoá |
| --- | --- | --- | --- |
| `src.ocr.domain.models.accuracy` | `ocr_contracts.accuracy` | test, legacy | P13, khi không còn consumer |
| `src.ocr.domain.models.confidence` | `ocr_contracts.confidence` | test, legacy | P13, khi không còn consumer |
| `src.ocr.domain.models.diagram` | `ocr_contracts.diagram` | test, legacy | P13, khi không còn consumer |
| `src.ocr.domain.models.document` | `ocr_contracts.document` | test, legacy | P13, khi không còn consumer |
| `src.ocr.domain.models.evidence_block` | `ocr_contracts.evidence_block` | test, legacy | P13, khi không còn consumer |
| `src.ocr.domain.models.formula` | `ocr_contracts.formula` | test, legacy | P13, khi không còn consumer |
| `src.ocr.domain.models.keyword` | `ocr_contracts.keyword` | test, legacy | P13, khi không còn consumer |
| `src.ocr.domain.models.page` | `ocr_contracts.page` | test, legacy | P13, khi không còn consumer |
| `src.ocr.domain.models.processing` | `ocr_contracts.processing` | test, legacy | P13, khi không còn consumer |
| `src.ocr.domain.models.quality` | `ocr_contracts.quality` | test, legacy | P13, khi không còn consumer |
| `src.ocr.domain.models.region` | `ocr_contracts.region` | test, legacy | P13, khi không còn consumer |
| `src.ocr.domain.models.schema` | `ocr_contracts.schema` | test, legacy | P13, khi không còn consumer |
| `src.ocr.domain.models.subpage` | `ocr_contracts.subpage` | test, legacy | P13, khi không còn consumer |
| `src.ocr.domain.models.table` | `ocr_contracts.table` | test, legacy | P13, khi không còn consumer |
| `src.ocr.domain.models.text_block` | `ocr_contracts.text_block` | test, legacy | P13, khi không còn consumer |
| `src.ocr.domain.routing.page_type` | `ocr_contracts.page_type` | test, legacy | P13, khi không còn consumer |
| `src.ocr.runtime.atomic_io` | `ocr_artifacts.atomic_io` | test, legacy | P13, khi không còn consumer |
| `src.ocr.infrastructure.postprocessing.keyword_counter` | `ocr_keywords.counter` | test, legacy, notebook V6.3 | P13, khi không còn consumer |
| `src.ocr.infrastructure.postprocessing.keyword_contract` | `ocr_keywords.contract` | test, legacy, notebook V6.3 | P13, khi không còn consumer |
| `src.ocr.infrastructure.export.keyword_exporter` | `ocr_reporting.document_workbook` | test, notebook V6.3, scripts | P13, khi không còn consumer |
| `src.ocr.infrastructure.export.keyword_v63` | `ocr_reporting.workbooks` | test, notebook V6.3, scripts | P13, khi không còn consumer |
| `src.ocr.infrastructure.postprocessing.numeric_guard` | `ocr_text.numeric_guard` | src.ocr, test, scripts | P13, khi không còn consumer |
| `src.ocr.infrastructure.postprocessing.text_cleaner` | `ocr_text.text_cleaner` | src.ocr, test, scripts | P13, khi không còn consumer |
| `src.ocr.infrastructure.postprocessing.unicode_normalizer` | `ocr_text.unicode_normalizer` | src.ocr, test, scripts | P13, khi không còn consumer |
| `src.ocr.runtime.backend_probe` | `ocr_runtime.backend_probe` | src.ocr, test, scripts | P13, khi không còn consumer |
| `src.ocr.runtime.config` | `ocr_runtime.config` | src.ocr, test, scripts | P13, khi không còn consumer |
| `src.ocr.runtime.dependency_lock` | `ocr_runtime.dependency_lock` | src.ocr, test, scripts | P13, khi không còn consumer |
| `src.ocr.runtime.device` | `ocr_runtime.device` | src.ocr, test, scripts | P13, khi không còn consumer |
| `src.ocr.runtime.fingerprint` | `ocr_runtime.fingerprint` | src.ocr, test, scripts | P13, khi không còn consumer |
| `src.ocr.runtime.models` | `ocr_runtime.models` | src.ocr, test, scripts | P13, khi không còn consumer |
| `src.ocr.runtime.paths` | `ocr_runtime.paths` | src.ocr, test, scripts | P13, khi không còn consumer |
| `src.ocr.runtime.process_tree` | `ocr_runtime.process_tree` | src.ocr, test, scripts | P13, khi không còn consumer |
| `src.ocr.runtime.structured_logging` | `ocr_runtime.structured_logging` | src.ocr, test, scripts | P13, khi không còn consumer |
| `src.ocr.runtime.torch_placement` | `ocr_runtime.torch_placement` | src.ocr, test, scripts | P13, khi không còn consumer |
| `src.ocr.infrastructure.pdf.coordinate_transform` | `ocr_pdf_io.coordinate_transform` | src.ocr, test | P13, khi không còn consumer |
| `src.ocr.infrastructure.pdf.native_text_extractor` | `ocr_pdf_io.native_text_extractor` | src.ocr, test | P13, khi không còn consumer |
| `src.ocr.infrastructure.pdf.pdf_inspector` | `ocr_pdf_io.pdf_inspector` | src.ocr, test | P13, khi không còn consumer |
| `src.ocr.infrastructure.pdf.pdf_renderer` | `ocr_pdf_io.pdf_renderer` | src.ocr, test | P13, khi không còn consumer |
| `src.ocr.infrastructure.pdf.region_cropper` | `ocr_pdf_io.region_cropper` | src.ocr, test | P13, khi không còn consumer |
| `src.ocr.infrastructure.pdf.scan_image` | `ocr_pdf_io.scan_image` | src.ocr, test | P13, khi không còn consumer |
| `src.ocr.application.route_page` | `ocr_recognition.route_page` | src.ocr, test | P13, khi không còn consumer |
| `src.ocr.domain.routing.routing_policy` | `ocr_recognition.routing_policy` | src.ocr, test | P13, khi không còn consumer |
| `src.ocr.infrastructure.layout.dla_engine` | `ocr_layout.dla_engine` | src.ocr, test | P13, khi không còn consumer |
| `src.ocr.infrastructure.layout.model_adapters` | `ocr_layout.model_adapters` | src.ocr, test | P13, khi không còn consumer |
| `src.ocr.infrastructure.layout.page_content_analyzer` | `ocr_layout.page_content_analyzer` | src.ocr, test | P13, khi không còn consumer |
| `src.ocr.infrastructure.layout.torch_layout` | `ocr_layout.torch_layout` | src.ocr, test | P13, khi không còn consumer |
| `src.ocr.infrastructure.ocr.candidate_scorer` | `ocr_recognition.candidate_scorer` | src.ocr, test | P13, khi không còn consumer |
| `src.ocr.infrastructure.ocr.fallback_engine` | `ocr_recognition.fallback_engine` | src.ocr, test | P13, khi không còn consumer |
| `src.ocr.infrastructure.ocr.primary_engine` | `ocr_recognition.primary_engine` | src.ocr, test | P13, khi không còn consumer |
| `src.ocr.infrastructure.ocr.rapidocr_engine` | `ocr_recognition.rapidocr_engine` | src.ocr, test | P13, khi không còn consumer |
| `src.ocr.infrastructure.ocr.text_detector` | `ocr_recognition.text_detector` | src.ocr, test | P13, khi không còn consumer |
| `src.ocr.infrastructure.ocr.vietnamese_seq2seq_engine` | `ocr_recognition.vietnamese_seq2seq_engine` | src.ocr, test | P13, khi không còn consumer |
| `src.ocr.infrastructure.quality.native_quality` | `ocr_recognition.native_quality` | src.ocr, test | P13, khi không còn consumer |
| `src.ocr.infrastructure.quality.ocr_layer_agreement` | `ocr_recognition.ocr_layer_agreement` | src.ocr, test | P13, khi không còn consumer |
| `src.ocr.infrastructure.quality.ocr_quality` | `ocr_recognition.ocr_quality` | src.ocr, test | P13, khi không còn consumer |
| `src.ocr.infrastructure.quality.vietnamese_quality` | `ocr_recognition.vietnamese_quality` | src.ocr, test | P13, khi không còn consumer |
| `src.ocr.infrastructure.layout.diagram_builder` | `ocr_structure.diagram_builder` | src.ocr, test, notebook V6.3 | P13, khi không còn consumer |
| `src.ocr.infrastructure.layout.docling_structure` | `ocr_structure.docling_client` | src.ocr, test, notebook V6.3 | P13, khi không còn consumer |
| `src.ocr.infrastructure.layout.document_layout_engine` | `ocr_structure.document_layout_engine` | src.ocr, test, notebook V6.3 | P13, khi không còn consumer |
| `src.ocr.infrastructure.pdf.ocr_bridge` | `ocr_structure.ocr_bridge` | src.ocr, test, notebook V6.3 | P13, khi không còn consumer |
| `src.ocr.infrastructure.table.hidden_text_layer` | `ocr_structure.hidden_text_layer` | src.ocr, test, notebook V6.3 | P13, khi không còn consumer |
| `src.ocr.application.document_export` | `ocr_document.export` | src.ocr, test, notebook, scripts | P13, khi không còn consumer |
| `src.ocr.application.resolve_document_furniture` | `ocr_document.resolve_document_furniture` | src.ocr, test, notebook, scripts | P13, khi không còn consumer |
| `src.ocr.application.resolve_document_layout` | `ocr_document.resolve_document_layout` | src.ocr, test, notebook, scripts | P13, khi không còn consumer |
| `src.ocr.infrastructure.export.contract_schema` | `ocr_document.contract_schema` | src.ocr, test, notebook, scripts | P13, khi không còn consumer |
| `src.ocr.infrastructure.export.document_contracts` | `ocr_document.document_contracts` | src.ocr, test, notebook, scripts | P13, khi không còn consumer |
| `src.ocr.infrastructure.export.document_validation` | `ocr_document.validation` | src.ocr, test, notebook, scripts | P13, khi không còn consumer |
| `src.ocr.infrastructure.export.json_exporter` | `ocr_document.json_exporter` | src.ocr, test, notebook, scripts | P13, khi không còn consumer |
| `src.ocr.infrastructure.export.manifest_exporter` | `ocr_document.manifest_exporter` | src.ocr, test, notebook, scripts | P13, khi không còn consumer |
| `src.ocr.infrastructure.export.markdown_exporter` | `ocr_document.markdown_exporter` | src.ocr, test, notebook, scripts | P13, khi không còn consumer |
| `src.ocr.infrastructure.export.output_contract` | `ocr_document.output_contract` | src.ocr, test, notebook, scripts | P13, khi không còn consumer |
| `src.ocr.infrastructure.export.result_reader` | `ocr_document.result_reader` | src.ocr, test, notebook, scripts | P13, khi không còn consumer |
| `src.ocr.infrastructure.layout.region_tree` | `ocr_document.region_tree` | src.ocr, test, notebook, scripts | P13, khi không còn consumer |
| `src.ocr.infrastructure.postprocessing.document_furniture` | `ocr_document.document_furniture` | src.ocr, test, notebook, scripts | P13, khi không còn consumer |
| `src.ocr.infrastructure.postprocessing.legacy_furniture` | `ocr_document.legacy_furniture` | src.ocr, test, notebook, scripts | P13, khi không còn consumer |
| `src.ocr.infrastructure.postprocessing.page_association` | `ocr_document.page_association` | src.ocr, test, notebook, scripts | P13, khi không còn consumer |
| `src.ocr.infrastructure.postprocessing.reading_order` | `ocr_document.reading_order` | src.ocr, test, notebook, scripts | P13, khi không còn consumer |
| `src.ocr.infrastructure.postprocessing.reading_order_graph` | `ocr_document.reading_order_graph` | src.ocr, test, notebook, scripts | P13, khi không còn consumer |
| `src.ocr.infrastructure.postprocessing.xy_cut` | `ocr_document.xy_cut` | src.ocr, test, notebook, scripts | P13, khi không còn consumer |
| `src.ocr.infrastructure.structure.figures` | `ocr_document.figures` | src.ocr, test, notebook, scripts | P13, khi không còn consumer |
| `src.ocr.infrastructure.structure.ids` | `ocr_document.ids` | src.ocr, test, notebook, scripts | P13, khi không còn consumer |
| `src.ocr.infrastructure.structure.section_tree` | `ocr_document.section_tree` | src.ocr, test, notebook, scripts | P13, khi không còn consumer |
| `src.ocr.infrastructure.structure.source_identity` | `ocr_document.source_identity` | src.ocr, test, notebook, scripts | P13, khi không còn consumer |
| `src.ocr.infrastructure.table.financial_checks` | `ocr_document.financial_checks` | src.ocr, test, notebook, scripts | P13, khi không còn consumer |
| `src.ocr.application.analysis_run` | `ocr_pipeline.analysis_run` | src.ocr, test, scripts, notebook | P13, khi không còn consumer |
| `src.ocr.application.keyword_finalization` | `ocr_pipeline.keyword_finalization` | src.ocr, test, scripts, notebook | P13, khi không còn consumer |
| `src.ocr.application.process_batch` | `ocr_pipeline.batch` | src.ocr, test, scripts, notebook | P13, khi không còn consumer |
| `src.ocr.application.process_document` | `ocr_pipeline.document` | src.ocr, test, scripts, notebook | P13, khi không còn consumer |
| `src.ocr.application.publish_keyword_matrix` | `ocr_pipeline.publication` | src.ocr, test, scripts, notebook | P13, khi không còn consumer |
| `src.ocr.application.recount_document` | `ocr_pipeline.recount` | src.ocr, test, scripts, notebook | P13, khi không còn consumer |
| `src.ocr.infrastructure.export.artifact_validator` | `ocr_pipeline.artifact_validation` | src.ocr, test, scripts, notebook | P13, khi không còn consumer |
| `src.ocr.infrastructure.export.completion` | `ocr_pipeline.completion` | src.ocr, test, scripts, notebook | P13, khi không còn consumer |
| `src.ocr.infrastructure.export.keyword_validator` | `ocr_pipeline.keyword_validation` | src.ocr, test, scripts, notebook | P13, khi không còn consumer |
| `src.ocr.infrastructure.state.batch_store` | `ocr_pipeline.batch_store` | src.ocr, test, scripts, notebook | P13, khi không còn consumer |
| `src.ocr.runtime.gpu_phase_worker` | `ocr_workers.phases` | src.ocr, test, scripts, notebook | P13, khi không còn consumer |
| `src.ocr.runtime.gpu_scheduler` | `ocr_pipeline.scheduler` | src.ocr, test, scripts, notebook | P13, khi không còn consumer |
| `src.ocr.runtime.v63_backend` | `ocr_pipeline.backend` | src.ocr, test, scripts, notebook | P13, khi không còn consumer |
| `src.ocr.runtime.v63_document_worker` | `ocr_pipeline.document_owner` | src.ocr, test, scripts, notebook | P13, khi không còn consumer |

Danh sách máy đọc được: `docs/architecture/module_map.json` (công cụ `scripts/migration/move_modules.py` ghi; `tests/unit/test_migration_aliases.py` kiểm từng alias là cùng object).

Ngoại lệ import tạm (package mới import `src.ocr`, khoá `temporary_legacy_imports` trong `module_map.json`, cũng là `ignore_imports` của hợp đồng `workers`):

- `ocr_workers.phase_text -> src.ocr.application.process_page` (trước P11b: `ocr_workers.phases`): profile V6.2 legacy (native-first, two-up, fallback vùng) vẫn chạy pha A bằng `ProcessPageUseCase` đóng băng; V6.3 dùng `ocr_workers.text_page` từ P09b. Xoá khi bỏ hỗ trợ V6.2.
- `ocr_workers.phase_export -> src.ocr.application.export_document` (trước P11b: `ocr_workers.phases`): đường V6.2 legacy finalize trong pha export (cũng là ngoại lệ của hợp đồng `extraction`). Xoá khi bỏ hỗ trợ V6.2.

Ngoại lệ tên riêng (P13, khoá `private_import_exceptions` trong `module_map.json`, kiểm bởi `test_packages_use_only_public_names_of_other_packages`): package chỉ dùng tên công khai của package khác. Còn một ngoại lệ:

- `ocr_pipeline.completion` nhập lại `_EXCLUDED`, `_artifact_files`, `_sha256` từ `ocr_artifacts.completion`.
  - Lý do: giữ đủ tập thuộc tính của module legacy đóng băng `src.ocr.infrastructure.export.completion`, vốn là alias của `ocr_pipeline.completion`.
  - Chỉ nhập lại; không nơi nào gọi.
  - Điều kiện xoá: xoá cùng alias đó, hoặc ở lần sửa kế tiếp vốn đã đổi closure extraction (file này thuộc closure đó, nên sửa riêng nó sẽ đổi fingerprint extraction và làm mất bằng chứng GPU của bản mã hiện tại).

Cạnh ngoài bảng phụ thuộc (P13): `ocr_document.validation -> benchmark.accuracy_first`.

- Đây là import trong hàm, chỉ chạy khi truyền manifest GT. Nó được chuyển nguyên từ validator legacy (`src/ocr/infrastructure/export/artifact_validator.py`), không phải cạnh mới.
- `benchmark` là top-level có từ trước trong cùng distribution, không phải dependency tải thêm.
- Hợp đồng `benchmark` cấm các package dưới tầng document chạm tới nó, kể cả gián tiếp. Hợp đồng `benchmark-direct` cấm `ocr_pipeline` và `ocr_workers` tự import nó; hai package này chỉ chạm tới qua validator trên.
- Điều kiện xoá: khi evaluator GT được đưa vào validator từ bên ngoài, hoặc chuyển vào một package mà document được phép dùng.

Ngoại lệ đóng gói (P10): wheel vẫn cài namespace `src` (chỉ chứa `src.ocr`) cho legacy và alias; bỏ khi không còn consumer import `src.ocr`. Top-level `benchmark` có từ trước, giữ cho `ocrpdf-perf`.


## Nhật ký bằng chứng

| Giai đoạn | Bằng chứng |
| --- | --- |
| P00 | `scratch/migration/import_graph_p00.json`, `scratch/migration/junit-baseline.xml`, `scratch/migration/baseline_user_changes.patch` |
| P00b | `tests/unit/test_v63_worker_acceptance.py` (27 test: worker giả qua subprocess thật, chính sách fallback Docling); toàn bộ unit/scientific 850 passed, 1 skipped (`scratch/migration/junit-p00b.xml`); patch `scratch/migration/after-P00b-P01.patch` |
| P13 | Codex: `scratch/codex-development-20261022/` (`verification.json`, `wheel-final/`, `linux-accepted-evidence/`, `light-isolation.json`, `isolated-app-accepted.xml`, `ref-after.xml`, `gpu-final/verification.json`), báo cáo `NGHIEM_THU_KIEN_TRUC_20261022.md`. Kiểm lại của Claude: `scratch/migration/p13-review/` (`junit-full.xml` 1180 passed/1 skipped; `junit-nomodels.xml` 1182 passed/1 skipped với thư mục model rỗng; `junit-ci-import.xml`, `junit-integration-nomodels.xml`, `workflow-check.json`); import-linter 16 KEPT; patch `scratch/migration/after-P13.patch`. NOT_RUN: GitHub Actions, runner GPU, image Docker đầy đủ, Kaggle; GT: NOT_EVALUATED |
| P12 | Claude: `tests/unit/runtime/test_config_and_paths.py`, `tests/unit/test_model_identity.py`; reviewer F06 `scratch/codex-review-20261022/p12-recheck-1911/`, `f06-recheck-1921/`; probe trên bản sao `scratch/migration/review-f06/`, `review-f06b/`; GPU trên mã trước `model_registry` (trung gian): `scratch/migration/v63-baseline/sample-p12.comparison.json`, `sample-p12-cachedir` (cache Unicode/khoảng trắng). Codex: `ref-before.xml`/`ref-after.xml`, `runtime-final.xml`, `full-suite.xml` (1175 passed/1 skipped), `gpu-sample/` và `gpu-final/verification.json` (extraction `2d3e8784a473b552`, khớp mã hiện tại) |
| P11b | toàn bộ unit/scientific/legacy_compat: 1132 passed, 1 skipped (`scratch/migration/junit-p11b.xml`); `tests/unit/test_stage_cache.py` (call counter theo pha, F05), `tests/unit/artifacts/test_atomic_replace.py`; reviewer F05: `scratch/codex-review-20261022/f05-recheck-1851/`; GPU thật lượt mới và `--resume`: `scratch/migration/v63-baseline/*-p11c*.comparison.json`, `p11c-reuse.provenance.json`; patch `scratch/migration/after-P11b.patch`. Lượt `*-p11b*` là bằng chứng trung gian trước F05. NOT_RUN: test symlink venv Linux; độ chính xác theo GT: NOT_EVALUATED |
| P10 | toàn bộ unit/scientific/legacy_compat: 1095 passed, 1 skipped (`scratch/migration/junit-p10.xml`); ma trận cài/import ngoài checkout và probe CWD là dự án khác (F04): `scratch/migration/p10-matrix/matrix.json`; GPU thật trùng P09b: `scratch/migration/v63-baseline/{sample,clw}-p10.comparison.json`, `sample-p10b.comparison.json`; patch `scratch/migration/after-P10.patch`. NOT_RUN: GitHub Actions, Docker, Kaggle, cài thật extra `legacy`/`gpu` từ wheel, test symlink venv Linux |
| P09 | toàn bộ unit/scientific/legacy_compat: 1087 passed, 1 skipped (`scratch/migration/junit-p09b.xml`); reviewer kiểm lại F01–F03: `scratch/codex-review-20261022/recheck-1736/`; GPU thật, orchestrator mới so với cũ trên 80 trang (sample, CLW, PJT, HTL): `scratch/migration/v63-baseline/{sample,clw,pjt,htl}-p09b.comparison.json` (đều `identical: true`), `p09b-receipts.comparison.json`; patch `scratch/migration/after-P09.patch`. NOT_RUN: test symlink venv Linux; độ chính xác theo GT: NOT_EVALUATED |
| P08 | toàn bộ unit/scientific/legacy_compat: 1052 passed, 1 skipped (`scratch/migration/junit-p08.xml`); import-linter 12 KEPT; GPU thật: `scratch/migration/v63-baseline/run-p08.comparison.json`; patch `scratch/migration/after-P08.patch` |
| P07 | toàn bộ unit/scientific/legacy_compat: 1029 passed, 1 skipped (`scratch/migration/junit-p07.xml`); import-linter 11 KEPT; GPU thật: `scratch/migration/v63-baseline/run-p07.comparison.json`; patch `scratch/migration/after-P07.patch` |
| P06 | toàn bộ unit/scientific/legacy_compat: 1023 passed, 1 skipped (`scratch/migration/junit-p06.xml`); import-linter 10 KEPT; GPU thật sau khi chuyển package và sau khi tách bước layout đều khớp baseline (`scratch/migration/v63-baseline/run-p06.comparison.json`, `run-p06b.comparison.json`); patch `scratch/migration/after-P06.patch` |
| P05b | toàn bộ unit/scientific/legacy_compat: 990 passed, 1 skipped (`scratch/migration/junit-p05b.xml`); GPU thật: `scratch/migration/v63-baseline/run-p05b.comparison.json`; patch `scratch/migration/after-P05b.patch` |
| P05a | toàn bộ unit/scientific/legacy_compat: 973 passed, 1 skipped (`scratch/migration/junit-p05a.xml`); import-linter 7 KEPT; lượt GPU thật trên sample khớp baseline P01 (`scratch/migration/v63-baseline/run-p05a.comparison.json`); patch `scratch/migration/after-P05a.patch` |
| P11a | toàn bộ unit/scientific/legacy_compat: 952 passed, 1 skipped (`scratch/migration/junit-p11a.xml`); analysis run trên 5 tài liệu V6.3 thật; lượt GPU thật sau P11a trên `examples/sample.pdf` (`scratch/migration/v63-baseline/run-p11a`): `result.md`, `document.md`, `extraction.json`, `structure.json`, `document.json`, Markdown trang trùng từng byte với P01; page JSON chỉ khác trường biến thiên (thời gian, generation, job/log Docling, fingerprint Docling do file client đổi); placement 4/4 `VERIFIED_INFERENCE`; patch `scratch/migration/after-P11a.patch` |
| P04 | toàn bộ unit/scientific/legacy_compat: 937 passed, 1 skipped (`scratch/migration/junit-p04.xml`); import-linter 5 hợp đồng KEPT; patch `scratch/migration/after-P04.patch` |
| P03 | toàn bộ unit/scientific/legacy_compat: 926 passed, 1 skipped (`scratch/migration/junit-p03.xml`); venv tối thiểu 34 passed; import-linter 3 hợp đồng KEPT; patch `scratch/migration/after-P03.patch` |
| P02 | toàn bộ unit/scientific/legacy_compat: 895 passed, 1 skipped (`scratch/migration/junit-p02.xml`); venv tối thiểu chỉ pydantic + pytest: test `contracts`/`artifacts` 9 passed (`scratch/migration/minimal-env-p02.txt`); import-linter 2 hợp đồng KEPT; patch `scratch/migration/after-P02.patch` |
| P01 | `benchmark/evidence/migration_p01_baseline.json`; lượt V6.3 GPU thật trên `examples/sample.pdf` (`scratch/migration/v63-baseline/run-p01`, placement detector/recognizer/layout/Docling đều `VERIFIED_INFERENCE` trên CUDA); fixture `tests/fixtures/migration/v63_sample` + `test_migration_v63_export_baseline.py` (export chạy lại trùng từng byte với lượt GPU); `test_migration_digest_baseline.py`; `tests/legacy_compat/` (13 passed, gồm một lượt legacy fast thật trên CPU); `scratch/migration/cli_help_p01.txt` |
