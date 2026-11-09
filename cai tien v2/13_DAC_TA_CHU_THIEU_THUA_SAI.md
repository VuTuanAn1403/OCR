# Đặc tả phân loại lỗi: Ký tự Thiếu, Thừa, Sai

Lập ngày 09/11/2026. Bổ sung cho [04 Đặc tả đo dấu 99,99%](04_DAC_TA_DO_DAU_9999.md) và cơ chế bảo vệ số liệu tài chính (`numeric_guard`). Tài liệu này định nghĩa chuẩn hóa toán học cho 3 loại biến dạng ký tự: **Thiếu (Deletion), Thừa (Insertion), Sai (Substitution)**, phân tầng đánh giá và các bất biến an toàn khi hệ thống vận hành lúc chưa có Ground Truth.

**Tầng áp dụng:** L3 (Nhận dạng chữ OCR), L7 (Hậu xử lý Unicode và dấu) và L8 (Đếm từ khóa keyword).  
**Trạng thái chất lượng:** `NOT_EVALUATED`. Thước đo mã nguồn đã sẵn sàng ở `ocr_metric.py` và `exact_bounds.py`.

---

## 1. Chuẩn hóa đầu vào cố định (Fixed Normalization)

Mọi phép so sánh giữa chuỗi dự đoán (Candidate - $C$) và chuỗi đối chuẩn (Reference / Ground Truth - $R$) bắt buộc phải đi qua cùng một quy trình chuẩn hóa tất định trước khi tính khoảng cách sửa đổi Levenshtein:

1. **Chuẩn hóa Unicode NFC:** Đảm bảo toàn bộ các ký tự tổ hợp (combining marks) được gộp thành ký tự dựng sẵn chuẩn.
2. **Chuẩn hóa khoảng trắng nội dòng:** Rút gọn các khoảng trắng liên tiếp (`\t`, nhiều dấu cách) thành đúng 1 dấu cách đơn (` `); loại bỏ khoảng trắng ở đầu và cuối dòng (strip).
3. **Bảo toàn cấu trúc phân dòng:** Dấu xuống dòng (`\n`) không bị xóa bỏ tùy tiện, tránh làm dính chữ giữa tiêu đề và nội dung thân bài (như lỗi danh xưng "CÔNG TY CỔ \n ÔNG").

---

## 2. Định nghĩa toán học D / I / S

Gọi chuỗi đối chuẩn là $R = (r_1, r_2, \dots, r_m)$ và chuỗi dự đoán là $C = (c_1, c_2, \dots, c_n)$.
Phép căn chỉnh tối ưu Levenshtein Alignment cực tiểu hóa tổng trọng số biến đổi xác định 4 trạng thái tại mỗi vị trí căn chỉnh:

| Trạng thái | Ký hiệu | Định nghĩa toán học | Ví dụ trực quan ($R \to C$) |
| :--- | :---: | :--- | :--- |
| **Đúng (Match / Correct)** | $M$ | Ký tự xuất hiện trùng khớp hoàn toàn: $r_i = c_j$. | `doanh thu` $\to$ `doanh thu` |
| **Sai (Substitution)** | $S$ | Ký tự bị nhận dạng nhầm thành ký tự khác: $r_i \ne c_j$. | `báo cáo` $\to$ `báo các` (`o` $\to$ `c`) |
| **Thiếu (Deletion)** | $D$ | Ký tự có trong $R$ nhưng biến mất hoàn toàn trong $C$ (bị bỏ sót): $r_i \to \varepsilon$. | `cổ đông` $\to$ `cổ đng` (mất chữ `ô`) |
| **Thừa (Insertion)** | $I$ | Ký tự xuất hiện trong $C$ nhưng không hề có trong $R$ (rác / lặp): $\varepsilon \to c_j$. | `năm 2022` $\to$ `năm 20022` (thừa số `0`) |

Các chỉ số cơ sở:
$$\text{CER} = \frac{S + D + I}{N_R}, \quad \text{với } N_R = M + S + D$$

---

## 3. Phân tầng kiểm soát lỗi theo ngữ nghĩa

Không phải mọi lỗi ký tự đều có mức độ nghiêm trọng như nhau. Hệ thống chia thành 4 lớp kiểm soát:

```
[Lớp 1: Chữ cái thường] ──► CER / WER thông thường
[Lớp 2: Slot dấu tiếng Việt] ──► Cổng chất lượng 99,99% (DSER_strict)
[Lớp 3: Chữ số & Ký hiệu tài chính] ──► Bất biến Numeric Guard (Cấm sửa silent)
[Lớp 4: Từ khóa Keyword] ──► Độ chính xác đếm lần xuất hiện (Occurrence Precision)
```

### Lớp 1: Chữ cái cơ sở (Base Characters)
- Các lỗi thay thế chữ không dấu (ví dụ: `c` $\leftrightarrow$ `o`, `u` $\leftrightarrow$ `v`, `rn` $\leftrightarrow$ `m`).
- Đánh giá bằng CER tiêu chuẩn; không quy về lỗi dấu tiếng Việt.

### Lớp 2: Slot dấu tiếng Việt (Diacritic Slots - DSER_strict)
- Tách theo [Đặc tả 04](04_DAC_TA_DO_DAU_9999.md): Tone (thanh), Shape (mũ/móc/trăng) và Stroke (đ).
- **Phân định rạch ròi:**
  - Nếu chữ cái cơ sở đúng mà sai dấu (ví dụ: `thể` $\to$ `thế`): Tính là $S_{\text{diacritic}}$ (lỗi dấu).
  - Nếu chữ cái cơ sở bị nhận dạng sai (ví dụ: `vốn` $\to$ `bốn`): Ký tự này thuộc $S_{\text{base}}$, **không được đổ lỗi cho dấu** để tránh làm sai lệch độ đo DSER.

### Lớp 3: Chữ số và Dấu phân cách tài chính (Numeric Guard)
- Tập ký tự được bảo vệ nghiêm ngặt: `0123456789`, dấu phẩy `,`, dấu chấm `.`, dấu âm `-`, ký hiệu `%`.
- **Bất biến bất di bất dịch:** Tuyệt đối không tự động sửa (silent auto-correction) bất kỳ chữ số nào.
- Nếu OCR phát hiện nghi vấn (ví dụ số có 2 dấu chấm phân cách `12.34.56`): Chỉ được phép **gắn cờ cảnh báo** (`numeric_suspicion`), giữ nguyên chuỗi thô để con người hậu kiểm.

### Lớp 4: Lỗi cấp độ Từ khóa (Keyword Occurrences)
- **Thiếu lần xuất hiện (False Negative / Under-counting):** Do chữ trong từ khóa bị nhận dạng sai dấu hoặc thiếu chữ cái (ví dụ: `cổ đông` bị đọc thành `cổ đng`), dẫn đến bộ đếm từ khóa bỏ sót.
- **Thừa lần xuất hiện (False Positive / Over-counting):** 
  - Do cơ chế khớp chuỗi con lỏng lẻo (lỗi của `literal_v1` bắt nhầm `B2B` bên trong `B2B2C`). Đã khắc phục bằng `literal_v2` (xét ranh giới từ và khớp dài nhất).
  - Do từ khóa lặp lại liên tục ở `Header` và `Footer` mỗi trang. Đã quy định tách riêng thành cột phụ, không cộng dồn vào thân bài.

---

## 4. Các bất biến bảo toàn khi chạy lúc chưa có GT (Runtime Safety Invariants)

Khi hệ thống vận hành thực tế trên dữ liệu mới chưa có Ground Truth kiểm toán:

1. **Nguyên tắc "Không nuốt chữ" (No Silent Drop):**
   - Mọi dòng chữ mà mô hình Detection bắt được đều phải đi qua mô hình Recognition và được ghi nhận vào `document.json`.
   - Cấm loại bỏ dòng chữ chỉ vì điểm số tin cậy (confidence score) thấp. Nếu confidence thấp, ghi nhận giá trị và gắn nhãn cảnh báo.
2. **Nguyên tắc "Bảo toàn tọa độ và nguồn gốc" (Provenance Preservation):**
   - Mỗi ký tự / từ trong output bắt buộc phải mang theo: `bbox` (tọa độ pixel), `page_index` (trang vật lý), `confidence` và `source_id`.
3. **Xử lý từ khóa một từ (Single-word Keywords):**
   - Đối với từ khóa chỉ có 1 từ (ví dụ: `ESG`, `xanh`): Nếu sai 1 ký tự hoặc sai dấu, hệ thống ghi nhận vào danh sách `single_word_variants` để kiểm toán, không tự động quy chụp cộng dồn.

