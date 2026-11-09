# Đặc tả thứ tự đọc tự nhiên trên trang văn bản

Lập ngày 09/11/2026. Kế thừa tài liệu kỹ thuật Benchmark-first (§8.2 Reading Order Benchmark) và các phát hiện tại [02 Kiểm toán khoảng trống](02_KIEM_TOAN_KHOANG_TRONG.md) (G03). Đặc tả này khóa **nguyên tắc sắp xếp, hệ phân cấp đơn vị, quy tắc hình học, hệ đo lường và ranh giới với bộ đếm keyword**.

**Tầng áp dụng:** L5 (Bố cục, cột, thứ tự đọc) và L8 (Trích xuất và đếm từ khóa).  
**Trạng thái chất lượng:** `NOT_EVALUATED`. Chưa có bộ Ground Truth trật tự đọc độc lập cho 9 PDF báo cáo thường niên.

---

## 1. Mệnh đề yêu cầu và bất biến cốt lõi

Trật tự đọc (Reading Order) là chuỗi tuần tự tất định sắp xếp các khối văn bản, dòng chữ và token trên một trang tài liệu sao cho phản ánh chính xác luồng đọc hiểu tự nhiên của con người.

### Bất biến bắt buộc (Core Invariants)
1. **Bảo tồn toàn vẹn (Completeness / Conservation):** Mọi node văn bản (dòng chữ, từ, ô bảng, chú thích) được trích xuất trên trang phải xuất hiện **đúng 1 lần** trong chuỗi đọc. Nghiêm cấm bỏ rơi node (drop) hoặc nhân đôi node (duplication).
2. **Tính tất định (Determinism):** Cùng một tập hợp bounding box và nhãn vùng đầu vào, thuật toán sắp xếp phải luôn sinh ra một trật tự duy nhất, không phụ thuộc vào thứ tự ngẫu nhiên của mảng dữ liệu trong bộ nhớ.
3. **Phân tách vùng chức năng (Semantic Partitioning):** Nội dung lặp (Header, Footer, số trang) và nội dung trích dẫn phụ (Pull-quote) phải được định danh và tách khỏi luồng văn bản chính (Main Body Stream).

---

## 2. Hệ phân cấp đơn vị cấu trúc

Luồng đọc được xây dựng theo mô hình phân tầng hình cây (DOM-like Hierarchy):

$$\text{Document} \longrightarrow \text{Logical Page} \longrightarrow \text{Region / Block} \longrightarrow \text{Line} \longrightarrow \text{Word / Token}$$

| Cấp | Đơn vị | Vai trò trong luồng đọc |
| :--- | :--- | :--- |
| **Cấp 0** | **Trang logic (Logical Page)** | Đơn vị không gian độc lập sau khi đã xử lý xoay và tách trang đôi (1-UP/2-UP theo [Đặc tả 12](12_HUONG_VA_XOAY_TRANG_1UP_2UP.md)). |
| **Cấp 1** | **Khối bố cục (Layout Block)** | Vùng ngữ nghĩa: `Title`, `Section Header`, `Paragraph`, `Table`, `Figure`, `Caption`, `Header`, `Footer`, `Pull-quote`. |
| **Cấp 2** | **Dòng văn bản (TextLine)** | Chuỗi ký tự liên tục theo phương ngang, có tọa độ hộp bao `[x_min, y_min, x_max, y_max]`. |
| **Cấp 3** | **Từ / Token** | Đơn vị từ tố cơ sở cho bộ đếm Keyword (L8) và kiểm tra chính tả/dấu (L7). |

---

## 3. Bộ quy tắc sắp xếp trật tự đọc (Rules R-RO)

Mọi thuật toán (rule-based hay model-based) đều phải thỏa mãn 8 quy tắc sau:

### R-RO-01: Chiều đọc trong dòng (In-line Direction)
- Các token trong cùng một dòng văn bản được sắp xếp theo chiều từ **trái sang phải** theo tọa độ hoành độ tăng dần: $x_{0, i} \le x_{0, i+1}$.

### R-RO-02: Chiều đọc giữa các dòng trong khối (Inter-line Direction)
- Các dòng trong cùng một đoạn văn hoặc khối văn bản được sắp xếp từ **trên xuống dưới** theo tung độ tăng dần: $y_{0, j} \le y_{0, j+1}$.

### R-RO-03: Ưu tiên cột trái trước cột phải (Column Dominance)
- Trong bố cục đa cột song song (multi-column layout), toàn bộ các khối thuộc cột bên trái phải được đọc xong trước khi chuyển sang đọc dòng đầu tiên của cột bên phải liền kề:
  $$\text{Block}_A \in \text{Col}_L, \text{Block}_B \in \text{Col}_R \implies \text{Order}(\text{Block}_A) < \text{Order}(\text{Block}_B)$$

### R-RO-04: Khối tràn ngang cắt dải (Span-Block Interruption)
- Khi một khối văn bản (tiêu đề lớn, bảng biểu rộng, hình vẽ) trải dài qua nhiều cột (spans multiple columns):
  - Toàn bộ nội dung các cột nằm **phía trên** khối tràn ngang phải kết thúc trước.
  - Đọc nội dung của khối tràn ngang.
  - Tiếp tục đọc các cột nằm **phía dưới** khối tràn ngang theo quy tắc cột trái trước cột phải.

### R-RO-05: Cô lập Header, Footer và Số trang (Header/Footer Isolation)
- `Header` và `Footer` không được chen ngang vào giữa các đoạn văn bản.
- Header được đánh chỉ mục đọc ở đầu trang (hoặc luồng metadata riêng).
- Footer và số trang được đánh chỉ mục ở cuối cùng của trang logic.

### R-RO-06: Xử lý đoạn trích nổi bật (Pull-Quote Handling)
- Pull-quote (khối chữ to trích lại một câu trong bài viết thường gặp trong báo cáo thường niên) được gán cờ `is_pull_quote = True`.
- Khối này được đặt ngay sau đoạn văn chứa nó hoặc ở cuối trang, tránh làm đứt mạch câu văn chính.

### R-RO-07: Bảng biểu và Chú thích (Table & Caption Continuity)
- Bảng biểu (`Table`) được coi là một khối thống nhất trong luồng đọc trang.
- Chú thích (`Caption`) đi liền trước hoặc ngay sau bảng theo cấu trúc ngữ nghĩa; không để dòng văn bản thân bài chen vào giữa Bảng và Chú thích của nó.

### R-RO-08: Nối trang và Nối cột (Continuation across Pages & Columns)
- Khi một câu bị ngắt dở ở cuối cột hoặc cuối trang (không có dấu kết thúc câu `.`, `!`, `?`): dòng đầu tiên của cột tiếp theo hoặc trang logic tiếp theo phải liên kết trơn tru với dòng trước đó mà không bị chèn bởi header/footer.

---

## 4. Tác động trực tiếp tới Bộ đếm Keyword (L8)

Trật tự đọc sai sẽ dẫn đến việc ghép sai từ khóa dạng cụm nhiều từ (multi-word keywords) cắt ngang cột hoặc trang. Theo quyết định kiểm toán:

1. **Phân tách luồng đếm:**
   - **Số đếm chính (Primary Count):** Chỉ tính các lần xuất hiện của keyword nằm trong khối thân bài (`Paragraph`), tiêu đề (`Title`/`Header_Section`) và bảng biểu (`Table`).
   - **Số đếm phụ (Auxiliary / Secondary Count):** Các keyword xuất hiện trong `Header`, `Footer`, `Số trang` hoặc `Pull-quote` được đếm và ghi vào một **cột riêng** trong bảng Excel / SQLite (`header_footer_occurrences`).
   - Tuyệt đối không cộng dồn số đếm Header/Footer lặp vào số đếm thân bài chính thức để tránh sai lệch báo cáo tài chính.
2. **Khớp từ khóa xuyên dòng:**
   - Chỉ cho phép ghép từ khóa khi khoảng cách dọc giữa 2 dòng liên tiếp trong cùng một khối thỏa mãn ngưỡng tiếp giáp dòng hợp lệ, ngăn chặn việc ghép nhầm 2 dòng ở 2 cột khác nhau.

---

## 5. Thước đo trật tự đọc (Reading Order Metrics)

Đánh giá chất lượng của Challenger trật tự đọc dựa trên bộ tiêu chí chuẩn hóa:

| Metric | Ký hiệu | Ý nghĩa toán học |
| :--- | :--- | :--- |
| **Độ chính xác cặp liền kề** | `Pair_Acc` | Tỷ lệ cặp node $(A, B)$ có quan hệ đọc trước - đọc sau đúng so với Ground Truth: $\frac{\sum \mathbb{I}(\text{pred} = \text{gt})}{\binom{N}{2}}$. |
| **Tỷ lệ thiếu node** | `Missing_Node_Rate` | Tỷ lệ node văn bản có trong GT nhưng bị rơi rớt trong chuỗi đọc. Mục tiêu = 0%. |
| **Tỷ lệ nhân đôi node** | `Duplicate_Node_Rate` | Tỷ lệ node bị lặp lại nhiều lần trong chuỗi đọc. Mục tiêu = 0%. |
| **Tiếp nối sai đoạn** | `Incorrect_Continuation` | Số lần câu bị ngắt ngọn ghép sai sang khối khác. |
| **Căn chỉnh khối** | `Block_Alignment` | Mức độ trùng khớp giữa thứ tự phân nhóm khối dự đoán so với phân nhóm ngữ nghĩa GT. |

---

## 6. Hiện trạng mã nguồn và Lộ trình nâng cấp (P5)

- **Baseline hiện tại:** `src/ocr_structure/` sử dụng mô hình RT-DETR (Docling Heron) để phân vùng layout và áp dụng bộ heuristic hình học cơ bản (sắp xếp dựa trên ngưỡng tọa độ $y$ và $x$).
  - *Hạn chế:* Dễ bị lỗi đọc ngang xuyên cột khi tài liệu có 2 cột không đều, hoặc bảng chen giữa thân bài.
- **Lộ trình nâng cấp Challenger (P5, theo [03 Lộ trình](03_LO_TRINH_V8_THEO_TANG.md)):**
  1. Thử nghiệm **PP-DocLayout V3** (PaddleOCR 3.7): Nhận diện đa giác layout và trật tự đọc end-to-end.
  2. Thử nghiệm **LayoutReader** (EMNLP): Mô hình chuyên biệt sắp xếp thứ tự đọc dựa trên tọa độ hình học 2D.
  3. Mọi mô hình mới phải chạy qua khung [05 Hợp đồng Adapter](05_HOP_DONG_BENCHMARK_ADAPTER.md) và được đánh giá trên tập benchmark so sánh đối đầu trước khi xem xét tích hợp.

