# Nghiệm thu kiến trúc module — 22/10/2026

Phạm vi: tiếp tục bản migration của Claude, hoàn thiện khóa model P12 và triển khai CI/tài liệu P13. Đây là báo cáo kiểm thử của bên triển khai. Claude kiểm lại ngày 23/10/2026 (mục cuối); Antigravity chưa có báo cáo. Không phát hành, commit hoặc push.

## Kết luận theo lớp bằng chứng

| Lớp | Trạng thái | Bằng chứng |
| --- | --- | --- |
| Mã P12, F06 model selection/content/ref | Đã kiểm Windows và hợp đồng CPU Linux | `ref-after.xml` (65 PASS, 1 SKIP), `runtime-final.xml` (52 PASS), `linux-accepted-evidence/linux-cpu.xml` |
| Hồi quy unit/scientific/legacy trước siết ref cuối | 1175 PASS, 1 SKIP Linux | `full-suite.xml`, `full-suite.log` (492 giây) |
| Phần fixture/worker/import đổi sau lượt đầy đủ | 78 PASS | `final-delta.xml`; chỉ đổi tổ chức fixture test, không đổi runtime |
| Package nhẹ, dependency tối thiểu | 39 PASS core, 9 PASS reporting, 3 PASS text | `light-isolation.json`, `light-*.xml` |
| Wheel cuối cài thật ngoài checkout | PASS cả core/reporting/app trên Windows và Linux | `wheel-final/verification.json`, `linux-accepted-evidence/linux-wheel.json`; 301 file/slot khớp wheel, CWD khác, `python -I -B` |
| CPU/contract trên app không stack OCR | 200 PASS, 1 SKIP Linux, 2 ca Torch chuyển job legacy | `isolated-app-accepted.xml` và log tương ứng |
| Inference GPU mới | PASS trên sample 1 trang, runtime đã khóa | `gpu-final/verification.json`; detector, recognizer, layout, Docling đều VERIFIED_INFERENCE |
| Batch resume và stage resume | PASS | Batch không extraction mới; output mới dùng lại A/B, chỉ export chạy |
| Hồi quy artifact/count | PASS | 6 artifact ổn định khớp byte baseline P11b sau F05; vector keyword khớp |
| Chất lượng trên GT người gán | NOT_EVALUATED | Chưa có GT độc lập; validation giữ NEEDS_REVIEW |
| Linux CPU/container | 247 PASS, 2 SKIP worker chưa cài, 2 ca Torch không thuộc CPU app | `linux-accepted-evidence/linux-verification.json`; symlink venv thực và timeout/orphan cleanup PASS, không Torch/model, network=none |
| Integration native/keyword | 5 PASS | `integration.xml`; PDF tạo trong scratch, không phải GPU hay GT |
| GitHub Actions / image lab Docker đầy đủ / Kaggle thực | NOT_RUN | Workflow và notebook được kiểm cục bộ; chưa có lượt target này |

Không cộng các nhóm test chồng lặp thành tổng pass mới. Cảnh báo `pkg_resources` của gdown là dependency cũ, không phải lỗi kiểm thử. Các cảnh báo regression trong log của test scientific là fixture kiểm bộ phát hiện hồi quy, không phải đo chất lượng OCR trên GT thật.

## Những gì đã thay đổi

- Giữ bản sửa snapshot `model_env`/`model_selection` của Claude và kiểm lại các ca đổi đường dẫn/file sau snapshot.
- Thêm `ocr_runtime.model_registry`: registry phải pin detector và mọi file ở các snapshot layout/table/formula thực sự được chọn. Config processor/tokenizer có trên đĩa nhưng thiếu registry bị từ chối trước model import; file mới thêm sau snapshot cũng bị phát hiện. Backend, runtime verifier và phase worker cùng dùng cổng này.
- Khóa tất cả cache alias Hugging Face/Transformers ở Docling client vào model store được chọn, bỏ `DOCLING_ARTIFACTS_PATH` thừa kế, giữ offline policy. Chẩn đoán dùng cùng resolver với engine, hiển thị `selected_files` và hash đúng kho ngoài checkout.
- Sửa fixture symlink venv để mô tả registry/model giả hợp lệ; giữ nguyên yêu cầu không resolve executable của venv về base Python. Tách `document_test_helpers.py` khỏi module test DLA, tránh kéo NumPy/Torch vào test pipeline/analysis.
- Siết import-linter theo ma trận dependency thực: probe trong cây tạm chứng minh 117 cạnh cấm và 52 cạnh cho phép, đường vòng gián tiếp, thư viện ngoài bị cấm và đúng hai ngoại lệ legacy.
- CI có các job package nhẹ theo dependency trực tiếp, CPU document/pipeline, protocol/cache/subprocess, wheel, legacy/inprocess và model/GPU opt-in. Hai test forward Torch chạy trong job có Torch, không bị bỏ khỏi phủ kiểm thử.
- Thêm `scripts/ci/check_wheel.py` và `check_gpu_sample.py`: work/output/cache mới, không dọn dữ liệu cũ; GPU lease vẫn dùng chung máy. Wheel helper có chế độ offline bằng wheelhouse hoặc uv cache.
- Cập nhật README gốc, README từng package, tài liệu cấu hình và hướng dẫn phát triển module. Alias vẫn là cùng object module; bảng cũ → mới và điều kiện bỏ alias ở `module_map.json`/`MIGRATION_PLAN.md` được giữ.

## Các ranh giới đã chứng minh

### Package và dependency thực tế

Kiểm kê AST mã hiện tại: `scratch/codex-development-20261022/module-dependencies.json` (hash từng file, import trực tiếp ở mọi mức). Bảng sau tóm tắt thư viện ngoài; dependency nội bộ thực tế có trong JSON, dependency được phép có trong thiết kế/import-linter. Không suy thư viện đã được import ở supervisor từ việc nó có mặt trong một hàm worker.

| Package | Số file Python | Thư viện ngoài được dùng |
| --- | --- | --- |
| `ocr_contracts` | 19 | pydantic |
| `ocr_artifacts` | 5 | Chỉ stdlib |
| `ocr_text` | 4 | Chỉ stdlib |
| `ocr_keywords` | 4 | Chỉ stdlib + contracts/artifacts |
| `ocr_reporting` | 4 | openpyxl |
| `ocr_runtime` | 15 | PyYAML, psutil; Torch trong hàm audit/probe |
| `ocr_pdf_io` | 7 | PyMuPDF, NumPy, OpenCV |
| `ocr_recognition` | 17 | Pillow, OpenCV, NumPy, ONNX Runtime, RapidOCR (legacy), Torch, VietOCR, PyYAML |
| `ocr_layout` | 6 | OpenCV, NumPy, ONNX Runtime, PyMuPDF; Torch/Transformers trong hàm |
| `ocr_structure` | 7 | psutil, PyMuPDF; không import Docling |
| `ocr_document` | 25 | pydantic, PyMuPDF; evaluator `benchmark.accuracy_first` chỉ khi truyền GT manifest |
| `ocr_pipeline` | 15 | psutil, pydantic, PyMuPDF; dependency bắc cầu app gồm PyYAML/openpyxl |
| `ocr_workers` | 9 | Pillow, OpenCV, NumPy, PyMuPDF, pypdfium2, Torch hoặc Docling/docling-core theo runtime |

`benchmark` là package đánh giá có sẵn trong cùng distribution, không phải dependency tải thêm. Nhánh GT trong validator không chạy khi thiếu manifest; các số liệu chất lượng của dự án vẫn `NOT_EVALUATED`. Namespace legacy `src.ocr` và các alias tiếp tục được đóng gói, có smoke/alias tests riêng.

Một distribution `ocr-pdf`; contracts/artifacts/keywords chỉ cần pydantic, text chỉ thư viện chuẩn, reporting thêm openpyxl; CPU app không cần stack OCR. Hai worker GPU vẫn ở runtime riêng, không cài lại môi trường. Source extraction/analysis/publication tách fingerprint; mã runtime đang kiểm khớp fingerprint inference mới: extraction `2d3e8784a473b552`, analysis `ce808ef92e712dc4`, publication `76b4cc9a380b8f99`.

Wheel mới: SHA-256 `1c98038ace13a31a5a3b954bb14eb7b14a6ceb9f64576119c709b47f95955f3d`. Mỗi slot kiểm dependency, resource mặc định và override dictionary, import/CLI, toàn bộ file cài từ wheel; không dùng copy tree để thay cho cài wheel thật.

Các giai đoạn trước P12 giữ bằng chứng lịch sử theo phiên bản trong `MIGRATION_PLAN.md`. Không gắn kết quả inference cũ thành kết quả do mã mới chạy. Không sửa output, receipt hoặc hash của extraction/batch cũ để làm resume qua cổng kiểm.

## Phần còn lại

### Thay đổi hành vi và tương thích

- P00b: chỉ nhận kết quả worker sau khi kiểm đúng request/attempt/output/identity, receipt/artifact và cây process đã thoát. Exit khác 0 chưa phân loại bị từ chối. Fallback Docling theo chính sách D3 vẫn cho `NEEDS_REVIEW`, không tự nhận thành công GPU/độ chính xác.
- P11a: đổi keyword/Excel không OCR lại; analysis tạo batch mới trên extraction đã kiểm. Nguồn thiếu file giữ hàng `FAILED_DOCUMENT`, counts `null`. Alias cũ là cùng object module với API mới, không nhân đôi logic.
- P11b: tái dùng stage qua key, receipt upstream và `exited.json`; tồn tại file đơn thuần không đủ. Thời gian của stage tái dùng là lịch sử. Batch vẫn khóa code/runtime/model; thay bản mã dùng output mới hoặc giữ nguyên snapshot gốc.
- P12/P13: từ chối model registry thiếu input thực tế, repo/ref không trùng loader, model đổi hoặc lựa chọn env dịch sau snapshot. Docling không dùng cache/artifacts tùy ý thừa kế. Đây là siết hợp đồng nhận dạng có chủ đích; không nâng model hay thuật toán. Đường dẫn tuyệt đối interpreter/checkout vẫn thuộc identity như thiết kế, không đổi sang nhận dạng nội dung để tăng cache hit.

P12 và mã triển khai P13 đã được kiểm cục bộ trên Windows/Linux, gồm wheel và symlink/process cleanup thực. P13 vẫn giữ IN_PROGRESS ở mức nghiệm thu môi trường target: GitHub Actions, image lab Docker đầy đủ hai runtime và phiên Kaggle thực chưa chạy. Container CPU đã kiểm không thay cho các target đó. Không push để kích CI hoặc dựng kho cloud; GT người gán chưa có nên chất lượng vẫn NOT_EVALUATED.

Đã chuyển đề nghị phản biện chỉ đọc sang Antigravity qua CLI ở workspace OCR_pdf, yêu cầu báo cáo `scratch/codex-development-20261022/ANTI_REVIEW.md`. Chỉ coi đã được phản biện khi báo cáo thực xuất hiện; hiện chưa dùng góp ý bên ngoài làm bằng chứng nghiệm thu.

Chi tiết phát triển module, thay schema/lock, cache/fingerprint, fixture, consumer và batch đã có: [HUONG_DAN_PHAT_TRIEN_MODULE.md](HUONG_DAN_PHAT_TRIEN_MODULE.md). Chính sách sao lưu/restoration SQLite và dữ liệu: [CAU_HINH_VA_DU_LIEU.md](CAU_HINH_VA_DU_LIEU.md).

## Đối chiếu từng yêu cầu P13

| Yêu cầu | Kết quả và bằng chứng |
| --- | --- |
| 1. Import boundaries, ngoại lệ, vi phạm có kiểm soát | PASS: 117 cạnh cấm/52 cạnh cho phép; hai ngoại lệ V6.2 có lý do/điều kiện gỡ trong module_map và MIGRATION_PLAN; 9 test import. Claude bổ sung ngày 23/10: kiểm import chéo tên/module riêng (`_x`), vốn chưa có (1 ngoại lệ có lý do, 6 vi phạm cấy bị bắt); ghi cạnh `ocr_document.validation -> benchmark` và chặn nó ở tầng dưới (16 hợp đồng KEPT) |
| 2. Chia job theo dependency | Đã triển khai 8 job; CPU kiểm toàn bộ runtime, legacy chạy integration native; model/GPU opt-in riêng. YAML và Python nhúng được parse; Actions thực NOT_RUN. Claude sửa ngày 23/10: bản này bỏ regression đầy đủ khỏi push/PR (trước P13 nó chạy ở mỗi push); job legacy nay chạy lại toàn bộ unit/scientific/legacy_compat mà không tải model (đã kiểm với thư mục model rỗng: 1182 PASS, 1 SKIP); `test_ci_workflow.py` chặn hồi quy này |
| 3. Không nhận thiếu GPU là pass; Windows/Linux | PASS cục bộ: Windows GPU thật; Linux CPU không Torch/model, symlink venv và cây process thực. Job GPU khai báo runner/activation, không đổi SKIP thành PASS |
| 4. Baseline, số/nguồn/tọa độ/artifact/publication | PASS: hồi quy fixture/scientific; GPU cuối so 6 artifact gồm document JSON và keyword vector; recovery ledger/workbook và FAILED_DOCUMENT trong suite CPU |
| 5. Setup/resources/Kaggle | PASS kiểm cục bộ: Linux bash syntax/help, setup/preflight CLI import; wheel 3 slot trên hai OS; notebook orchestration tests Windows. Cài image lab đầy đủ và chạy Kaggle target NOT_RUN |
| 6. Hướng dẫn module | 13 README package và HUONG_DAN_PHAT_TRIEN_MODULE: dependency, test, fixture, adapter/schema, lock, benchmark, fingerprint/cache |
| 7. API cũ → mới, alias | module_map/MIGRATION_PLAN có danh sách và điều kiện bỏ; alias tests và legacy smoke đã kiểm; không bỏ consumer còn dùng |
| 8. Batch hiện hữu/receipt/analysis | Hướng dẫn P12/P13; analysis kiểm extraction/receipt, thiếu tài liệu giữ FAILED_DOCUMENT counts=null; không sửa ledger/output cũ để resume |

### Siết model ref sau lượt kiểm đầu

Năm ca âm trước sửa đều FAIL đúng lỗi không từ chối (`ref-before.xml`). Loader Docling 2.137.0 dùng repo và nhánh cố định; metadata registry khác repo hoặc ref không được pin có thể chọn model ngoài tập khóa. Cổng chung nay kiểm repo thực, bắt buộc pin refs và đối chiếu nội dung ref với revision. Năm ca mới cùng hồi quy liên quan PASS (`ref-after.xml`); GPU và wheel cuối được chạy lại trên bản mã này, không lấy lượt GPU cũ để chứng nhận bản mới. Không thay trọng số/registry thật.

Lượt tải pip Linux ban đầu bị dừng và một download host bị kiểm hash từ chối; không nới hash lock. Wheelhouse HTTP/1 sau đó kiểm SHA-256 theo lock, container cuối cài offline với network=none. Chỉ dùng container-final.log/JUnit cuối làm kết quả; log lượt trung gian được giữ để truy vết.

Lượt `linux-local-evidence` có 3 FAIL: hai ca do bản sao harness thiếu `module_map.json`/registry metadata, một ca do assert PID ngay trước lúc Linux thu hồi zombie. Bản sao cuối có đầy đủ metadata; helper test chỉ chờ tối đa 5 giây và vẫn bắt buộc PID biến mất, không tự kill hay bỏ kiểm cleanup. Nhóm process/worker trên Windows đạt 40 PASS (`process-final.xml`); suite Linux cuối gồm các ca đó đạt 247 PASS, 2 SKIP. Chỉ `linux-accepted-evidence` là bằng chứng Linux được chốt. Hai lượt bind Windows trước bị dừng do tải/chạy chậm, không được tính là pass.

## Kiểm lại độc lập — Claude 23/10/2026

Đối chiếu bản này với mục P12, P13, "Quy tắc phụ thuộc" và "Bảng kiểm chung" của [thiết kế](PROMPTS_TAI_CAU_TRUC_MODULE_OCR_PDF.md). Evidence của Codex không bị sửa. Lượt chạy mới nằm ở `scratch/migration/p13-review/`.

| Kiểm | Kết quả | Bằng chứng |
| --- | --- | --- |
| Toàn bộ unit/scientific/legacy_compat, mã hiện tại | 1180 PASS, 1 SKIP (symlink venv chỉ Linux) | `junit-full.xml` |
| Cùng bộ đó với `OCR_MODELS_DIR`/`VIETOCR_MODEL_DIR` rỗng, HF offline | 1182 PASS, 1 SKIP: regression không cần trọng số tải về | `junit-nomodels.xml` |
| Fingerprint mã hiện tại so với lượt GPU cuối | Trùng: extraction `2d3e8784a473b552`, analysis `ce808ef92e712dc4`, publication `76b4cc9a380b8f99`. Sửa của Claude chỉ chạm test, `pyproject.toml` và tài liệu | lệnh `code_fingerprints()` |
| So output GPU của Codex với `sample-p11c` | Lượt mới và stage-resume trùng: artifact ổn định, page JSON và page JSON pha A từng trường | `compare_runs.py` trên `gpu-final/output*` |
| Registry thật qua `validate_registry` | Đạt, 34 file | lệnh trực tiếp |
| Notebook Kaggle so với cổng registry mới | Khớp: tải snapshot đầy đủ theo revision đã ghim, ghi `refs/*`. Chạy Kaggle thật: NOT_RUN | đọc cell 10 |

Thiếu so với thiết kế, đã sửa:

1. **Import chéo implementation riêng** (P13 mục 1) chưa được kiểm. import-linter chỉ kiểm cạnh giữa package.
   - `test_packages_use_only_public_names_of_other_packages` quét import, kể cả trong hàm, và truy cập `module._x`.
   - 6 vi phạm cấy có kiểm soát đều bị bắt.
   - Ngoại lệ duy nhất có lý do nằm ở `module_map.json` (`private_import_exceptions`) và MIGRATION_PLAN. Đó là `ocr_pipeline.completion`, giữ tên của module legacy mà nó là alias.
2. **Cạnh `ocr_document.validation -> benchmark.accuracy_first`** chưa được ghi. Đây là import trong hàm, chỉ chạy khi truyền GT, chuyển nguyên từ validator legacy.
   - Đã ghi lý do.
   - Thêm hợp đồng `benchmark` (tầng dưới document, kể cả gián tiếp) và `benchmark-direct` (pipeline/workers). Nay 16 hợp đồng KEPT, có ca vi phạm cấy cho cả hai.
3. **CI bỏ regression đầy đủ khỏi push/PR.** Trước P13, `tests/unit` và `tests/scientific` chạy ở mỗi push. Bản chia job chỉ còn chạy chúng khi chọn `run_models`.
   - Job legacy nay chạy toàn bộ unit/scientific/legacy_compat cùng integration native, không tải model.
   - `tests/unit/test_ci_workflow.py` hỏng nếu một thư mục regression rời khỏi job mặc định, hoặc nếu job mặc định tải model; test này fail trên bản trước khi sửa.
   - Lượt GitHub Actions thực: NOT_RUN.
4. MIGRATION_PLAN: câu "chưa chạy Linux" đã bị mục sau thay thế; mục Linux nằm sau nhật ký bằng chứng; nhật ký thiếu dòng P12/P13. Đã sửa.

Trạng thái sau kiểm lại: P12 DONE. P13 mã/CI/tài liệu hoàn thiện cục bộ, vẫn IN_PROGRESS. Còn NOT_RUN: GitHub Actions trên hai hệ điều hành, runner GPU `ocr-pdf-gpu`, image Docker đầy đủ hai runtime và phiên Kaggle thật. Chất lượng trên GT: NOT_EVALUATED.
