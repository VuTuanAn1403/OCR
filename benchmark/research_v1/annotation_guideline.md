# Research V1 Ground Truth Annotation Guideline

## 1. Mục đích và Phạm vi
Tài liệu này quy định quy chuẩn gán nhãn (Ground Truth Annotation Guideline) cho tập dữ liệu benchmark nghiên cứu khoa học V5 (`benchmark/research_v1/`).
Phạm vi bao gồm tất cả các thể loại PDF thực tế: văn bản hành chính, báo cáo tài chính, tạp chí khoa học nhiều cột, tài liệu kỹ thuật scan, form biểu mẫu.

## 2. Nguyên tắc Bất biến (Core Principles)
1. **Không giả mạo Human Verification**: Kết quả do AI sinh ra (OCR/LLM) chỉ được gắn nhãn `AI_GENERATED_CANDIDATE`. Tuyệt đối không tự phong là `HUMAN_VERIFIED` khi chưa qua quy trình thẩm định độc lập 2 vòng (double-blind cross-check).
2. **Trạng thái gán nhãn 3 mức**: Đối với từng trường (text, table, layout, numeric, reading_order), phải khai báo rõ ràng 1 trong 3 trạng thái:
   - `not_annotated`: Vùng/trang chưa được gán nhãn. Evaluator chuyển sang chế độ `PARTIAL_GT` và bỏ qua trường này, không phạt thành False Positive.
   - `annotated_empty`: Người gán nhãn xác nhận vùng/trang này hoàn toàn KHÔNG CÓ thực thể (ví dụ trang trắng, trang không có bảng). Nếu mô hình trích xuất ra thực thể, sẽ bị phạt là hallucination / spurious entity.
   - `annotated_nonempty`: Người gán nhãn cung cấp dữ liệu thực thể chuẩn.
3. **Phân tách Rõ Ràng giữa Artifacts và Fixtures**: Thư mục `fixtures/` chỉ dùng cho unit tests/regression test các hàm toán học, không được tính vào empirical benchmark.

## 3. Quy chuẩn Gán nhãn cho Từng Modal

### 3.1. Text & OCR
- Chuẩn hóa Unicode: Lưu trữ dạng Canonical NFC.
- Giữ nguyên toàn bộ dấu câu, chữ số, ngắt dòng ngữ nghĩa.
- Ký tự Tiếng Việt: Phân biệt rõ cấu tạo dấu thanh (sắc, huyền, hỏi, ngã, nặng), dấu mũ/móc (â, ă, ê, ô, ơ, ư) và nét gạch chữ `đ` (`U+0111`) / `Đ` (`U+0110`).

### 3.2. Tables
- Biểu diễn chuẩn: HTML markup `<table>...</table>` với cấu trúc `<tr>`, `<th>`, `<td>`.
- Ghi nhận chính xác thuộc tính gộp ô `colspan` và `rowspan`.
- Nội dung ô: Whitespace trong ô được chuẩn hóa rút gọn đơn lẻ (`" ".join(text.split())`).

### 3.3. Document Layout Analysis (DLA)
- Bounding Box: Hỗ trợ cả 2 định dạng chuẩn:
  - `xyxy`: `[x0, y0, x1, y1]` theo tọa độ PDF point (72 dpi) hoặc pixel ảnh.
  - COCO `xywh`: `[x, y, width, height]`.
- Phân loại (10 categories chuẩn):
  `title`, `section_header`, `text`, `header`, `footer`, `page_number`, `table`, `figure`, `caption`, `formula`.
- Nếu một class không xuất hiện trong tài liệu (absent class): Gán `total_gt = 0`, evaluator trả về `AP = None`, không làm sai lệch mAP.

### 3.4. Numeric Entities
- Phân biệt số âm định dạng kế toán: `(100)` != `100`.
- Giữ nguyên số 0 ở đầu (leading zeros): `00123`.
- Tỷ lệ phần trăm và đơn vị: `12%`, `15.000 VNĐ`, `USD`.
- Định dạng ngày tháng: `09/10/2026`, `2026-10-09`.

### 3.5. Reading Order
- Danh sách các text block ID theo thứ tự đọc tự nhiên từ trên xuống dưới, từ trái sang phải theo cột đọc logic của con người.
- Thứ tự đọc trong tài liệu 2 cột: Cột trái đọc hết -> Cột phải.
