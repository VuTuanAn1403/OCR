# ocr_workers

Entry point pha A/B/export, Docling server và factory engine. Mỗi pha có vòng đời process giới hạn; GPU lease thuộc scheduler trong pipeline.

- Điểm vào: `python -m ocr_workers.phases --request <json> --phase <text|structure|export>`; `docling_server`; composition root `page_engines`.
- Không cài dependency chung cho mọi pha: runtime text và Docling dùng lock riêng. Export dùng interpreter text với CUDA bị ẩn; supervisor/document owner dùng extra app.
- Test không inference: `test_worker_protocol.py`, `test_v63_worker_acceptance.py`, `test_stage_cache.py`; fixture/double phải được ghi rõ. Kiểm quá trình thật qua timeout/crash/process con, không suy placement từ tên runtime.
- Receipt `stage_io` ràng buộc output/key/upstream; chỉ cache stage có hash hợp lệ và `exited.json` xác nhận cây process đã thoát. Stage không tự ghi publication SQLite.
- Chỉ một đường xử lý: `TextPageExtractor` OCR toàn trang, Docling nhận bridge OCR, export dùng `DocumentExporter`. Không import `src.ocr`; keyword được document owner hoàn tất sau export.
- Khi patch model trong test factory, patch `ocr_workers.page_engines.<Class>` tại nơi tra cứu, tránh nạp model thật ngoài dự kiến.

[Cài đặt, cách chạy và kiểm thử](../../README.md).
