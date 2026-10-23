# ocr_workers

Entry point pha A/B/export, Docling server và factory engine. Mỗi pha có vòng đời process giới hạn; GPU lease thuộc scheduler trong pipeline.

- Điểm vào: `python -m ocr_workers.phases --request <json> --phase <text|structure|export>`; `docling_server`; composition root `page_engines`.
- Không cài dependency chung cho mọi pha: runtime text và Docling dùng lock riêng. Export dùng interpreter text với CUDA bị ẩn; supervisor/document owner dùng extra app.
- Test không inference: `test_worker_protocol.py`, `test_v63_worker_acceptance.py`, `test_stage_cache.py`; fixture/double phải được ghi rõ. Kiểm quá trình thật qua timeout/crash/process con, không suy placement từ tên runtime.
- Receipt `stage_io` ràng buộc output/key/upstream; chỉ cache stage có hash hợp lệ và `exited.json` xác nhận cây process đã thoát. Stage không tự ghi publication SQLite.
- Ngoại lệ legacy còn giữ: pha A V6.2 dùng `ProcessPageUseCase`, hook export V6.2 finalize cũ. Lý do và điều kiện gỡ nằm trong `module_map.json`; V6.3 không dùng các hook đó.
- Khi patch model trong test factory, patch `ocr_workers.page_engines.<Class>` tại nơi tra cứu, tránh nạp model thật ngoài dự kiến.

Protocol/adapter/runtime/fingerprint: [hướng dẫn chung](../../docs/architecture/HUONG_DAN_PHAT_TRIEN_MODULE.md).
