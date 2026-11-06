# Global Alias Rules và quy trình kiểm thử trên Kaggle

Cập nhật 06/11/2026, Asia/Bangkok. Tài liệu thiết kế do người dùng cung cấp, được đối chiếu với checkout hiện tại. Đây không phải biên bản duyệt GT hay chứng nhận độ chính xác. Bộ từ khóa vẫn là **v1, 86 display/86 canonical**; schema rules v1 và companion v3 không phải bộ keyword v2 đã hủy.

## 1. Phạm vi và bằng chứng

Mục tiêu là tự áp dụng các alias đã cấu hình, đưa biến thể chưa có quy tắc vào hàng đợi và giữ nguyên phép đếm literal. Triển khai nằm ở `ocr_keywords/global_rules.py`, `ocr_keywords/tiered.py`, `ocr_pipeline/alias_finalization.py`, analysis/publication và notebook chuẩn.

Bản nháp trước ghi “15 chấp nhận/8 loại trừ do người thẩm định”. Chưa có biên bản người và identity đủ để dùng mệnh đề đó làm bằng chứng. Các lượt thử ảnh AI chỉ là diagnostic, không phải GT độc lập. Phép đối chiếu lịch sử 9 PDF/938 trang/165 literal chứng minh tính nhất quán trên Markdown đã xác minh; không chứng minh đủ mọi keyword trên ảnh PDF.

Các tỷ lệ tự động hóa 90%/99%, thời gian duyệt ba phút, tái đếm vài giây và suy luận lượng biến thể mới tiệm cận về 0 là giả thuyết chưa đo. Không dùng chúng làm tiêu chí đã đạt. Phiên triển khai và lệnh thực chạy được ghi tại `scratch/dev_sessions/20261106-alias-rules-kaggle/session.md`; thư mục scratch/output cần lưu kèm khi bàn giao.

## 2. Ba luồng đếm

1. **Literal**: `literal_v1` giữ NFC + casefold và đúng ngữ nghĩa matcher hiện có, đếm trên `result.md`. Không sửa chữ, số hoặc cộng alias vào `canonical_counts`, `display_counts` hay sheet literal.
2. **Alias đã giải quyết**: alias khớp quy tắc chấp nhận được tính riêng vào tầng 2 với `resolution_source=auto_alias_rule`. Quy tắc loại trừ tạo `REJECTED` với `auto_disallow_rule`; không làm giảm hay sửa tầng 1.
3. **Nghi vấn mới**: ứng viên không khớp quy tắc giữ `review_status=NOT_EVALUATED` và được xuất ra `new_suspicions_queue.json`. Số alias đã chấp nhận có thể bằng 0 trong khi Pending lớn hơn 0; điều này không có nghĩa đã duyệt hết.

Candidate finder chỉ phát hiện các biến thể dấu cùng khung chữ cái trong cụm nhiều từ. Đây không phải fuzzy hay bộ phát hiện mọi lỗi OCR. Dấu câu giữa các từ không bị xóa để tạo ứng viên. NFC + casefold áp dụng cho phép so rule; khoảng trắng/ngắt đoạn không tự gộp thành một alias đã biết. Vì vậy `tài chính\n\nSố` có thể còn Pending, còn `tài chính. Số` không được biến thành một cụm liên tục.

Với một occurrence, thứ tự ưu tiên là: **quyết định v2 theo occurrence đã xác minh identity → rule toàn cục khớp alias/ngữ cảnh → Pending**. Quyết định `REJECTED` hoặc `REVOKED` không bị rule chấp nhận ghi đè. Trùng quyết định/biến thể không được cộng hai lần. Chưa có quy tắc tổng quát được học từ một quyết định occurrence; việc nâng thành global rule là thao tác cấu hình có chủ đích.

## 3. Hợp đồng alias_rules.json

Nguồn chuẩn: `config/alias_rules.json`. Những alias dài từ ví dụ thiết kế được giữ; alias ngắn có nguy cơ khác nghĩa phải có ràng buộc ngữ cảnh. Không gán vai trò người duyệt cho AI hoặc coi curator trong JSON là chữ ký kiểm toán.

Schema bắt buộc có đủ `schema_version`, `updated_at_utc` có timezone, `curator`, `normalization_policy=NFC_CASEFOLD`, `approved_global_aliases`, `disallowed_false_positives`. Target phải thuộc dictionary snapshot. Alias phải khác literal, cùng khung chữ cái không dấu, nhiều từ; không đổi chữ nền hoặc số. Thiếu file, JSON trùng key, schema lạ, target lạ, xung đột accept/reject hoặc checksum sai đều bị chặn.

Giá trị mỗi target là danh sách chuỗi hoặc object có `alias`, `required_before`, `required_after`. Ví dụ:

```json
{
  "schema_version": "alias-rules-v1",
  "updated_at_utc": "2026-11-06T07:00:00Z",
  "curator": "reviewed-project-rule-set",
  "normalization_policy": "NFC_CASEFOLD",
  "approved_global_aliases": {
    "Chuyển đổi số": ["chuyển đối số"],
    "Đổi mới": [
      {"alias": "đồi mới", "required_before": "sáng tạo"},
      {"alias": "đối mới", "required_after": "tài sản"}
    ]
  },
  "disallowed_false_positives": {"Đổi mới": ["đời mới", "đổi môi"]}
}
```

Ngữ cảnh là chuỗi literal đã chuẩn hóa với ranh giới token, nằm cùng đoạn; không phải regex do người dùng thực thi. Thiếu ngữ cảnh cần thiết thì Pending. Ví dụ “câu đối mới”, “ngọn đồi mới” không tự được tính là “Đổi mới”. Các alias khác nghĩa vẫn có thể tồn tại ngoài tập mẫu; curator phải giới hạn rule theo bằng chứng. Không có cam kết loại bỏ mọi dương tính giả.

File khởi tạo hiện có 5 target chấp nhận, 6 dạng alias khác nhau, 7 rule chấp nhận sau khi thêm điều kiện ngữ cảnh; 2 target loại trừ với 3 rule. Những dòng chỉ khác chữ hoa/thường hoặc NFC/NFD được gộp. Bản nháp liệt kê 9 chuỗi whitelist bề mặt, không phải 8; không cần lặp lại chữ hoa trong cấu hình.

## 4. Identity, provenance và publication

Extraction giữ PDF identity, receipt, Markdown, code/model/lock/runtime và đủ mọi trang. Phân tích giữ dictionary snapshot, toàn bộ normalized rule snapshot, SHA-256 byte file rules, snapshot quyết định occurrence nếu có. Snapshot này nằm trong `batch_config.json` và identity SQLite. Rule ID được dựng tất định từ target, alias, trạng thái và điều kiện.

- Đổi rules/dictionary/decision bundle: dùng output analysis mới, không sửa receipt hay batch cũ để resume qua.
- File rules bị đổi/mất trong lượt: chặn trước SQLite prepare/publication.
- Companion `keyword_two_tier.json` v3 được dựng lại từ report, text và snapshot để đọc kiểm trước chấp nhận và publication. Trường literal giữ nguyên so với `keyword_counts.json`.
- Companion, Excel, queue và projection phải khớp revision trước acknowledge. Nếu crash giữa ghi file và acknowledge, resume dựng lại từ revision đã prepare.
- `new_suspicions_queue.json` chứa document/PDF/MD/dictionary/rule hash, observed text, keyword, NFC offsets, trang/ngữ cảnh và trạng thái. Chưa căn được bbox thì giữ `bbox=null`, `placement_status=MARKDOWN_OFFSET_ONLY`; trang không rõ giữ unresolved. Không suy bbox từ độ dài chữ. Bảng logic có thể ghi nhiều trang nguồn thay vì đoán một trang.
- Tài liệu lỗi/chưa xử lý không có số đếm. Queue ghi `documents_not_evaluated`; tổng Pending toàn batch để null nếu coverage chưa đủ.

Schema v2 occurrence decisions vẫn bắt buộc PDF/MD/dictionary hash, reviewer, thời điểm, status và offsets NFC. Bundle v1 không tự ghép hash hoặc tự nâng cấp. Rule toàn cục được áp ở CPU sau khi document worker đã thoát; worker model không import keyword/reporting.

## 5. Excel và tổng sau duyệt

Sheet `Ma trận từ khóa` hiện có tiếp tục là literal. Khi bật global rules, ma trận bổ sung:

- `Dem_Tier2`: số occurrence đã chấp nhận, mỗi vị trí tối đa một lần.
- `Cho_duyet`: số occurrence còn Pending.
- `Tong_sau_duyet`: Tier1 + Tier2 chỉ khi Pending của ô bằng 0; còn Pending hoặc tài liệu lỗi thì để trống.
- `Trich_dan_chi_tiet`: occurrence literal.
- `Trich_dan_Tier2`: alias chấp nhận, vị trí, ngữ cảnh và nguồn rule/decision.

Đây là tổng sau quy trình duyệt cấu hình, không là chứng nhận accuracy trên PDF. Sheet và JSON ghi quality `NOT_EVALUATED`. Workbook mỗi tài liệu vẫn giữ hai sheet literal `Tong_hop`/`Trich_dan_chi_tiet`; companion và ma trận cung cấp phần tầng 2. Chuỗi dữ liệu được ghi literal, không thực thi như công thức Excel.

## 6. Lệnh trên Windows

Chạy OCR sản phẩm mới khi thật sự cần, qua pipeline chuẩn, CUDA và đủ trang. Với dictionary mặc định, CLI mặc định nạp rules cùng bản mã; dùng `--no-alias-rules` để tắt trong lượt mới. Dictionary tùy chỉnh cần chỉ định bộ rule tương thích.

Đổi rule trên extraction đã xác minh chỉ cần CPU, không gọi model:

```powershell
.venv/Scripts/python.exe run_batch.py --analysis-from output/<batch_nguon> --output output/<analysis_moi> --keywords-file config/keywords.txt --keyword-set-version v1 --alias-rules config/alias_rules.json
```

Hoặc dùng helper tương đương:

```powershell
.venv/Scripts/python.exe scripts/run_count_only.py output/<batch_nguon> --keywords-file config/keywords.txt --keyword-set-version v1 --alias-rules config/alias_rules.json --output output/<analysis_moi>
```

`--recount` tại batch cũ giữ nguyên snapshot, không dùng để đổi tri thức. `--alias-rules`/`--no-alias-rules` không được dùng để lặng lẽ đổi một lượt recount. Nguồn và output phải tách biệt.

Gói review có ảnh và cờ nghi vấn động theo dictionary:

```powershell
.venv/Scripts/python.exe run_batch.py --review-from output/<batch_nguon> --output scratch/<review_moi> --keywords-file config/keywords.txt --review-limit 100
```

Đọc ảnh nguồn, căn occurrence với Markdown rồi xuất bundle quyết định v2. Nạp bundle trong analysis mới bằng `--alias-decisions <bundle.json>`; không tự biến phiếu review chưa điền thành quyết định đã duyệt.

## 7. Vận hành Kaggle

Notebook chuẩn là **`kaggle/ocr_pdf_kaggle.ipynb`**. `ocr_pdf_v63_kaggle.ipynb` chỉ còn liên kết chuyển hướng. Detector theo registry hiện là **PP-OCRv4 ONNX**, recognizer VietOCR, cấu trúc Docling; không phải Surya Detection.

Tài nguyên phụ thuộc phiên/tài khoản. [Kaggle Notebooks](https://www.kaggle.com/docs/notebooks) nêu tối đa 12 giờ cho CPU/GPU và 20 GB output lưu ở `/kaggle/working`; luôn kiểm tra quota và tài nguyên thực được cấp trong giao diện. [Thông báo Kaggle](https://www.kaggle.com/product-announcements/735239) công bố ngừng P100 từ 15/09/2026. Không suy từ đó rằng mọi tài khoản luôn được T4 x2 hoặc có cùng lịch reset quota. Hai GPU không tạo một vùng VRAM chung; pipeline tuần tự một worker không tự dùng tổng bộ nhớ của hai card.

### Chuẩn bị đúng bản mã chưa phát hành

Không cần tự commit/push. Tạo gói source chỉ gồm mã/cấu hình/lock/font/registry, không chứa trọng số, PDF hoặc kết quả:

```powershell
.venv/Scripts/python.exe scripts/build_kaggle_source.py --output scratch/<source_moi>.zip
```

Lưu SHA-256 lệnh in ra, gắn ZIP này và dataset PDF vào Kaggle qua Add Input. Notebook kiểm manifest/hash và đường dẫn ZIP trước khi giải nén vào runtime riêng. Snapshot bị sửa thì không tái dùng.

Trong cell `parameters`, đặt đúng tên tham số đang có:

```python
SOURCE_ARCHIVE = "/kaggle/input/<source_dataset>/<source_moi>.zip"
SOURCE_ARCHIVE_SHA256 = "<sha256_do_lenh_build_in_ra>"
RUN_FULL_BATCH = True
FILE_LIMIT = None
RESUME = True
ASSETS = "none"
KEYWORD_SET_VERSION = "v1"
GLOBAL_ALIASES = True
ALIAS_RULES_FILE = None
PREVIOUS_RESULTS_DIR = None
```

Bật GPU và Internet khi notebook cần tải môi trường/model. Dùng Save Version → Save & Run All cho lượt chạy nền; không cam kết phiên không bị giới hạn tài nguyên. Notebook dùng Python supervisor 3.11, worker riêng theo lock, cùng profile `unified_gpu_full_ocr`. Không chuyển sang CPU OCR nếu GPU thiếu.

Rules/dictionary được khóa và lưu cùng kết quả. Trọng số, môi trường và cache trung gian ở runtime `/tmp`; output và diagnostics cần bàn giao nằm trong RESULTS_DIR. Notebook xác minh SQLite revision, receipt, ma trận, companion và queue trước khi ghi `verification.json`. ZIP tải về là `/kaggle/working/results.zip`, gồm queue trong thư mục documents, bản rules, từ điển, ma trận và log; không gói model/runtime vào ZIP. Dung lượng RESULTS_DIR và ZIP cùng chiếm quota lưu output; `ASSETS=none` không bảo đảm tự động mọi lô đều vừa 20 GB.

### Tiếp tục phiên sau

`RESUME=True` không phục hồi dữ liệu đã biến mất cùng container. Gắn toàn bộ output phiên trước đã giải nén và dataset PDF gốc, đặt `PREVIOUS_RESULTS_DIR` trỏ tới thư mục có `run_settings.json`, `selected_inputs.json`, `documents/batch_state.sqlite` và các artifact đi kèm. Restore sang RESULTS_DIR mới, không merge/ghi đè một thư mục đã có. Giữ cùng đường dẫn output/input, source archive/hash, runtime options và snapshot. Với nguồn Git, notebook khóa commit của phiên đã restore. Chỉ SQLite là không đủ để xác minh extraction.

Đổi rules trong cùng lô: tải kết quả về, dùng lệnh CPU analysis ở mục 6 với output mới. Tiếp tục giữ nguồn nguyên vẹn và đưa rules mới vào các lô mới. Không sửa snapshot/hash để ép resume chấp nhận bản khác.

## 8. Kiểm chứng và phần chưa nghiệm thu

Kiểm sát thay đổi: `tests/unit/keywords/test_global_alias_rules.py`, `tests/unit/test_global_alias_publication.py`, `tests/unit/test_kaggle_global_alias.py`, cùng các test analysis/publication/import/workbook hiện có. Hồi quy theo AGENTS:

```powershell
.venv/Scripts/python.exe scripts/run_pytest_scratch.py tests/unit tests/scientific tests/legacy_compat -q --capture=fd
```

Điều kiện phần mềm: literal bất biến; alias không trùng; occurrence revoke thắng rule; novel giữ Pending; thiếu/sai/mất rules fail closed; đổi rules cần output mới và không gọi OCR; Excel/queue/SQLite đọc kiểm cùng revision; gói nguồn và restore không thoát đường dẫn hoặc ghi đè dữ liệu.

Chạy notebook tại Kaggle thật, breadth 100–1.000 PDF, thời gian/chi phí/dung lượng và độ đúng trên GT độc lập là các phạm vi riêng. Test double, tổng test pass, local GPU hoặc 9 PDF diagnostic không thay cho các phép đo đó. Những phạm vi chưa có artifact tương ứng giữ `NOT_EVALUATED`; không ghi sẵn chữ ký người duyệt hoặc phát hành tuyên bố chất lượng.
