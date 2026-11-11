# Kỹ thuật phát hiện hướng, xoay trang và phân tách 1-UP / 2-UP

Lập ngày 09/11/2026. Kế thừa các số liệu đo thực nghiệm trên toàn bộ 938 trang PDF đầu vào và các phân tích tại [02 Kiểm toán khoảng trống](02_KIEM_TOAN_KHOANG_TRONG.md) (L1, P2). Tài liệu này đặc tả **hệ tọa độ, quy trình phát hiện hướng, tiêu chí phân tách trang đôi 2-UP và cơ chế ánh xạ ngược tọa độ**.

**Tầng áp dụng:** L0 (Tiếp nhận PDF), L1 (Tiền xử lý ảnh trang) và L9 (Hợp đồng trang và provenance).  
**Trạng thái chất lượng:** `NOT_EVALUATED`. Dữ liệu đo hình học là `VERIFIED`; kết luận phân loại 2-UP trên tập scan thuần ảnh là `HYPOTHESIS` chờ kiểm định qua OCR.

---

## 1. Dữ liệu khảo sát thực nghiệm trên 938 trang đầu vào

Khảo sát độc lập bằng PyMuPDF trên toàn bộ 9 PDF báo cáo thường niên đã xác minh các số liệu hình học sau:

| Đặc tính hình học | Số lượng trang | Chi tiết phân bố | Nhãn chứng cứ |
| :--- | :---: | :--- | :--- |
| **Cờ `/Rotate` trong PDF** | 937 trang 0°<br>1 trang 90° | Trang xoay duy nhất là `AGR 2020` trang 84 (MediaBox 842×595, hiển thị 595×842, scan thuần ảnh). | `VERIFIED` |
| **Chất lượng text layer gốc** | 650 trang > 200 ký tự<br>288 trang ít/không text | Các tài liệu `ABT`, `ACL` gần như toàn bộ là scan ảnh thuần, không có text layer. | `VERIFIED` |
| **Khổ ngang (Aspect ratio 1.30–1.50)** | 324 trang | Dạng gần A4 ngang ($297 \times 210$ mm). | `VERIFIED` |
| **Dấu hiệu 2-UP trên trang ngang có text** | 233 / 276 trang | 233 trang không có bất kỳ từ nào cắt qua trục giữa (x = 50% width); 224 trang có số trang in riêng ở chân mỗi nửa: tập trung ở `BCE` (41/42), `BHN` (46/48), `VIC` (146/147). | `VERIFIED` |
| **Dạng 1-UP ngang (bảng rộng)** | 43 / 276 trang | Chữ và bảng biểu cắt ngang qua trục giữa (gặp ở `AAA`, `AGR 2020/2022`, `ASM`). | `VERIFIED` |
| **Trang ngang không có text layer** | 48 trang | Gồm `BCE` (19), `BHN` (24), `ABT` (3), `VIC` (2) — cần tín hiệu ảnh để phân loại. | `HYPOTHESIS` |

### Thử nghiệm tín hiệu hình ảnh (Rãnh ít mực)
- Thử nghiệm quét hình chiếu dọc (vertical projection) tìm "rãnh gáy sách ít mực ở dải 45%–55% chiều ngang" (render độ phân giải thấp 24 DPI trong bộ nhớ):
  - Khớp 193/237 trang có rãnh text.
  - **Báo nhầm 25/39 trang 1-UP** (bảng rộng có khoảng cách giữa các cột trùng vào giữa trang).
  - 43/48 trang scan thuần ảnh có tín hiệu rãnh gáy.
- 👉 **Kết luận kiến trúc:** Một tín hiệu đơn lẻ không đủ để quyết định cắt trang. Phải kết hợp đa tín hiệu và có nhánh `UNCERTAIN` để chuyển sang xử lý an toàn.

---

## 2. Định nghĩa và Hệ quy chiếu tọa độ

- **Trang vật lý (Physical Page):** Mỗi trang trong file PDF đầu vào ($i \in \{1, 2, \dots, N\}$, với corpus hiện tại $N = 938$).
- **Trang logic (Logical Page):** Đơn vị nội dung sau khi phân tách:
  - Nếu là **1-UP**: 1 trang vật lý $\Longleftrightarrow$ 1 trang logic.
  - Nếu là **2-UP**: 1 trang vật lý $\Longleftrightarrow$ 2 trang logic: Nửa trái (Left - `L`) và Nửa phải (Right - `R`).
- **Hệ tọa độ gốc (Physical Canvas):** $x \in [0, W], y \in [0, H]$ tính theo điểm ảnh (pixels) ở render DPI chuẩn (144 DPI hoặc 200 DPI).

---

## 3. Quy trình kỹ thuật 6 bước (P2 Pipeline)

```
[PDF Page] 
    │
    ▼
1. Đọc Metadata (/Rotate, MediaBox)
    │
    ▼
2. Phát hiện hướng xoay trang (0°, 90°, 180°, 270°) ──► [Xoay về thẳng đứng]
    │
    ▼
3. Đánh giá phân loại: 1-UP / 2-UP / UNCERTAIN
    │
    ├───► [1-UP]: Giữ nguyên khổ trang
    │
    └───► [2-UP]: 4. Tách thành Trang Logic L và R
                     │
                     ▼
                  5. Deskew & Định hướng độc lập từng nửa
                     │
                     ▼
                  6. Ánh xạ ngược tọa độ Bounding Box về trang vật lý
```

### Bước 1: Tiếp nhận và đọc cờ PDF
- Kiểm tra cờ `/Rotate` trong từ điển Page của PDF. Nếu `/Rotate \in \{90, 180, 270\}`, áp dụng ma trận biến đổi affine đưa canvas hiển thị về chuẩn $0^\circ$.

### Bước 2: Phát hiện hướng xoay trang giấy (Orientation Detection)
- Với tài liệu scan hoặc cờ `/Rotate = 0` nhưng chữ bị scan ngược (upside-down 180°) hoặc nghiêng 90°:
  - Ứng viên mô hình: **PP-LCNet doc_ori** (tốc độ < 5ms/trang trên GPU).
  - Đầu ra: Góc xoay $\theta \in \{0^\circ, 90^\circ, 180^\circ, 270^\circ\}$.
  - Áp dụng phép xoay hình học đưa toàn bộ dòng chữ về chiều đọc từ trên xuống dưới.

### Bước 3: Đánh giá phân tách 1-UP và 2-UP (Multi-signal Fusion)
Kết hợp 3 nguồn tín hiệu:
1. **Tỷ lệ khung hình (Aspect Ratio):** Chỉ xét các trang có $W / H \ge 1.25$ (khổ ngang). Trang đứng ($W / H < 1.0$) mặc định là `1-UP`.
2. **Tín hiệu Text Layer (nếu có):**
   - Đếm số từ cắt qua dải trung tâm $[0.48 W, 0.52 W]$. Nếu $= 0$ và xuất hiện 2 cụm số trang ở chân 2 nửa $\implies$ trọng số 2-UP cao.
   - Nếu có bảng biểu hoặc câu văn trải dài từ $x < 0.4 W$ đến $x > 0.6 W \implies$ khẳng định `1-UP` (bảng rộng).
3. **Tín hiệu Hình ảnh (Image Projection Profile):**
   - Tính lược đồ mật độ pixel tối (ink projection) theo phương đứng tại dải giữa $[0.45 W, 0.55 W]$.
   - Phát hiện "vệt trắng/xám liên tục" đặc trưng của gáy sách hoặc đường viền trang in.
- **Quyết định:**
  - `CONFIRMED_2UP`: Thỏa mãn cả tỷ lệ ngang và không có văn bản cắt ngang.
  - `CONFIRMED_1UP`: Trang đứng hoặc trang ngang có bảng biểu/dòng chữ tràn qua giữa.
  - `UNCERTAIN`: Đưa vào hàng đợi xem xét (review queue); mặc định giữ nguyên 1-UP để không cắt nhầm văn bản.

### Bước 4: Tách trang logic (Splitting)
- Xác định đường cắt gáy sách $X_{\text{split}} \in [0.48 W, 0.52 W]$ tại vị trí có mật độ mực tối thiểu.
- Cắt thành 2 ảnh độc lập:
  - $\text{Page}_{\text{Left}} = \text{Crop}(0, 0, X_{\text{split}}, H)$
  - $\text{Page}_{\text{Right}} = \text{Crop}(X_{\text{split}}, 0, W, H)$
- **Quy ước đánh chỉ mục:**
  - `physical_page`: Giữ nguyên chỉ số trang gốc (ví dụ: Trang 42).
  - `logical_page`: `42_L` và `42_R`.
  - `printed_page`: Số trang in đọc được ở footer (nếu có, ví dụ: 82 và 83).

### Bước 5: Nắn thẳng độc lập (Individual Deskew)
- Hai trang của một bản scan 2-UP thường có góc nghiêng lệch nhau do độ cong gáy sách.
- Áp dụng thuật toán Radon Transform hoặc Hough Lines tính góc lệch $\alpha$ độc lập cho từng nửa trang logic ($\alpha_{\text{Left}} \ne \alpha_{\text{Right}}$), giới hạn $|\alpha| \le 5^\circ$.

### Bước 6: Ánh xạ ngược tọa độ và Lưu trữ Provenance
- Mọi hộp bao ký tự / từ / bảng phát hiện trên trang logic $\text{bbox}_{\text{local}} = [x_1, y_1, x_2, y_2]$ phải được ánh xạ ngược về hệ tọa độ trang vật lý:
  $$\text{bbox}_{\text{global}} = \begin{cases} [x_1, y_1, x_2, y_2] & \text{với nửa trái (L)} \\ [x_1 + X_{\text{split}}, y_1, x_2 + X_{\text{split}}, y_2] & \text{với nửa phải (R)} \end{cases}$$
- Đảm bảo tính truy xuất nguồn gốc (provenance): Khi nhấp vào bất kỳ từ khóa nào trên bảng báo cáo, hệ thống có thể đối chiếu chính xác vị trí trên ảnh PDF gốc.

---

## 4. Ràng buộc tương thích hợp đồng đầu ra (Output Contracts)

Theo quyết định đã thống nhất để không phá vỡ tính liên tục của hệ thống:
1. **Hợp đồng đếm trang (Page Count Contract):**
   - Hợp đồng `receipt.json`, `manifest.json` và bảng so sánh Baseline **vẫn giữ nguyên đơn vị 938 trang vật lý**.
   - Các bảng phân tích từ khóa và Excel bổ sung thêm cột định danh: `Trang vật lý` và `Nửa trang logic (L/R)`.
2. **Không làm hỏng Baseline:**
   - Việc tách 2-UP là một tính năng của tiền xử lý Challenger (P2). Kết quả so sánh giữa có tách và không tách 2-UP sẽ được đo đạc song song thông qua chỉ số phát hiện keyword bị đứt gãy.

