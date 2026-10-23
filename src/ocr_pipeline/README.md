# ocr_pipeline

Supervisor/document owner CPU: CLI, backend, batch/SQLite, điều phối worker, analysis và publication. Không import thư viện GPU/model; chạy worker bằng subprocess JSON có phiên bản.

- API/điểm vào: `cli.main` (`main_v63` là alias), `batch.process_batch`, `backend.prepare_backend`/`verify_runtime`, `scheduler.run_document`, `analysis_run.run_analysis`, `publication`, `batch_store`.
- Cài `python -m pip install -e ".[app,dev]" pytest`; không cần Torch/model để test state/protocol bằng double.
- Test: `test_v63_pipeline.py`, `test_analysis_run.py`, `test_v63_worker_acceptance.py`, `test_worker_protocol.py`, `test_stage_cache.py`, `test_model_identity.py`.
- Mọi nhánh nhận kết quả phải kiểm identity/receipt, artifact và process tree; chỉ acknowledge revision sau ghi và đọc kiểm workbook. Lỗi tài liệu không giữ số đếm cũ.
- Analysis xác minh extraction gốc, không tin provenance tự khai. Tài liệu nguồn thiếu file giữ hàng `FAILED_DOCUMENT`, counts `null`.
- Wheel hỗ trợ analysis CPU; backend V6.3 GPU cần checkout và hai runtime được khóa.

[Cài đặt, cách chạy và kiểm thử](../../README.md).
