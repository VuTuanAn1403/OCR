# Đo lại công thức từ hai publication canonical

Người giữ tập chạy lệnh này sau khi đã khóa protocol có công thức, hoàn tất hồ sơ A/B/C và xác minh đối chứng renderer trên development. Lưu báo cáo dưới quyền truy cập của tập holdout vì cặp công thức chứa chữ thô và nhãn tham chiếu. [Hồ sơ A/B/C](../ground_truth_tools/FORMULA_HOLDOUT_V7.md) · [Preflight công thức](FORMULA_ACCEPTANCE_POLICY_V7.md).

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
.venv/Scripts/python.exe -B -m benchmark.scientific_evaluation.formula_holdout_replay `
  --protocol scratch/holdout/protocol.locked.yaml `
  --artifact-index scratch/holdout/artifact-index.yaml `
  --pdf-root scratch/holdout/pdf `
  --baseline-batch output/baseline_canonical `
  --candidate-batch output/candidate_canonical `
  --output scratch/holdout/formula-replay-001
```

Hai cờ batch nhận một hoặc nhiều thư mục của lượt OCR canonical đã công bố. Chương trình đọc lại ledger, workbook đã xác nhận, chứng cứ CUDA và thoát cây tiến trình. Mỗi PDF trong mẫu cần có đủ trang và một kết quả gốc riêng cho mỗi bên. Trước khi căn bbox, bộ đo kiểm lại SHA-256 của OCR receipt, `COMPLETED.json` và `extraction.json`. Lệnh chạy bằng CPU trên kết quả đã công bố.

Luồng `FORMULA_HOLDOUT_REPLAY` chạy đủ kiểm tra preflight, rồi dựng tham chiếu từ phiếu và seal đã ghim trong manifest phân xử. Cả hai bên dùng đúng các trang đã khóa và cùng ngưỡng IoU. Trang âm tính vẫn tính phát hiện thừa. Biểu thức tham chiếu bị bỏ sót vẫn nằm trong mẫu số, kể cả khi một phía thiếu dự đoán. Với tham chiếu TEXT, bộ đo tính các ký tự bị xóa theo chính sách chữ nhìn thấy. Trang ngoài mẫu không xuất hiện trong báo cáo căn và cặp công thức.

Mỗi bên có `alignment.json`, `cdm-pairs.json` và `formula-content.json` khi có cặp. Khi chưa nhận hồ sơ critical, công cụ tạo `critical-template.json` với quyết định `UNRESOLVED`, danh tính và khai báo để trống. Người rà đọc ảnh nguồn, điền mọi nhóm ký hiệu có lý do và nộp bản mới với `status: SUBMITTED`, `actor_type: HUMAN`, `source_images_checked: true`, `reviewer` và `reviewed_at` có múi giờ. Ghim đúng cặp và alignment. Chạy lại vào output mới với `--baseline-critical` và `--candidate-critical` trỏ hai bản nộp. Công cụ đối chiếu hash, giữ ca chưa phân xử và tính số công thức có lỗi.

Để chạy CDM, thêm cùng lúc `--formula-python`, `--node`, `--lualatex` bằng đường dẫn executable tuyệt đối. Dùng interpreter trong môi trường CPU riêng và khóa `runtime.formula_renderer_manifest_sha256` của protocol theo phương pháp Unicode v2. Supervisor kiểm hash executable. Tiến trình CDM quan sát lại phiên bản, công cụ, DLL, gói Python và hash hai font Latin Modern rồi so với runtime khóa. Đường dẫn và thời lượng probe có thể đổi. Nội dung nhận dạng còn lại phải khớp trước khi render. CDM có log và `cdm-process.json` riêng cho từng phía. [Công cụ CPU](FORMULA_CDM_V7.md).

Scorecard đọc lại hash artifact, chữ thô, glyph và các file TeX đã sử dụng, rồi chạy lại đối sánh ký tự. Mọi CDM holdout phải có bằng chứng render đủ để kiểm lại, kể cả các cặp render lỗi. TEXT và MathML còn nằm trong báo cáo với phạm vi hỗ trợ đã khai báo. Điểm CDM chỉ đo cohort tham chiếu LaTeX và trạng thái được tính từ độ phủ cohort đó. Hồ sơ critical có thể có kết quả độc lập với điểm CDM.

Dùng `--baseline-cdm` và `--candidate-cdm` khi cần kiểm lại hai kết quả render đã hoàn tất. Cung cấp cả hai cờ để giữ bộ renderer evidence của lượt đã duyệt. Bộ đo kiểm process/log và tất cả hash, ràng buộc lại với cặp vừa dựng rồi tính lại matching. Output replay vẫn là thư mục mới. Cách này giữ các bằng chứng render có thời điểm và log gốc cho bước ký quyết định phát hành.

`scorecard.json` báo số đếm, mẫu số và thống kê theo công ty. Nếu dùng CLI `formula_scorecard` trực tiếp, truyền đúng `--sample` và file cặp của mỗi bên. `replay.json` xuất sau khi đủ hai bên và scorecard, ghi hash đầu vào/đầu ra. Nếu lệnh dừng giữa chừng, chọn thư mục mới. Runtime nhận dạng executable, DLL, phiên bản gói và mã adapter. Bằng chứng từng lượt render ghi các input TeX đã dùng.

Thêm `--scorecard-sample` để xuất count công thức theo mẫu chung đã khóa. Cổng phát hành dùng lại replay để ghép count và kiểm toàn họ thống kê. [Đơn vị mẫu và lệnh gate](FORMULA_FAMILY_V7.md).

Chế độ này đo dự đoán công thức tự động. Span nhúng cần quy trình rà riêng trước khi được tính vào nội dung holdout. Nghiệm thu tổng vẫn `NOT_EVALUATED` khi thiếu dữ liệu, độ chính xác hoặc điều kiện phát hành theo protocol.
