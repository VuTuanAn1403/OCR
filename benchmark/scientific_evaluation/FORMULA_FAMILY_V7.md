# Công thức trong mẫu và họ kiểm định chung

Người giữ tập chuẩn bị đơn vị công thức trong file `ocr-holdout-scorecard-sample-v1` trước khi khóa protocol. SHA-256 của file này nằm ở `sample_sha256` của `ocr-sample-precision-plan-v1`. Mẫu trang công thức riêng `ocr-formula-scorecard-sample-v1` tiếp tục được ghim trong protocol. Bộ đo đối chiếu hai mẫu với nhãn A/B/C đã phân xử và hai publication canonical.

## Đơn vị trong mẫu chung

Mỗi đơn vị có `unit_id` duy nhất, `document_id`, `pdf_sha256`, `page`, `region_id`, `strata`, `metrics`. Giữ đúng PDF và trang vật lý của mẫu công thức. Tập trang và công thức phải khớp đầy đủ với tham chiếu đã phân xử.

- Mỗi trang đã chọn có một đơn vị `region_id: page`, chứa `formula_detection_errors_per_gt`. Với trang âm tính, thêm `formula_detection_recall` vào cùng đơn vị. Trang dương tính lấy recall từ từng công thức bên dưới. Các metric toàn trang khác như `cer` có thể nằm trong cùng đơn vị trang.
- Mỗi công thức GT có đơn vị `region_id` bằng `formula:` nối ID tham chiếu, ví dụ `formula:eq-01`. Metric bắt buộc gồm `formula_detection_recall` và `formula_critical_error_rate`. Công thức TEXT thêm `formula_text_cer`, `formula_text_exact`. Công thức LATEX thêm `formula_cdm_mean`.
- `strata` của công thức chứa đúng placement từ GT, gồm một trong `inline` hoặc `display`. Đơn vị trang giữ các nhóm thuộc tính trang đã duyệt, tách khỏi hai tên placement này. Các nhóm bổ sung phải thuộc protocol đã khóa.

MathML chưa có bộ đo nội dung được hỗ trợ. Bộ đo ghi danh sách tham chiếu dạng này và giữ cổng chất lượng chưa đánh giá. Khi bỏ một đơn vị, thêm metric recall toàn trang dương tính làm trùng mẫu số, gán sai placement hoặc thay PDF, bộ chiếu từ chối cả khi file mẫu đã được ghim lại hash.

Recall cộng TP trên các công thức GT, mỗi công thức có mẫu số 1. Đơn vị trang âm tính có recall 0/0. Lỗi phát hiện cộng FP + FN theo trang, chia tổng GT. Vì vậy FP trên trang âm tính vẫn góp vào tổng. Prediction vắng giữ trong count, với trạng thái `MISSING_OUTPUT` ở recall, TEXT hoặc CDM khi có phép đo phù hợp. Hồ sơ critical chưa hoàn tất và render chưa hỗ trợ giữ `NOT_EVALUATED`.

## Xuất count từ replay

Thêm `--scorecard-sample <file mẫu chung>` vào `formula_holdout_replay`. File phải khớp hash đã khóa trong kế hoạch precision. Replay sinh `global-counts-baseline.json` và `global-counts-candidate.json`, ghim chúng trong `replay.json`. Chỉ số công thức của hai bên được dựng từ cùng mẫu và nhãn. [Cách chạy replay và runtime CPU](FORMULA_HOLDOUT_REPLAY_V7.md).

## Cổng chất lượng v7.0

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
.venv/Scripts/python.exe -B -m benchmark.scientific_evaluation.release_gate `
  --protocol scratch/holdout/protocol.locked.yaml `
  --artifact-index scratch/holdout/artifact-index.yaml `
  --sample scratch/holdout/scorecard-sample.json `
  --prediction-inventory scratch/holdout/paired-predictions.json `
  --formula-pdf-root scratch/holdout/pdf `
  --formula-output scratch/holdout/formula-final-001 `
  --formula-python C:/kk_2/OCR_pdf/scratch/tools/formula-v7/python/Scripts/python.exe `
  --node C:/nvm4w/nodejs/node.exe `
  --lualatex C:/kk_2/OCR_pdf/scratch/tools/formula-v7/TinyTeX/bin/windows/lualatex.exe `
  --baseline-critical scratch/holdout/baseline-critical.json `
  --candidate-critical scratch/holdout/candidate-critical.json `
  --report scratch/holdout/gate-001.json
```

Gate thực hiện replay mới từ các batch trong prediction inventory. Gate đối chiếu protocol, PDF và completion của các cặp, rồi ghép count công thức với chữ, số, bảng và bố cục. Công cụ gọi scorecard chung một lần cho toàn họ so sánh đã khóa. Bootstrap đi theo cụm công ty. Holm dùng toàn họ, giữ phép đo chưa đánh giá với p dùng hiệu chỉnh bằng 1.

Khi duyệt báo cáo đã đo, truyền `--baseline-cdm` và `--candidate-cdm` trỏ hai thư mục render của lượt đó, cùng các cờ critical đã dùng. Hai cờ cache là đầu vào renderer của lần kiểm lại này. Bộ đo kiểm completion của subprocess, hash log, runtime đã khóa, input TeX, chữ thô và các artifact trước khi tính lại matching. Nhãn, publication và count toàn họ vẫn được dựng lại. Giữ protocol, source và các bằng chứng đã ký để `evidence_sha256` của quyết định độc lập khớp báo cáo. Nếu dùng một lượt render mới, người duyệt cần duyệt digest của lượt mới.

`formula-output` cần là thư mục mới, nằm ngoài batch/PDF. File report của gate nằm ngoài thư mục replay. Phiếu critical của lượt chuẩn bị phải khớp các file alignment/cặp được dựng lại. Manifest mã evaluator cần ghim cả các module công thức, nhận nhãn và kiểm split mà gate liệt kê. Dùng output mới khi danh tính thay đổi.

Thiếu mẫu, GT, CDM, hồ sơ critical, cỡ mẫu hoặc CI hợp lệ vẫn làm các phép đo chưa đánh giá. Trạng thái `INPUTS_VERIFIED` chỉ xác nhận hồ sơ trước đo. Phát hành còn cần các cổng review/vận hành và quyết định độc lập theo protocol. [Chính sách công thức](FORMULA_ACCEPTANCE_POLICY_V7.md) · [Phạm vi v7.0](../../cai%20tien%20v2/09_LUU_TRU_CAI_TIEN_V7.md#ct-11).
