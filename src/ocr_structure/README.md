# ocr_structure

Docling client, PDF bridge và ánh xạ bảng/công thức/sơ đồ lên chữ đã nhận dạng. Model Docling ở server/runtime riêng; client không import Docling, VietOCR hay model layout.

- API: `docling_client.DoclingStructureExtractor`, `ocr_bridge`, `enrichment.enrich_structures`, `document_layout_engine.DocumentLayoutEngine`, `diagram_builder`, `hidden_text_layer`.
- Client/fixture dùng môi trường `.[app]` và pytest; suite cấu trúc rộng có thể cần dependency legacy/test. Không cài Docling vào supervisor.
- Test độc lập: `python -m pytest tests/unit/structure -q -p no:cacheprovider`; fixture mẫu `tests/fixtures/migration/v63_sample` dùng Docling double trong test pha B.
- Giữ `raster-plus-gpu-text-v1`: cấu trúc phải bám text evidence/GPU bridge, không sao chép text layer native để vượt validator. Confidence chưa đo là `null`.
- Mã chỉ pha B thay đổi cần dùng lại pha A, chạy lại B và downstream; kiểm bằng stage call counter cùng receipt upstream.

[Cài đặt, cách chạy và kiểm thử](../../README.md).
