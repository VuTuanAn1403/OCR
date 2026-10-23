# ocr_recognition

Detector/recognizer, đánh giá chữ, routing và các bước inference. Không phụ thuộc model layout hoặc Docling; engine được factory worker khởi tạo rồi truyền vào bước xử lý.

- API theo vai trò: `text_detector.ONNXTextDetector`, `vietnamese_seq2seq_engine.VietnameseSeq2SeqEngine`, `rapidocr_engine.RapidOCREngine` (legacy); các bước trong `inference`, `primary_engine`, `blocks`, `orientation`.
- Dùng `.[legacy,test]` cho unit/legacy CPU; inference V6.3 dùng runtime text từ lock riêng, không cài ONNX Runtime CPU vào runtime GPU.
- Test package: `tests/unit/recognition`; thêm test routing/native quality/numeric theo thay đổi. Mock tại `ocr_workers.page_engines` khi kiểm factory; fixture/double không phải inference model thật.
- Adapter mới phải khai báo capability, nguồn chữ và placement đo được. Không tạo confidence hoặc nhãn GPU cho dữ liệu không đo.
- Thay code/model pha A phải làm mất hiệu lực các stage downstream; giữ nguyên baseline khi chỉ di chuyển mã.

[Cài đặt, cách chạy và kiểm thử](../../README.md).
