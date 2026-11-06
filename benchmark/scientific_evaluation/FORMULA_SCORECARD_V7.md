# Scorecard chẩn đoán công thức v7.0

`formula_scorecard.py` tổng hợp theo PDF, mã công ty trong danh mục và tầng `inline`/`display`. Chỉ truyền các file cặp, critical hoặc CDM thuộc đúng lần căn. Có thể chạy một phía để kiểm kê dữ liệu. Khi có hai đầu ra khác nhau cho cùng PDF và cùng tham chiếu, phép bootstrap lấy mẫu theo cụm công ty. Kết quả phục vụ development và giữ `acceptance_status: NOT_EVALUATED`.

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
.venv/Scripts/python.exe -B -m benchmark.scientific_evaluation.formula_scorecard `
  --sources scratch/dev_sessions/20261104-benchmark-source-inventory/sources.issuer-observed.csv `
  --candidate-alignment scratch/dev_sessions/20261104-formula-embedded/replay/alignment.json `
  --output scratch/formula-scorecard-moi.json
```

Khi alignment có cặp tham chiếu, thêm `--candidate-pairs <cdm-pairs.json>`. Thêm `--candidate-critical <file.json>` nếu đã có hồ sơ rà và `--candidate-cdm <thư mục output CDM>` nếu đã render. Bộ tổng hợp tính lại TEXT và critical từ file cặp và phiếu đã ghim. Với CDM, nó kiểm hash input, runtime, ID cặp, rồi tính lại F1 từ số ký tự và số khớp khai báo. Lượt này sử dụng kết quả render đã có. [Hướng dẫn TEXT/critical](FORMULA_CONTENT_V7.md) · [Hướng dẫn CDM](FORMULA_CDM_V7.md).

Có thể thêm bộ `--baseline-alignment`, `--baseline-pairs`, `--baseline-critical` và `--baseline-cdm`. Hai phía phải có cùng hash annotation, dữ liệu tham chiếu, phạm vi định vị và ngưỡng IoU. Completion của mỗi PDF phải khác nhau. Danh mục nguồn kiểm cùng `document_id`, PDF SHA-256 và tổng trang. Mã công ty `unknown` vẫn có tổng theo tài liệu và chặn CI cho nhóm có mã chưa xác minh. Không suy mã từ tên tệp.

Mặc định scope gồm tất cả trang trong alignment ứng viên. Nếu dùng scope nhỏ hơn, cung cấp `--sample` với schema `ocr-formula-scorecard-sample-v1` và danh sách `documents`. Mỗi mục gồm `document_id`, `pdf_sha256` và danh sách `pages` vật lý từ 1. Kết quả lưu SHA-256 mẫu. Scope development có thể tập trung vào trang đã chọn. Việc khóa mẫu holdout thuộc protocol nghiệm thu.

| Phép đo | Tử số | Mẫu số |
| --- | --- | --- |
| `formula_detection_recall` | TP | TP + FN |
| `formula_detection_errors_per_gt` | FP + FN | TP + FN |
| `formula_text_cer` | Tổng thay thế, chèn, xóa | Số ký tự TEXT tham chiếu |
| `formula_text_exact` | Số cặp TEXT khớp nguyên văn | Số cặp TEXT tham chiếu |
| `formula_cdm_mean` | Tổng F1 CDM trên từng biểu thức | Số biểu thức LaTeX tham chiếu |
| `formula_critical_error_rate` | Số công thức có ít nhất một lỗi critical | Số công thức được rà đủ bảy loại |

Scorecard giữ TP/FP/FN riêng theo PDF và công ty, cùng precision, recall, F1 khi mẫu số có nghĩa. Trang đã xác nhận âm tính có thể góp FP với mẫu số GT bằng 0. Trang chưa rà và cặp chưa chấm được xuất số lượng riêng. Micro, macro và CI của toàn cohort giữ trống nếu còn phần thiếu. Cặp khác dạng và MathML chưa đo được hiển thị trong coverage theo format. CDM, TEXT và critical giữ riêng. CI dùng engine `company_cluster_bootstrap`, với `--seed`, `--resamples`, `--confidence`, `--min-companies` được ghi trong báo cáo. CI cần đủ cụm có mẫu số dương; phân phối suy biến có trạng thái riêng.

Alignment holdout phải có đúng file mẫu và mọi trang trong mẫu đã gán nhãn. Khi có CDM holdout, scorecard kiểm hash từng artifact render, input thô, các input TeX và tính lại matching từ glyph. Hồ sơ critical cần khai báo người thật đã rà ảnh. Gate replay các nguồn này và ghép count vào họ so sánh toàn cục. [Chính sách trước holdout](FORMULA_ACCEPTANCE_POLICY_V7.md) · [Mẫu và họ kiểm định](FORMULA_FAMILY_V7.md).
