# ocr_runtime

Paths/config, registry/model/dependency lock, fingerprint, GPU lease, process tree và chẩn đoán môi trường. Supervisor chỉ dùng API nhẹ; model/probe chạy trong process mục tiêu khi được yêu cầu.

- API: `paths`, `config`, `models`, `fingerprint`, `dependency_lock`, `process_tree.supervised_run`, `gpu_lease`; `python -m ocr_runtime.diagnose --json` chỉ đọc.
- Dependency runtime: contracts/artifacts, PyYAML, psutil; `.[app]` là extra hỗ trợ sẵn. Cài `python -m pip install -e ".[app,dev]" pytest`.
- Test: `tests/unit/runtime`, `test_migration_code_roots.py`, `test_model_identity.py`, `test_venv_interpreter_paths.py`. Hai test import worker trong `test_runtime_package.py` skip khi chưa có runtime; không phải pass inference.
- Không resolve symlink Python venv thành interpreter hệ thống. Không sync runtime đang được batch dùng. Hash model phải chọn đúng file engine nạp, kể cả model nằm ngoài checkout.
- Khi đổi fingerprint, kiểm coverage mã coordinator/worker và stage invalidation bằng call counter, không chỉ chuỗi hash.

[Cấu hình/precedence/sao lưu](../../docs/architecture/CAU_HINH_VA_DU_LIEU.md); [hướng dẫn phát triển](../../docs/architecture/HUONG_DAN_PHAT_TRIEN_MODULE.md).
