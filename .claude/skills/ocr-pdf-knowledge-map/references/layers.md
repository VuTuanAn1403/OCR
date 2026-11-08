# Tầng pipeline → module → ký hiệu

Trạng thái năng lực và chất lượng của từng tầng **không ghi ở đây**; xem `--summary`. Muốn biết module nào ứng với test nào, xem [PROJECT_MAP](../../../../docs/development/PROJECT_MAP.md). File này chỉ cho biết **đi đâu trong mã**.

## Luồng chạy

`run_ocr.py` → `src/ocr/cli/unified.py` (alias legacy) → `ocr_pipeline.cli.main`. Từ đó:

1. `backend.prepare_backend`: kiểm profile, registry model và lock.
2. `batch.process_batch`: tạo SQLite `batch_state.sqlite`.
3. Với mỗi PDF, chạy subprocess `ocr_pipeline.document_owner` → `scheduler.run_document`. Scheduler chạy ba pha theo thứ tự `PHASES = ("text", "structure", "export")`, mỗi pha là một tiến trình `ocr_workers.phases`.
4. Sau ba pha: `document.validate_gpu_source` → `ocr_receipt.json` → `keyword_finalization.finalize_keywords` → `ocr_reporting.workbooks.export_document` → ma trận keyword.

Môi trường Python:
- `.venv`: supervisor, CPU, keyword, Excel.
- `.venv-v62/text`: pha A và client của pha B.
- `.venv-v62/docling`: server Docling.

## Bảng tầng

| Tầng | Package | Ký hiệu chính | Pha v8 |
| --- | --- | --- | --- |
| L0 PDF, render, text layer | [ocr_pdf_io](../../../../src/ocr_pdf_io/README.md) | `pdf_renderer.py::PDFRenderer`, `native_text_extractor.py::NativeTextExtractor`, `pdf_inspector.py::PDFInspector` | P2 |
| L1 Ảnh và tiền xử lý | ocr_pdf_io, [ocr_recognition](../../../../src/ocr_recognition/README.md) | `scan_image.py::acquire_page_image`, `orientation.py::orientation_candidate_score` | P2 |
| L2 Phát hiện chữ | ocr_recognition, [ocr_contracts](../../../../src/ocr_contracts/README.md) | `text_detector.py::ONNXTextDetector` (PP-OCRv4 ONNX DB), `text_detection.py::validate_snapshot` | P3 |
| L3 Nhận dạng chữ | ocr_recognition | `vietnamese_seq2seq_engine.py::VietnameseSeq2SeqEngine` (VietOCR), `primary_engine.py::BaseOCREngine`, `diacritic_retry.py::retry_diacritic_blocks`, `short_token_retry.py::retry_short_token_blocks` | P4 |
| L4 Layout | [ocr_layout](../../../../src/ocr_layout/README.md) | `torch_layout.py::TorchLayout` (Heron RT-DETR), `dla_engine.py::HeuristicLayoutClassifier` | P5 |
| L5 Thứ tự đọc | [ocr_document](../../../../src/ocr_document/README.md) | `reading_order_graph.py::solve_order`, `region_tree.py::infer_region_tree`, `column_continuity.py::join_column_continuations`, `document_furniture.py::DocumentFurnitureResolver` | P5 |
| L6 Bảng, công thức | [ocr_structure](../../../../src/ocr_structure/README.md), ocr_document | `docling_client.py::DoclingStructureExtractor`, `ocr_bridge.py::ocr_bridge`, `enrichment.py::enrich_structures`, `auto_table_stitch.py::build_auto_stitches`, `table_stitch.py::project_table` | P6 |
| L7 Hậu xử lý chữ | [ocr_text](../../../../src/ocr_text/README.md) | `unicode_normalizer.py::UnicodeNormalizer`, `numeric_guard.py::protected_numeric_spans`, `vietnamese_diacritics.py::diacritic_suspicions` | P8 |
| L8 Keyword | [ocr_keywords](../../../../src/ocr_keywords/README.md) | `counter.py::KeywordCounter`, `alias_map.py::find_alias_candidates`, `tiered.py::build_tiered_report` | P8 |
| L9 Export, Excel, runtime | ocr_document, [ocr_reporting](../../../../src/ocr_reporting/README.md), [ocr_pipeline](../../../../src/ocr_pipeline/README.md), [ocr_runtime](../../../../src/ocr_runtime/README.md) | `export.py::DocumentExporter`, `workbooks.py::export_document`, `scheduler.py::run_document`, `fingerprint.py::extraction_fingerprint` | P9 |

## Khu đánh giá (ngoài `src/`)

| Việc | Vị trí |
| --- | --- |
| CER/WER/DER | `benchmark/scientific_evaluation/ocr_metric.py::compute_der_detailed` |
| Cổng dấu | `diacritic_acceptance.py::evaluate_diacritic_acceptance`, `native_diacritic_replay.py::recompute_native_diacritics`, `release_gate.py::_ocr_diacritic_point_gate` |
| Keyword occurrence | `keyword_acceptance.py::evaluate` |
| Thống kê | `cluster_statistics.py::company_cluster_bootstrap`, `stratified_scorecard.py::evaluate` |
| Detection, bảng, thứ tự đọc | `text_detection_metric.py::evaluate_page`, `teds_metric.py::compute_teds`, `reading_order_metric.py::compute_reading_order_detailed` |
| So cặp và báo cáo QA | `benchmark/qa/paired_effects.py::summarize`, `benchmark/qa/report.py::build_report`, `benchmark/qa/error_registry.py::ERROR_CODES` |
| GT intake | `benchmark/ground_truth_tools/human_annotations.py::seal_submissions` |
| Khóa baseline (identity, không chạy OCR) | `scripts/lock_baseline.py::build_lock`; báo cáo `cai tien v2/bao_cao/BASELINE_LOCK_REPORT.md` |

Các tên file trong cột "Vị trí" thuộc `benchmark/scientific_evaluation/`, trừ những dòng ghi đường dẫn đầy đủ. Challenger trong tương lai đặt ở `benchmark/challengers/` ([constraints](constraints.md)).
