# Ràng buộc kiến trúc khi đổi mã hoặc thử model

| Ràng buộc | Kiểm ở | Hệ quả |
| --- | --- | --- |
| Một pipeline sản phẩm, một profile `unified_gpu_full_ocr` | `src/ocr_runtime/pipeline_policy.py::validate_profile` | Không thêm profile hay CLI để chọn engine khác |
| Mọi `src/**/*.py` nằm trong OCR identity | `src/ocr_runtime/fingerprint.py::extraction_fingerprint` | Thêm hoặc sửa `.py` dưới `src/` thì cache, resume và receipt cũ hết hiệu lực; phải chạy output mới. README và script ngoài `src/` không ảnh hưởng |
| Analysis và publication có fingerprint riêng | `fingerprint.py::code_fingerprints` | Sửa keyword/Excel có thể chạy analysis mới trên extraction đã xác minh, không cần OCR lại |
| Phiên bản | `src/ocr_runtime/version.py::PIPELINE_VERSION` | Giữ `7.0.0` cho tới PR tích hợp v8 (V8-160); test khẳng định giá trị này |
| Registry model khóa sha | `src/ocr_runtime/model_registry.py::validate_registry` | Không sửa `models/v62/runtime-models.json` để thử model |
| Ranh giới import | `pyproject.toml` (import-linter), `tests/unit/test_import_contracts.py` | Production không được import `benchmark`; challenger cần contract riêng (V8-041) |
| Môi trường | AGENTS | Không cài Docling vào `.venv`, không trộn lock; challenger dùng `.venv-v8-<tên>/` riêng |
| OCR cần CUDA | AGENTS, `validate_gpu_source` | Thiếu GPU thì báo lỗi; CPU chỉ chạy export, keyword, analysis |
| Legacy đóng băng | `src/ocr/` | Chỉ là alias tương thích; không thêm tính năng |

## Chỗ đặt challenger

- **Mã adapter:** `benchmark/challengers/<tầng>/<ứng viên>/`.
- **Catalog model:** `benchmark/challengers/model_catalog.json`.
- **Output:** `scratch/benchmarks/<experiment_id>/`.
- **Báo cáo:** `cai tien v2/bao_cao/`.

Đặc tả đầy đủ ở [05](../../../../cai%20tien%20v2/05_HOP_DONG_BENCHMARK_ADAPTER.md). Không đặt thư mục con tên `reports/`, `logs/`, `lib/`, `build/`, `dist/`, vì `.gitignore` bỏ qua các tên này.

## Không bao giờ

- Sửa receipt, hash, lock hay batch đang chạy để ép kiểm tra qua.
- Để VLM ghi đè `text_raw` hoặc tự suy số tài chính.
- Tự động PROMOTE challenger vào production.
