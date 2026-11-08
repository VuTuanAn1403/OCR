# Kiến trúc hiện tại và phạm vi audit QA

Audit ngày 07/11/2026, Asia/Bangkok. HEAD `4852f53837d235ea8ffcb100d322882c07e294ea`, working tree có thay đổi chưa commit. [Snapshot đầu](../../scratch/dev_sessions/20261107-qa-repository-audit/start.json), [kiểm cuối](../../scratch/dev_sessions/20261107-qa-repository-audit/verification.json). Báo cáo là quan sát checkout; thiết kế chuẩn vẫn ở [ARCHITECTURE](../../ARCHITECTURE.md). Không tạo một pipeline hoặc kiến trúc sản phẩm thứ hai.

Cập nhật sau audit: đã thêm [QA Registry offline v1](../../benchmark/qa/README.md), nằm ngoài pipeline sản phẩm. Các quan sát audit bên dưới giữ mốc riêng; trạng thái triển khai mới ở [roadmap](IMPLEMENTATION_ROADMAP.md).

Đây là điểm vào của sáu đầu ra được yêu cầu:

1. Bản này: pipeline/caller, cơ chế hiện có và bằng chứng.
2. [ERROR_TAXONOMY](ERROR_TAXONOMY.md): họ lỗi, hồ sơ truy vết và tiêu chuẩn xác minh nguyên nhân.
3. [QUALITY_GAP_ANALYSIS](QUALITY_GAP_ANALYSIS.md): khoảng trống có phân loại và giới hạn kết luận.
4. [GROUND_TRUTH_PROTOCOL](GROUND_TRUTH_PROTOCOL.md): phương pháp dự thảo tương thích công cụ hiện hữu; chưa khóa dữ liệu thật.
5. [BENCHMARK_PLAN](BENCHMARK_PLAN.md): phép đo, mẫu số, paired fix/harm, regression và cách báo cáo.
6. [IMPLEMENTATION_ROADMAP](IMPLEMENTATION_ROADMAP.md): QA-01–09, ưu tiên và điều kiện hoàn tất từng phase.

## Phạm vi và cách lấy bằng chứng

Đã đọc thiết kế chuẩn, quy ước [AGENTS](../../AGENTS.md), [quy trình phát triển](../development/README.md), khai báo import trong [pyproject](../../pyproject.toml) và tra mã/caller/test liên quan. Không nạp toàn bộ corpus, model, JSON hoặc lịch sử output. [Bản đối chiếu trước](../../cai%20tien%20v2/09_LUU_TRU_CAI_TIEN_V7.md#ct-15) là đầu mối; 12 focus của phiên đó được đối chiếu lại, không dùng riêng HEAD để suy mọi byte giống nhau.

`VERIFIED` trong audit chỉ có nghĩa theo mệnh đề đã kiểm. Có hàm/test không phải accuracy; có record review không chứng minh review bắt đủ lỗi. “Chưa tìm thấy” chỉ áp dụng vùng source/benchmark/scripts/config đã tra, không chứng minh toàn bộ dự án không thể có công cụ bên ngoài.

## Pipeline sản phẩm và quyền sở hữu

- [`ocr_pipeline.cli.main`](../../src/ocr_pipeline/cli.py) phân biệt OCR, CPU analysis, recount, review packet và table-stitch preview. Nhánh OCR gọi [`prepare_backend`](../../src/ocr_pipeline/backend.py), khóa runtime, rồi [`process_batch`](../../src/ocr_pipeline/batch.py). Các nhánh CPU vẫn kiểm nguồn theo hợp đồng tương ứng.
- [`config/profiles.yaml`](../../config/profiles.yaml) và [`validate_profile`](../../src/ocr_runtime/pipeline_policy.py) yêu cầu CUDA, mọi trang, `native_first=false`, VietOCR, layout cấp tài liệu và Docling cấu trúc. Không có lựa chọn native-first/CPU OCR bằng CLI chuẩn. Tên cấu hình theo phiên bản là alias.
- [`document_owner.main`](../../src/ocr_pipeline/document_owner.py) sở hữu một tài liệu; [`process_document`](../../src/ocr_pipeline/document.py) gọi [`scheduler.run_document`](../../src/ocr_pipeline/scheduler.py), xác minh OCR và hoàn tất keyword sau các pha. Scheduler ràng buộc identity/cache với nguồn, config, model/lock/interpreter, upstream receipt, code và process-tree exit.
- Pha A [`run_text`](../../src/ocr_workers/phase_text.py) dùng [`TextPageExtractor`](../../src/ocr_workers/text_page.py): inspect, phân loại, render toàn trang, detector/recognizer/layout GPU, lưu raw/evidence và retry có giới hạn. Phân loại không bỏ bước OCR.
- Pha B [`run_structure`](../../src/ocr_workers/phase_structure.py) dùng [`ocr_bridge`](../../src/ocr_structure/ocr_bridge.py) và Docling tắt OCR. Bridge giữ visible cùng frozen OCR sources, cấm chữ native. Fallback cấu trúc phải giữ chữ pha A và review; không giả nhãn model cho bảng heuristic.
- [`run_export`](../../src/ocr_workers/phase_export.py) gọi [`DocumentExporter.execute`](../../src/ocr_document/export.py) trên CPU; giải layout/furniture, nguồn/ownership, bảng logic và các artifact xuất. [`resolve_document_layout`](../../src/ocr_document/resolve_document_layout.py) chứa đối soát occurrence/glyph/token; [`build_auto_stitches`](../../src/ocr_document/auto_table_stitch.py) đã có và profile bật `auto_v1`, vẫn cần review.
- Keyword thuộc document owner. [`keyword_finalization`](../../src/ocr_pipeline/keyword_finalization.py), [`alias_finalization`](../../src/ocr_pipeline/alias_finalization.py), [`publication`](../../src/ocr_pipeline/publication.py) và [`batch_store`](../../src/ocr_pipeline/batch_store.py) giữ một chuỗi finalization, SQLite prepare, ghi/đọc kiểm workbook, acknowledge rồi mới chuyển PDF. Literal và alias là các tầng riêng.

Supervisor Windows dùng `.venv/Scripts/python.exe`; hai worker model dùng môi trường text/Docling và lock riêng. QA offline có thể đọc các artifact đã xác minh trên CPU. Production không được import `benchmark`; các adapter QA tương lai phải nằm ngoài engine và không làm worker phụ thuộc keyword/reporting. Quy tắc nằm trong pyproject và [test import contracts](../../tests/unit/test_import_contracts.py).

## Các cơ chế QA đã tồn tại

- **PDF và tọa độ:** [`PDFInspector`](../../src/ocr_pdf_io/pdf_inspector.py), [`RoutingPolicy`](../../src/ocr_recognition/routing_policy.py), coordinate chain/crop và processing view. [`ocr_layer_agreement`](../../src/ocr_recognition/ocr_layer_agreement.py) đo bất đồng giữa hai prediction, không phải GT và chưa có ngưỡng tái dùng layer.
- **Ảnh/chữ:** [`diacritic_retry`](../../src/ocr_recognition/diacritic_retry.py), [`fallback_engine`](../../src/ocr_recognition/fallback_engine.py) có crop DPI cao/CLAHE; token ngắn và hướng dòng có provenance. [`numeric_guard`](../../src/ocr_text/numeric_guard.py) bảo toàn fragment khi sửa, không bảo đảm OCR số ban đầu đúng. [`text_detection_metric`](../../benchmark/scientific_evaluation/text_detection_metric.py) dùng snapshot detector trước retry, giữ cả vùng không nhận dạng được chữ.
- **Layout/bảng:** [`structured_scoreboard.evaluate_structure`](../../benchmark/scientific_evaluation/structured_scoreboard.py) chấm bảng, số theo ô, reading order và layout theo phạm vi GT; [`validation`](../../src/ocr_document/validation.py) kiểm hợp đồng artifact. Hai nhiệm vụ này có ý nghĩa khác nhau.
- **GT và phân tập:** [`src.ocr.collect.catalog`](../../src/ocr/collect/catalog.py) có inventory `sources-v2`, khóa/kiểm `splits-v2`, tạo pilot drafts. [`human_annotations`](../../benchmark/ground_truth_tools/human_annotations.py), nhãn bảng/công thức và [hướng dẫn](../../benchmark/ground_truth_tools/ANNOTATION_V6.md) đã có quy trình nguồn/phiếu/niêm phong/phân xử. Phiếu development không được biến thành holdout.
- **Protocol và scorecard:** [`protocol_preflight`](../../benchmark/scientific_evaluation/protocol_preflight.py), [`scorecard_counts`](../../benchmark/scientific_evaluation/scorecard_counts.py), [`stratified_scorecard`](../../benchmark/scientific_evaluation/stratified_scorecard.py) và [`release_gate`](../../benchmark/scientific_evaluation/release_gate.py) đã kiểm input hash, scope, GT, ngưỡng, thống kê và điều kiện release. Preflight sẵn sàng input vẫn không phải nghiệm thu chất lượng.
- **Metric chữ/số/bảng/order:** có [`ocr_metric`](../../benchmark/scientific_evaluation/ocr_metric.py), [`evaluation_protocol`](../../benchmark/scientific_evaluation/evaluation_protocol.py), [`numeric_metric`](../../benchmark/scientific_evaluation/numeric_metric.py), [`teds_metric`](../../benchmark/scientific_evaluation/teds_metric.py), reading order và bộ công thức. Không cần viết lại CER/WER hoặc TEDS.
- **Keyword/review/fix-harm:** [`keyword_acceptance`](../../benchmark/scientific_evaluation/keyword_acceptance.py) đối chiếu occurrence; [`run_review`](../../src/ocr_pipeline/review_packet.py) tạo packet/crop/template; [`review_calibration`](../../benchmark/scientific_evaluation/review_calibration.py) có routing/reliability/thời gian và paired fixed/introduced. [`retry_effects`](../../benchmark/scientific_evaluation/retry_effects.py) có fix/harm nhưng chỉ diagnostic target phrase trên nhãn AI sơ bộ, không là evaluator nghiệm thu toàn dòng.
- **Vận hành/completeness:** [`audit_batch_outputs.py`](../../scripts/audit_batch_outputs.py), completion/receipt, cache/hash và tests publication/recovery đã có. Release gate có điều kiện bằng chứng cold/warm/cache và operation plan/SLO. Chưa có phép đo tải dài mới trong audit.

JSON/Markdown/TXT, workbook keyword và ma trận là đầu ra hiện có. PDF chữ ẩn của bridge là trung gian; không suy đó là searchable PDF sản phẩm. Excel keyword cũng không thay thế exporter mọi bảng tài chính. Đây là tính năng sản phẩm riêng, không phải lý do viết lại evaluator QA.

## Bằng chứng thực chạy

Lượt `20261107-qa-audit-governance`: **152 passed**, exit 0, 20,08 giây theo pytest. 11 file kiểm import, collect/splits, protocol, source overlap, human annotations, retry, detection và scorecard/release. [Lệnh/identity](../../scratch/runs/20261107-qa-audit-governance/run.json), [JUnit](../../scratch/runs/20261107-qa-audit-governance/evidence/junit.xml).

Probe preflight chạy đúng [mẫu protocol DRAFT hiện có](templates/benchmark_acceptance_protocol.example.yaml): CLI exit **1**, `NOT_READY_FOR_ACCEPTANCE_MEASUREMENT`, vì chưa `LOCKED`; quality giữ `NOT_EVALUATED`. Đây là kết quả từ chối mong đợi, không phải lỗi cần sửa để ép qua. [Probe](../../scratch/dev_sessions/20261107-qa-repository-audit/draft-preflight-probe.json).

125 test của phiên đối chiếu trước có artifact riêng, không cộng vào 152 và không gọi là chạy lại. Hash 12 focus trước được kiểm lại ở [đối chiếu](../../scratch/dev_sessions/20261107-qa-repository-audit/previous-review-focus-check.json); phạm vi này không là code/model closure toàn dự án.

Không đo branch/line coverage, OCR accuracy, runtime GPU hoặc soak; không chạy full regression/integration/golden. Các test trên là kiểm fixture/counterexample kỹ thuật. Không đổi mã/model/config/dependency/lock/GT/output lịch sử. Chi tiết bảo toàn và lệnh ở [nhật ký](../../scratch/dev_sessions/20261107-qa-repository-audit/session.md).
