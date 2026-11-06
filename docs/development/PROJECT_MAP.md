# Bản đồ tra cứu OCR PDF

Chỉ mục kiểm từ checkout ngày 03/11/2026, không phải bản sao kiến trúc. Khi di chuyển module, cập nhật liên kết. Chọn một hàng phù hợp rồi đọc mã/caller/test; không nạp toàn bảng mã vào hội thoại.

## Nguồn thông tin theo câu hỏi

| Câu hỏi | Nguồn cần mở |
| --- | --- |
| Quy trình phiên và trạng thái công việc | [AGENTS](../../AGENTS.md), [HANDOFF](HANDOFF.md), [quy trình](README.md) |
| Cài đặt, lệnh chạy, output | [README gốc](../../README.md) |
| Thiết kế và invariant | [ARCHITECTURE](../../ARCHITECTURE.md); tìm tiêu đề bằng `rg -n '^##' ARCHITECTURE.md` |
| Cấu hình thực thi | [profiles.yaml](../../config/profiles.yaml); alias không phải backend mới |
| Model/dependency/import | [registry](../../models/v62/runtime-models.json), [locks](../../requirements/v62), [pyproject](../../pyproject.toml) |
| Chuyển tên module cũ | [module_map.json](../../config/module_map.json); dò lại file đích |
| Kết quả lịch sử kiến trúc | [IMPLEMENTATION_REPORT](../../IMPLEMENTATION_REPORT.md), [evidence 23/10](../../benchmark/evidence/unified_architecture_20261023.json) |
| Diagnostic và giới hạn GT | [điểm vào Test case](../../Test%20case/00_DOC_KET_QUA_TRUOC.md); các file ở đây hiện có thể còn chưa được Git theo dõi |
| Điểm yếu đã tổng hợp và việc cải tiến tiếp theo | [Cai Tien](../../Cai%20Tien/README.md), [backlog theo ID](../../Cai%20Tien/03_BACKLOG_CAI_TIEN.csv); đọc evidence đúng mốc trước khi sửa |

Tài liệu có ngày, evidence cũ và baseline chỉ chứng minh phạm vi đã ghi tại mốc tương ứng. Không lấy số test trong báo cáo lịch sử làm kết quả working tree hiện tại. Mã hiện tại cho biết hành vi triển khai; test và artifact xác nhận mệnh đề đã thực sự kiểm.

## Vùng thay đổi và phép kiểm

Các đường dẫn test dưới đây là điểm bắt đầu, không phải chứng nhận đã chạy trong phiên.

| Vấn đề | Module/điểm vào | Kiểm sát phạm vi |
| --- | --- | --- |
| CLI, batch, resume, analysis, công bố | [ocr_pipeline](../../src/ocr_pipeline/README.md) | [pipeline](../../tests/unit/test_v63_pipeline.py), [analysis](../../tests/unit/test_analysis_run.py), [cache](../../tests/unit/test_stage_cache.py) |
| Cấu hình, model, identity, process | [ocr_runtime](../../src/ocr_runtime/README.md) | [runtime](../../tests/unit/runtime), [identity](../../tests/unit/test_model_identity.py) |
| Hợp đồng và provenance | [ocr_contracts](../../src/ocr_contracts/README.md) | [contracts](../../tests/unit/contracts), [import bounds](../../tests/unit/test_import_contracts.py) |
| Hash, ghi nguyên tử, receipt | [ocr_artifacts](../../src/ocr_artifacts/README.md) | [artifacts](../../tests/unit/artifacts), [digest baseline](../../tests/unit/test_migration_digest_baseline.py) |
| Pha worker và cô lập GPU | [ocr_workers](../../src/ocr_workers/README.md) | [protocol](../../tests/unit/test_worker_protocol.py), [acceptance](../../tests/unit/test_v63_worker_acceptance.py) |
| PDF view, render, tọa độ | [ocr_pdf_io](../../src/ocr_pdf_io/README.md) | [PDF IO](../../tests/unit/pdf_io) |
| Detector, crop, chữ, hướng dòng | [ocr_recognition](../../src/ocr_recognition/README.md) | [recognition](../../tests/unit/recognition), [routing](../../tests/unit/test_routing.py) |
| Dấu và bảo toàn số | [ocr_text](../../src/ocr_text/README.md) | [text](../../tests/unit/text), [numeric guard](../../tests/unit/test_v6_numeric_guard.py) |
| Layout vùng và Docling bridge | [ocr_layout](../../src/ocr_layout/README.md), [ocr_structure](../../src/ocr_structure/README.md) | [layout adapters](../../tests/unit/test_v6_layout_adapters.py), [structure](../../tests/unit/structure) |
| Ghép bảng/trang, reading order, review, export | [ocr_document](../../src/ocr_document/README.md) | [document](../../tests/unit/document), [export baseline](../../tests/unit/test_migration_v63_export_baseline.py) |
| L5 bảng qua trang | [Tiếp nhận A/B/C](../../benchmark/ground_truth_tools/TABLE_BOUNDARY_INTAKE_V7.md), [ghép thử](../../src/ocr_document/TABLE_STITCH_V7.md) | [Phiếu L5](../../tests/scientific/test_table_boundary_annotations.py), [phép chiếu bảng](../../tests/unit/document/test_table_stitch.py) |
| Đếm literal, Excel, ma trận | [ocr_keywords](../../src/ocr_keywords/README.md), [ocr_reporting](../../src/ocr_reporting/README.md) | [keywords](../../tests/unit/keywords), [reporting](../../tests/unit/reporting), [counter](../../tests/unit/test_keyword_counter.py) |
| Chỉ số và độ chính xác khoa học | [evaluator](../../benchmark/scientific_evaluation), [GT guideline](../../benchmark/ground_truth_tools/ANNOTATION_V6.md), [detector pha A](../../benchmark/scientific_evaluation/TEXT_DETECTION_V7.md), [trích dẫn xen cột](../../benchmark/scientific_evaluation/CALLOUT_V7.md) | [scientific](../../tests/scientific); cần GT thật cho nghiệm thu chất lượng |
| Công thức | [Nhãn A/B/C](../../benchmark/ground_truth_tools/FORMULA_ANNOTATION_V7.md), [căn theo nguồn](../../benchmark/scientific_evaluation/FORMULA_ALIGNMENT_V7.md), [CDM CPU](../../benchmark/scientific_evaluation/FORMULA_CDM_V7.md), [TEXT và critical](../../benchmark/scientific_evaluation/FORMULA_CONTENT_V7.md), [scorecard](../../benchmark/scientific_evaluation/FORMULA_SCORECARD_V7.md) | [Nhãn](../../tests/scientific/test_formula_annotations.py), [căn vị trí](../../tests/scientific/test_formula_alignment.py), [nội dung](../../tests/scientific/test_formula_content.py), [scorecard](../../tests/scientific/test_formula_scorecard.py) |
| Dấu OCR/native 99,99% | [Gate](../../benchmark/scientific_evaluation/NATIVE_DIACRITIC_RELEASE_V7.md) | [PDF/CI](../../tests/scientific/test_native_diacritic_replay.py) |
| Đo holdout công thức | [Chính sách](../../benchmark/scientific_evaluation/FORMULA_ACCEPTANCE_POLICY_V7.md), [Hồ sơ A/B/C](../../benchmark/ground_truth_tools/FORMULA_HOLDOUT_V7.md), [Replay](../../benchmark/scientific_evaluation/FORMULA_HOLDOUT_REPLAY_V7.md), [Họ kiểm định chung](../../benchmark/scientific_evaluation/FORMULA_FAMILY_V7.md) | [Preflight/replay](../../tests/scientific/test_protocol_preflight.py), [Count công thức](../../tests/scientific/test_formula_counts.py), [Nhãn](../../tests/scientific/test_formula_annotations.py) |
| Mẫu drift BK-08 | [Khung và phiếu A/B](../../benchmark/scientific_evaluation/DRIFT_SAMPLING_V7.md) | [Lấy mẫu](../../tests/scientific/test_drift_sampling.py), [gate](../../tests/scientific/test_release_gate.py) |
| Đối chuẩn OmniDocBench BK-07 | [Plan và xuất paired](../../benchmark/scientific_evaluation/OMNIDOCBENCH_V7.md) | [Ảnh/PDF, Markdown và config](../../tests/scientific/test_omnidocbench_adapter.py) |
| Công cụ ngữ cảnh phiên | [build_dev_context.py](../../scripts/build_dev_context.py) | [test công cụ](../../tests/unit/test_build_dev_context.py) |

## Chạy kiểm tra

Thay đường dẫn test trong lệnh bằng phạm vi vừa sửa:

```powershell
.\.venv\Scripts\python.exe scripts/run_pytest_scratch.py `
  tests/unit/test_build_dev_context.py -q --capture=fd --tb=short
```

Runner lưu `run.json`, `logs/pytest.log`, `evidence/junit.xml` dưới `scratch/runs/<run_id>/` và trả exit code pytest. Không dùng một log cũ cho nhiều lượt sửa. Kiểm phần mềm, smoke GPU, audit artifact và đánh giá GT là các phạm vi khác nhau; chọn theo mệnh đề cần kiểm.
