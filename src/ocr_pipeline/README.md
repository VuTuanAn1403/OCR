# ocr_pipeline

Supervisor/document owner CPU: CLI, backend, batch/SQLite, điều phối worker, analysis và publication. Không import thư viện GPU/model; chạy worker bằng subprocess JSON có phiên bản.

- API/điểm vào: `cli.main` (`main_v63` là alias), `batch.process_batch`, `backend.prepare_backend`/`verify_runtime`, `scheduler.run_document`, `analysis_run.run_analysis`, `review_packet.run_review`, `publication`, `batch_store`.
- Cài `python -m pip install -e ".[app,dev]" pytest`; không cần Torch/model để test state/protocol bằng double.
- Test: `test_input_contracts.py`, `test_v63_pipeline.py`, `test_analysis_run.py`, `test_v63_worker_acceptance.py`, `test_worker_protocol.py`, `test_stage_cache.py`, `test_model_identity.py`.
- Mọi nhánh nhận kết quả phải kiểm identity/receipt, artifact và process tree; chỉ acknowledge revision sau ghi và đọc kiểm workbook. Lỗi tài liệu không giữ số đếm cũ.
- Analysis xác minh extraction gốc, không tin provenance tự khai. Tài liệu nguồn thiếu file giữ hàng `FAILED_DOCUMENT`, counts `null`.
- `--alias-decisions` chỉ dành cho analysis. Snapshot quyết định v2 nằm trong config/identity; đổi bundle chặn resume, thay/mất file trong lượt chặn publication. Companion `keyword_two_tier.json` được dựng lại để đọc kiểm trước SQLite prepare và khi tái dùng; literal JSON/Excel vẫn theo `literal_v1`.
- `--alias-rules` khóa rules vào identity phân tích; CLI với dictionary mặc định dùng `config/alias_rules.json`, `--no-alias-rules` tắt trong lượt mới. API analysis mặc định không tự chọn rules. `AliasFinalizingProcessor` mở rộng bước CPU sau khi document worker thoát, không gọi lại OCR hay cộng vào literal. Đổi rules dùng analysis/output mới.
- Publication dựng lại companion và queue từ prepared revision, đọc kiểm các sheet Tier2/Pending/tổng sau duyệt rồi mới acknowledge. Queue `new_suspicions_queue.json` giữ unknown ở tài liệu lỗi/chưa xử lý. Snapshot dictionary/rules/quyết định cùng hash nằm trong `batch_config.json` và SQLite.
- Snapshot OCR/analysis kiểm số tài liệu trước đọc nội dung. File đổi đuôi từ định dạng khác sang `.pdf` giữ `source_error` và được đưa vào hàng lỗi trước khi gọi processor.
- `--review-from` xuất hàng đợi và gói crop có giới hạn từ nguồn đã kiểm. Giữ literal/raw, source ID, tọa độ, nguyên nhân và đề xuất chưa áp dụng. Gói có prediction để người vận hành rà, annotation và thời gian vẫn chờ điền. Kiểm tại `tests/unit/test_review_packet.py`.
- Cảnh báo `layout_review.item_ids` được nối theo source ID và hỗ trợ ID xuất cũ. Nguồn frozen chưa được xuất vẫn giữ lý do layout cần rà; các ID/raw/bbox không đổi.
- `--table-stitch-from` kiểm extraction gốc rồi dựng HTML/Markdown ghép thử theo plan, kèm bản đồ từ từng ô tới nguồn. Dùng thư mục output riêng. [Cách chạy](../ocr_document/TABLE_STITCH_V7.md).
- Wheel v7.0 hỗ trợ analysis và gói review CPU. Backend GPU cần checkout và hai runtime được khóa.

[Cài đặt, cách chạy và kiểm thử](../../README.md).
