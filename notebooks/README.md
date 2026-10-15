# Chạy OCR V6.1 trên Google Colab GPU

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/VuTuanAn1403/OCR/blob/main/notebooks/colab_v6.ipynb)

1. Mở notebook bằng nút trên, hoặc tải `colab_v6.ipynb` lên Colab.
2. Chọn **Runtime → Change runtime type → GPU**.
3. Giữ `PROFILE = "balanced"` để chạy VietOCR + Docling TableFormer/CodeFormula; chọn `"local"` cho VietOCR GPU và bảng heuristic/vector.
4. Up PDF vào **MyDrive/ocr_pdf/data/raw/**, đặt file `.pdf` trực tiếp trong thư mục này.
5. Chạy các ô theo thứ tự: mount Drive, clone repo, cài Python 3.11/môi trường CUDA, kiểm tra GPU và smoke một trang.
6. Sau khi smoke thành công, đặt `RUN_FULL_BATCH = True` ở ô cấu hình và chạy lại ô xử lý lô. `FILE_LIMIT = None` xử lý mọi PDF; đặt số nguyên để giới hạn.

Mã nguồn lấy từ `https://github.com/VuTuanAn1403/OCR.git`. `REVISION = "main"` lấy bản mới nhất và ghi SHA thực tế; thay bằng commit SHA để tái lập. Notebook dùng `subprocess` kiểm tra mã thoát, không tiếp tục sau lỗi cài đặt. Khi ngắt ô xử lý, nhóm process CLI/Docling được dừng cùng nhau.

Python của kernel Colab không bị cài đè các thư viện OCR. uv cài Python 3.11 riêng, tạo `.venv` cho VietOCR và `.venv-docling` cho Docling, chọn wheel PyTorch CUDA 12.6 chính thức. Cả hai môi trường được kiểm tra CUDA; các dependency portable không chứa `pywin32` hay pin torch `+cpu` từ lock Windows.

Drive lưu:

| Thư mục | Nội dung |
|---|---|
| `ocr_pdf/data/raw/` | PDF đầu vào |
| `ocr_pdf/models/` | Model VietOCR/Docling, dùng lại qua các phiên |
| `ocr_pdf/cache/<profile>/` | Cache tương thích cấu hình/mã/model |
| `ocr_pdf/outputs/<profile>/` | Kết quả lô, báo cáo JSON/CSV/Excel |
| `ocr_pdf/outputs/smoke-.../` | Kết quả chạy thử riêng |
| `ocr_pdf/logs/` | Log, commit SHA và freeze môi trường |

Giữ cả thư mục tài liệu khi sao chép đầu ra compact, gồm `pages/`, `extraction.json`, `structure.json`, `document.json`, `document.md`. Trạng thái `NEEDS_REVIEW` yêu cầu kiểm tra nội dung; không phải lỗi cài đặt hay chứng nhận độ chính xác.

Mặc định `SHARD, SHARDS = 0, 1` chạy toàn bộ tập trên một phiên. Chỉ chia shard khi chủ động tổ chức nhiều phiên được phép sử dụng; cần hoàn tất mọi shard trước khi gộp. Chạy lại ô batch sẽ kiểm tài liệu hoàn tất và dùng cache tương thích. Không dùng resume/cache khi đo baseline hiệu năng.

**Trạng thái kiểm chứng:** notebook đã được kiểm tra cấu trúc và cú pháp; dependency của môi trường chính và Docling đã resolve cho Python 3.11/Linux/CUDA. VietOCR GPU đã chạy thực trên RTX 2050/Windows. Chưa thực thi notebook trong phiên Colab hoặc nghiệm thu Docling GPU trên Colab; model bảng/công thức sẽ tải ở lần warm-up đầu.

GPU và giới hạn phiên [không được Colab bảo đảm cố định](https://research.google.com/colaboratory/faq.html). Notebook không cần `docs/`, môi trường ảo, model hay dữ liệu runtime trong GitHub.
