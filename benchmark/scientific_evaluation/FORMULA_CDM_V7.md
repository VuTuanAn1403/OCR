# Đo công thức bằng render trên CPU

`formula_cdm.py` nhận các cặp LaTeX đã xác định trước và ghi kết quả từng cặp. Phương pháp `unimernet-cdm-5a2c80d-pymupdf200-aa0-tol1-unicode-v2` dùng LuaLaTeX cho toàn bộ tập, kể cả ASCII, để một tham chiếu có cùng engine ở baseline và candidate. Bộ tách token, tô màu và đối sánh dựa trên nguồn UniMERNet đã ghim. PyMuPDF raster ở 200 dpi, tắt khử răng cưa và dùng dung sai một mức mỗi kênh RGB. [Bài báo CDM](https://arxiv.org/abs/2409.03643) · [Nguồn đã ghim](_vendor/unimernet_cdm/ATTRIBUTION.md).

LuaLaTeX dùng `unicode-math` và font Latin Modern. Adapter áp dụng NFC trên bản dùng để render, lưu nguyên byte nguồn và hash. Matcher quy đồng dấu âm Unicode với dấu âm LaTeX và một số lệnh Greek với ký tự toán tương ứng. Các biến thể Greek khác nhau, dấu tiếng Việt và ký tự `0`/`O` vẫn được phân biệt. Thiếu glyph trong font làm cặp `NOT_EVALUATED`. [unicode-math](https://ctan.org/pkg/unicode-math) · [Latin Modern](https://ctan.org/pkg/lm).

## Căn theo vị trí trên đầu ra công bố

Chạy `formula_alignment` bằng Python supervisor. Adapter đọc batch canonical đã acknowledge, xác minh danh tính PDF và receipt, rồi ràng buộc chính xác byte `extraction.json`. Mỗi annotation thuộc một PDF SHA-256 và một trang vật lý. Khung gồm `coordinate_space`, `transforms`, `width`, `height` và phải khớp extraction. [Lược đồ thao tác và phiếu nguồn](FORMULA_ALIGNMENT_V7.md).

`alignment.json` giữ cặp một-một, IoU, GT thiếu, prediction dư/trùng, ignore và các trang chưa gán nhãn. Khi có tham chiếu, `cdm-pairs.json` có một cặp cho mỗi biểu thức, kể cả prediction vắng. Dùng file này thay cho `--pairs` trong lệnh bên dưới và đối chiếu `input.json` của lượt CDM với SHA-256 trong `alignment.json`.

## Cài và chạy lại bộ mẫu phát triển

Dùng venv CPython 3.11 x64 riêng và lock có SHA-256. Phiên đã kiểm TinyTeX `v2026.11` portable và Node `v22.23.2`. Gói `upgreek` từ CTAN được build trong scratch vì TinyTeX-1 thiếu gói này. Hash bản tải TinyTeX, gói CTAN, file `.sty` và các bánh xe Python nằm trong hồ sơ phiên. [Lock Windows](../../requirements/v70/formula-eval-cp311-win_amd64.lock) · [TinyTeX](https://github.com/rstudio/tinytex-releases/releases/tag/v2026.11) · [upgreek](https://ctan.org/pkg/upgreek/).

Chạy từ thư mục gốc, với đúng đường dẫn binary TeX và Node đã xác minh. Ví dụ dùng môi trường portable đã chuẩn bị trong workspace này.

```powershell
scratch/tools/formula-v7/python/Scripts/python.exe -B -m benchmark.scientific_evaluation.formula_cdm `
  --pairs scratch/dev_sessions/20261104-formula-cdm-adapter/controlled-pairs.json `
  --output scratch/formula-run-moi `
  --node C:/nvm4w/nodejs/node.exe `
  --lualatex C:/kk_2/OCR_pdf/scratch/tools/formula-v7/TinyTeX/bin/windows/lualatex.exe
```

Dùng output mới ngoài thư mục công bố. JSON đầu vào là danh sách object có `id` duy nhất, `reference` và `prediction` là chuỗi, hoặc `prediction: null` khi thiếu. Có thể ghi `reference_format` và `prediction_format` là `LATEX`, `TEXT` hoặc `MATHML`. Adapter render LaTeX. TEXT và MathML được lưu nguyên dạng và đánh dấu chưa hỗ trợ. Quy trình hiện dành cho biểu thức được chọn và rà trước trong bộ phát triển. TeX nhận cờ tắt shell escape, dùng các tiến trình theo danh sách đối số và lưu log riêng.

`runtime.json` lưu hash executable, DLL, hai font được tìm bằng `kpsewhich` cùng thư mục LuaLaTeX, phiên bản gói Python và nguồn vendor. Mỗi lượt render lưu LaTeX gốc, bản tokenize, log, input TeX, font OpenType nhúng trong PDF theo log, ảnh và bbox. `comparison.json` ghi TP/FP/FN chưa làm tròn. Exit `0` khi mọi cặp có điểm, `1` khi còn cặp chưa chấm được. Dùng `--pdflatex` thay cho `--lualatex` để chạy phương pháp v1 phục vụ chẩn đoán lịch sử. Khi đổi phương pháp phải dùng output và hồ sơ runtime mới.

Đối chứng development trước đó cho thấy upstream dùng pdfLaTeX báo F1 bằng 1 dù mất hai glyph ở mỗi ca Greek và tiếng Việt. Phương pháp LuaLaTeX v2 chấm đủ 25 cặp đã ghim, định vị đủ glyph ở hai ca từng lỗi và giữ nguyên 23 F1 đã chấm được bằng v1. Kết quả áp dụng cho control tổng hợp. Hồ sơ duyệt đối chứng và chất lượng holdout vẫn chưa hoàn tất. [Đối chứng lịch sử](../../scratch/dev_sessions/20261105-formula-renderer-parity/comparison-summary.json) · [Lượt LuaLaTeX](../../scratch/dev_sessions/20261105-formula-unicode/session.md).

Trong phép đo holdout, `--expected-runtime` và `--expected-runtime-sha256` phải đi cùng nhau và trỏ runtime đã được duyệt trong protocol. Adapter quan sát runtime hiện tại rồi so các trường nhận dạng trước khi render. Đường dẫn executable và log probe cùng thời lượng probe được bỏ khỏi phép so. Các phiên bản, hash executable/DLL, mã adapter, nguồn vendor, giới hạn và cấu hình raster phải khớp. `verify_comparison` kiểm file cặp, runtime, từng artifact render, nguồn thô và input TeX còn nguyên hash rồi tính lại đối sánh từ glyph. [Replay với protocol khóa](FORMULA_HOLDOUT_REPLAY_V7.md).

## Diễn giải và điều kiện sử dụng cho nghiệm thu

- Nếu tham chiếu lỗi render, hoặc lỗi từ môi trường, giới hạn hay dạng prediction chưa được hỗ trợ, trạng thái cặp là `NOT_EVALUATED`. Một cặp chưa chấm được làm trung bình toàn cohort là `null`. Trung bình trên phần chấm được có trường riêng dùng để chẩn đoán.
- Khi tham chiếu render đủ, prediction thiếu hoặc lỗi cú pháp có điểm cặp 0 và toàn bộ ký tự tham chiếu tính FN. Với prediction lỗi cú pháp, số ký tự FP chưa xác định nên để `null`.
- Dấu mảnh có thể mất do raster hóa. Adapter trả lỗi evaluator nếu token đã tô màu còn thiếu bbox. Ca `x^{2}` so với `x_{2}` cho CDM 1 ở bộ mẫu, kèm cờ rà cấu trúc. `rendered_character_exact` chỉ mô tả kết quả đối sánh ký tự.
- Nghiệm thu v7.0 cần căn vị trí với PDF công bố, chấm detection và công thức dư, giữ cả inline và display, có nhãn A/B và phân xử theo ảnh. Cần xử lý biểu diễn thực tế, đo lỗi critical riêng và khóa phương pháp, ngưỡng, cỡ mẫu trước khi mở holdout. [Đặc tả phạm vi](../../Cai%20Tien/11_NGHIEM_THU_CONG_THUC_V70.md).
