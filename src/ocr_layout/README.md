# ocr_layout

Adapter model layout và các bước áp layout lên bằng chứng trang. Package độc lập với recognizer; composition root nằm trong worker.

- API: `dla_engine.DLAEngine`, `model_adapters`, `torch_layout`, `page_content_analyzer.PageContentAnalyzer`, `steps`.
- Unit test dùng môi trường `.[legacy,test]`; model layout V6.3 chạy trong runtime text đã khóa. Không nâng model cùng một refactor.
- Test: `tests/unit/test_v6_layout_adapters.py`, `test_page_content_analyzer.py`, các test geometry liên quan; fixture không thay cho GT layout độc lập.
- Adapter mới chuẩn hóa capability/bbox/hệ tọa độ, không bịa confidence. Layout trên trang xoay phải có phép biến đổi xác minh được.
- Kiểm stage closure khi thêm dynamic import/model mới; sửa layout ảnh hưởng những pha thật sự đọc nó.

[Cài đặt, cách chạy và kiểm thử](../../README.md).
