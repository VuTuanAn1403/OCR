# Bằng chứng khắc phục V6.1

`remediation_20261014.json` ghi revision gốc, fingerprint bản mã đang sửa, hash file/config/model, môi trường và trạng thái KP-01..14. Các status chỉ có ý nghĩa theo `verification_scope`; fixture không chứng minh chất lượng trên GT thật.

- `20261014/pytest.txt`: full suite 462 passed, 3 skipped, 1 warning.
- `20261014/runtime_verification.json`: tuần tự/pool 2 worker/resume, 3 PDF synthetic × 2 trang; 15 artifact giống hệt byte.
- `20261014/wheel_verification.json`: wheel 6.1.0 cài không deps vào venv scratch; dùng dependencies đã có qua PYTHONPATH. Các import/profile/worker lấy từ wheel, các command chạy ngoài checkout. Đây không phải cài mới toàn bộ dependency stack hoặc thử GPU.
- `20261014/source_inventory.json`: 10 PDF hiện có, toàn bộ company metadata chưa được người xác minh; GT/splits chưa khóa.
- `references.json`: nguồn chính thức đã đối chiếu bằng plugin Firecrawl cho COCO/paired bootstrap/Holm/chữ ẩn.

Sổ cũ `benchmark/research_v1/claim_evidence.csv` được tham chiếu bằng hash, giữ nguyên và đánh dấu `LEGACY_UNVERIFIED`. Các dòng cũ chứa `synthetic_gt_hash`, `pred_hash`, `git_head_v5` không được nâng thành bằng chứng V6.1. Không suy ra CER/WER/TEDS từ confidence, quality score, số tests hoặc smoke.

Smoke bổ sung Docling qua hai tài liệu chưa được thực thi: automatic approval review không hoàn tất vì hạn mức tài khoản. Script chuẩn bị tại `scratch/verify_v6_docling_lifetime.py`; unit tests kiểm ownership/invalidation đã qua, nhưng chưa thay thế phép smoke thực.

`docs/` và `scratch/` tiếp tục bị ignore theo chính sách hiện tại; các bản ghi trong thư mục này có thể được version hóa cùng mã nguồn. Không có commit/PR được tạo trong đợt này.

## Bổ sung 15/10/2026

`remediation_20261015_addendum.json` bổ sung bằng chứng sau sổ 14/10, không sửa các record cũ; fingerprint mã `95cace67366d4be0`, working tree vẫn chưa commit.

- `20261014/docling_lifetime_verification.json`: smoke Docling thực qua hai tài liệu đã **chạy và PASS** (cùng một worker, mỗi tài liệu 1 bảng + 1 công thức, đóng worker khi kết thúc). Thay cho trạng thái `NOT_EXECUTED_REVIEW_FAILURE` ở sổ 14/10; chỉ chứng minh vòng đời worker, không phải chất lượng hay PERF.
- `20261015/pytest.txt`: full suite 510 passed, 3 skipped, 1 warning.
- `20261015/financial_checks_real_probe.json`: kiểm số học flag-only trên trang native thật của AGR/ADP; không có VIOLATION sai được quan sát, không có GT.
- `20261015/matrix_exploratory_summary.json`: chạy thử runner ma trận 9.4 trên một trang ADP; đủ 9 slot hiển thị, 24 so sánh đều `NOT_EVALUATED` vì chưa có GT. Thời gian không dùng làm bằng chứng PERF.

## Hoàn thiện tiếp 15/10/2026

`remediation_20261015_continuation.json` ghi compact export, text-overlay fallback và sửa phép thử bảng scan, cùng hash riêng từng phép chạy. Bằng chứng trong `20261015_continuation/`: full suite cuối **601 passed, 3 skipped**, compact sequential/pool/resume (3 PDF native, 6 trang, giảm 37,88% payload), perf CLI compact exploratory, A replay trên OCR evidence BSI đã khóa (2.935 từ round-trip đúng trên 5 trang; vẫn cần review ô bảng). A/B giữ hai fingerprint vì bước chèn chữ được sửa sau B; chưa có GT/C, không tuyên bố phương án thắng hoặc đạt PERF.

CI Windows/Linux đã sửa để cài `.[test]`; chưa có run GitHub Actions, Docker, GPU hay Colab mới. Chi tiết cục bộ tại `docs/V6_BO_SUNG_20261015.md`; docs tiếp tục bị ignore.
