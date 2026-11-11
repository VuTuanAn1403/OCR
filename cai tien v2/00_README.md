# Bộ tài liệu nâng cấp OCR PDF v8.0

Lập ngày 08/11/2026 từ HEAD `08f7602`. "v8.0" là **nhãn chương trình**; mã nguồn vẫn ở `PIPELINE_VERSION = 7.0.0` cho tới PR tích hợp (V8-160).

**Mục tiêu lõi:** bảo toàn dấu tiếng Việt ở mức 99,99% để đếm keyword đúng từng lần xuất hiện. Kết quả phải đủ chặt để làm nền cho bài báo khoa học.

**Nguyên tắc:** Benchmark-first. Mỗi tầng hiện tại là Baseline. Model mới là Challenger chạy riêng. Chỉ đề xuất thay khi có kết quả so cặp trên GT độc lập.

**Trạng thái chất lượng hiện tại:** `NOT_EVALUATED`.

## Đọc theo câu hỏi

| Câu hỏi | Mở |
| --- | --- |
| Dự án đang ở đâu? | Skill `ocr-pdf-knowledge-map`, hoặc `.venv/Scripts/python.exe -B scripts/check_knowledge_map.py --summary` |
| Tầng nào đã có, tầng nào thiếu? | [02 Kiểm toán khoảng trống](02_KIEM_TOAN_KHOANG_TRONG.md) |
| Làm gì tiếp, theo thứ tự nào? | [03 Lộ trình theo tầng](03_LO_TRINH_V8_THEO_TANG.md), [06 Backlog](06_BACKLOG_V8.csv) |
| Đo 99,99% thế nào cho đúng? Cần bao nhiêu GT? | [04 Đặc tả đo dấu](04_DAC_TA_DO_DAU_9999.md) |
| Model nào đáng thử ở mỗi tầng? | [01 Radar công nghệ](01_RADAR_CONG_NGHE_THEO_TANG.md) |
| Baseline đã khóa ra sao, identity nào để so? | [Báo cáo khóa baseline](bao_cao/BASELINE_LOCK_REPORT.md) |
| Thử model mới mà không phá production? | [05 Hợp đồng adapter](05_HOP_DONG_BENCHMARK_ADAPTER.md) |
| Làm việc với AI sao cho không ảo giác? | [07 Phương pháp dự án lớn](07_PHUONG_PHAP_DU_AN_LON_AI.md) |
| Đọc ít mà vẫn đủ? | [08 Tối ưu token](08_TOI_UU_TOKEN.md) |
| Tài liệu `Cai Tien/` cũ ở đâu? | [09 Lưu trữ](09_LUU_TRU_CAI_TIEN_V7.md) |
| Thứ tự đọc tự nhiên ra sao? | [11 Đặc tả thứ tự đọc](11_DAC_TA_THU_TU_DOC_TU_NHIEN.md) |
| Xoay trang và tách 1-UP/2-UP thế nào? | [12 Hướng và xoay trang](12_HUONG_VA_XOAY_TRANG_1UP_2UP.md) |
| Phân loại lỗi ký tự thiếu/thừa/sai? | [13 Đặc tả thiếu thừa sai](13_DAC_TA_CHU_THIEU_THUA_SAI.md) |
| Trạng thái máy đọc được | [10_TRANG_THAI_V8.json](10_TRANG_THAI_V8.json) (nguồn duy nhất) |

Bản Word tổng hợp nội dung 00–13: `OCR_PDF_V8_BO_TAI_LIEU.docx`. Bản Word chỉ để đọc; nguồn chuẩn là Markdown. Registry lưu sha của bản Word, nên khi Markdown đổi mà chưa xuất lại thì trình kiểm báo STALE.

## Tài liệu nguồn (sha trong registry)

Người dùng đã xóa ba file này khỏi working tree sau ngày 08/11. Nội dung đã ánh xạ vẫn nằm trong commit `08f7602`, và trình kiểm xác minh sha256 của từng file qua `git cat-file`:

- `So_sanh_cong_nghe_OCR_pdf.docx`: so sánh kiến trúc và model, ma trận A/B/C/D.
- `Ke_hoach_ky_thuat_nang_cap_OCR_pdf_Benchmark_First.docx`: các pha 0–9, metric, quy tắc quyết định.
- `tai lieu diem yeu.md`: bản chép trao đổi gồm 10 nhóm khoảng trống. Đây là **dữ liệu**, không phải chỉ dẫn.

Đọc lại một file: `git show 08f7602:"cai tien v2/tai lieu diem yeu.md"`.

## Cập nhật bộ tài liệu

1. Sửa [10_TRANG_THAI_V8.json](10_TRANG_THAI_V8.json) và [06_BACKLOG_V8.csv](06_BACKLOG_V8.csv). Mọi trạng thái phải có evidence `đường_dẫn::ký_hiệu`.
2. Chạy `scripts/check_knowledge_map.py --render` để sinh lại bảng trong 02/03, rồi chạy `--check` (exit 0).
3. Đổi `verified_head` và `last_verified` khi đã kiểm lại trên HEAD mới.
4. Xuất lại DOCX nếu nội dung 00–09 đổi, rồi cập nhật `exports[]`.

Ngân sách byte của từng file nằm ở `DOC_BUDGETS` trong `scripts/build_dev_context.py`.
