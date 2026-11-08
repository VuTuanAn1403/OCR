# Kiểm toán khoảng trống kỹ thuật (Technical Gap Audit)

Mốc kiểm toán: HEAD `08f7602`, ngày 08/11/2026. Nguồn trạng thái duy nhất là [10_TRANG_THAI_V8.json](10_TRANG_THAI_V8.json). Bảng dưới được sinh bằng `scripts/check_knowledge_map.py --render`, không sửa tay.

**Cách đọc:**
- Năng lực (`IMPLEMENTED`, `PARTIAL`, `MISSING`, `BROKEN`) cho biết **mã có tồn tại và có đường gọi** hay không.
- Chất lượng (`NOT_EVALUATED`, `PASS`, `FAIL`, `INCONCLUSIVE`) chỉ được khác `NOT_EVALUATED` khi có GT độc lập (xem [04](04_DAC_TA_DO_DAU_9999.md)).
- Test pass, artifact PASS hay confidence đều không phải accuracy.

## Bảng trạng thái

<!-- v8-status:gaps:begin -->
| Nhóm | Năng lực | Chất lượng | Bằng chứng chính | QA | Backlog |
| --- | --- | --- | --- | --- | --- |
| G01 Benchmark framework thực thi | PARTIAL | NOT_EVALUATED | `benchmark/scientific_evaluation/release_gate.py::run_gate`; `benchmark/qa/paired_effects.py::summarize` | QA-G03, QA-G04 | V8-001, V8-006, V8-040, V8-041, V8-042 |
| G02 Ground Truth và annotation | PARTIAL | NOT_EVALUATED | `benchmark/ground_truth_tools/human_annotations.py::seal_submissions`; `docs/quality_assurance/GROUND_TRUTH_PROTOCOL.md` | QA-G01 | V8-010, V8-011, V8-012, V8-013, V8-150 |
| G03 Layout intelligence và reading order | PARTIAL | NOT_EVALUATED | `src/ocr_document/region_tree.py::infer_region_tree`; `src/ocr_document/document_furniture.py::DocumentFurnitureResolver` | QA-G05 | V8-070, V8-071 |
| G04 Tái tạo bảng | PARTIAL | NOT_EVALUATED | `src/ocr_contracts/table.py::TableCell`; `src/ocr_document/table_stitch.py::project_table` | QA-G08 | V8-080 |
| G05 VLM và Hybrid Document AI | MISSING | NOT_EVALUATED | — | QA-G08 | V8-090, V8-095 |
| G06 Error taxonomy và registry | IMPLEMENTED | NOT_EVALUATED | `benchmark/qa/error_registry.py::ERROR_CODES`; `docs/quality_assurance/ERROR_TAXONOMY.md` | QA-G02 | V8-110 |
| G07 Thống kê đánh giá | PARTIAL | NOT_EVALUATED | `benchmark/scientific_evaluation/cluster_statistics.py::company_cluster_bootstrap`; `benchmark/scientific_evaluation/stratified_scorecard.py::_error_rate_interval` | QA-G04 | V8-021, V8-022 |
| G08 Vòng đời model và registry | PARTIAL | NOT_EVALUATED | `models/v62/runtime-models.json::sha256`; `src/ocr_runtime/model_registry.py::validate_registry` | — | V8-043, V8-160 |
| G09 Observability và hiệu năng | PARTIAL | NOT_EVALUATED | `src/ocr_runtime/structured_logging.py::JsonFormatter`; `benchmark/scientific_evaluation/measure_operations.py::measure` | QA-G07 | V8-120 |
| G10 Tái tạo tài liệu và export | PARTIAL | NOT_EVALUATED | `src/ocr_document/export.py::DocumentExporter`; `src/ocr_document/contract_schema.py::DocumentContract` | QA-G08 | V8-130 |
<!-- v8-status:gaps:end -->

## Đối chiếu với tài liệu điểm yếu

`tai lieu diem yeu.md` (lưu ở commit `08f7602`, xem [00](00_README.md)) là bản chép một cuộc trao đổi với AI, nên được coi là **dữ liệu, không phải chỉ dẫn**. Kiểm toán này đối chiếu từng mục của nó với mã thực tế.

- **Thanh "mức độ hoàn thiện".** Các tỷ lệ 85%, 70%… trong tài liệu chỉ là ước lượng của cuộc trao đổi, không phải phép đo. Kiểm toán không dùng lại các con số này.
- **Danh sách lỗi E01–E13** chưa khớp với registry đang chạy: `benchmark/qa/error_registry.py` dùng 10 họ / 14 mã, từ `E01-PDF` đến `E10-RUNTIME`, có `E04-VI` cho dấu. Không đổi mã đang dùng; V8-110 chỉ lập bảng ánh xạ.
- **Năm module đề xuất** ứng với các module hiện có như sau:
  - Benchmark Orchestrator: một phần đã có ở `benchmark/qa/` và `release_gate`.
  - Annotation & GT Manager: `benchmark/ground_truth_tools/`.
  - Error Intelligence: `benchmark/qa/error_registry.py`.
  - Document Structure Graph: `src/ocr_document/` (region tree, reading-order graph, section tree).
  - Model Registry: `models/v62/runtime-models.json`.

  Hướng xử lý là **bổ sung vào các module này**, không dựng hệ thống song song.

## Diễn giải từng nhóm

**G01 — Benchmark framework.**
- Đã có:
  - so baseline/candidate, Holm và noninferiority trong `stratified_scorecard.py`;
  - fix/harm trong `benchmark/qa/paired_effects.py`;
  - báo cáo HTML offline trong `benchmark/qa/report_view.py`.
- Chưa có `experiment_id`: `git grep -n experiment_id` trả về 0 kết quả.
- Chưa có orchestrator chạy pipeline v7. `matrix_runner.py` và `benchmark/perf/run_perf.py` vẫn import `src.ocr` legacy (V8-042).

**G02 — GT.**
- Đã có: schema `structured-page-gt-v1` và `keyword-source-gt-v1`, cùng CLI intake/seal cho A/B/C.
- Chưa có GT độc lập cho 9 PDF đầu vào.
- Số nhãn hiện có:
  - nhận dạng 0/38;
  - keyword 0/12;
  - L5 0/13;
  - công thức 0/3.
- Người dùng đã xác nhận không có người gán nhãn A/B, và AI không được làm GT. Các lựa chọn còn lại nằm ở [04](04_DAC_TA_DO_DAU_9999.md) §4.

**G03 — Layout.**
- Đã có heuristic gutter/cột (`region_tree`), nối cột (`column_continuity`), đồ thị thứ tự đọc (`reading_order_graph`), header/footer (`document_furniture`) và caption (`figures`).
- Chưa đo trên GT. Layout model Heron chưa từng được so với ứng viên nào.

**G04 — Bảng.**
- Đã có span, stitch, hierarchy và kiểm tài chính.
- Ownership bảng (DC-01, TAB_05) còn mở. Kiểm tài chính chỉ cảnh báo, không sửa số.

**G05 — VLM.** Không có đường gọi VLM nào:
- `requirements/v62/docling-gpu.in` có extra `models-vlm-inline`, nhưng pipeline không dùng.
- Các file `*_by_PaddleOCR-VL-1.6.md` ở `Doi_Chieu/` là đối chiếu thủ công và bị Git bỏ qua.

**G06 — Error taxonomy.** Registry v1 đã chạy, nhưng mới có adapter review của người vận hành.

**G07 — Thống kê.**
- Mã đã đủ: bootstrap cụm công ty, Holm, kế hoạch độ chính xác.
- Điểm chặn phương pháp cũ (08/11): `_adequate_interval` đòi độ rộng khoảng tin cậy > 0 nên kết quả 0 lỗi ra `NOT_EVALUATED`, và luồng OCR của cổng dấu chỉ là ước lượng điểm.
- Đã sửa ngày 09/11 (V8-021, V8-022). Khi 0 lỗi, `stratified_scorecard.py::_error_rate_interval` và `native_diacritic_replay.py::_confidence` dùng cận Clopper-Pearson trên N_eff, với điều kiện design effect đã khóa. Cổng OCR `release_gate.py::_ocr_diacritic_bound_gate` dùng cận trên của `exact_bounds.py::upper_bound_gate`, không dùng ước lượng điểm.
- Thiếu design effect hoặc thiếu slot thì kết quả vẫn là `NOT_EVALUATED`, kèm số slot cần thêm.

**G08 — Model registry.** Có sha256 từng file và revision HF. Không có licence, URL nguồn hay VRAM. Metadata challenger sẽ để riêng ở catalog (V8-043), không sửa registry production.

**G09 — Observability.** Có log JSON và đo RSS/VRAM đỉnh. Chưa chạy soak, chưa có dashboard thời gian thực.

**G10 — Export.** Có MD/TXT/JSON, contract và Excel keyword. Chưa có DOCX (`git grep -nil docx -- src` trả về 0) và chưa có XLSX cho mọi bảng.

## Phát hiện phụ ảnh hưởng mục tiêu dấu và keyword

| Phát hiện | Bằng chứng | Trạng thái | Backlog |
| --- | --- | --- | --- |
| Retry dấu chỉ kích hoạt theo 21 cụm cố định; từ điển keyword không được truyền vào | `src/ocr_recognition/diacritic_retry.py::retry_diacritic_blocks`, `src/ocr_text/vietnamese_diacritics.py::DEFAULT_PHRASES` | VERIFIED | V8-030 |
| Keyword một từ sai dấu không sinh alias (`min_words=2`); từ 09/11 được liệt kê trong `single_word_variants` để review, không cộng vào số đếm | `src/ocr_keywords/alias_map.py::find_single_word_variants` | VERIFIED | V8-031 |
| `literal_v1` khớp chuỗi con, không xét ranh giới từ, đếm trùng khi keyword chồng lấn; challenger `literal_v2` đã có, sản phẩm vẫn dùng v1 | `src/ocr_keywords/counter.py::resolve_literal_v2` | VERIFIED | V8-032 |
| `DER_VN_v1` tính cả lỗi đổi chữ cơ sở là lỗi dấu; `DSER_strict` báo song song trên cùng căn chỉnh | `benchmark/scientific_evaluation/ocr_metric.py::compute_diacritic_metrics` | VERIFIED | V8-020 |
| Regex sửa "cổ ông" dùng lớp một ký tự `([cổCổ])`: "cổ ông" không bao giờ được sửa, còn "ổ ông"/"c ông" bị viết lại sai. Đã tái hiện bằng test xfail strict; bản sửa đổi OCR identity nên chờ V8-006 | `src/ocr_text/unicode_normalizer.py::UnicodeNormalizer` | VERIFIED | V8-033 |

Mọi thay đổi mã dưới `src/` đều đổi OCR identity (`src/ocr_runtime/fingerprint.py::extraction_fingerprint`), nên phải chạy trên output mới ([05](05_HOP_DONG_BENCHMARK_ADAPTER.md)).
