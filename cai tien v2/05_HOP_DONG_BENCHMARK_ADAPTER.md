# Hợp đồng adapter Challenger và experiment

Tài liệu này là đặc tả cho V8-040, chưa phải mã. Phương pháp so sánh nằm ở [BENCHMARK_PLAN](../docs/quality_assurance/BENCHMARK_PLAN.md); ở đây chỉ khóa **chỗ đặt mã, identity và định dạng output**, để mọi challenger so được với baseline mà production không bị đụng tới.

## 1. Ranh giới không được vượt

| Quy tắc | Lý do kiểm được trong mã |
| --- | --- |
| Không thêm `.py` dưới `src/` cho challenger | `src/ocr_runtime/fingerprint.py::_source_entries` hash mọi `src/**/*.py`; thêm file sẽ đổi `extraction_fingerprint`, làm hỏng resume và receipt |
| Không sửa `config/profiles.yaml` hay thêm profile | `src/ocr_runtime/pipeline_policy.py::validate_profile` khóa VietOCR, CUDA và Docling; CLI chỉ nhận `unified_gpu_full_ocr` |
| Không sửa `models/v62/runtime-models.json` | `src/ocr_runtime/model_registry.py::validate_registry` hash từng file model |
| Không nâng `PIPELINE_VERSION` | `src/ocr_runtime/version.py::PIPELINE_VERSION` có mặt trong mọi stage closure; chỉ nâng ở PR tích hợp (V8-160) |
| Production không import challenger | Contract `benchmark` và `benchmark-direct` trong `pyproject.toml`; contract riêng cho challenger là V8-041 |
| Không cài dependency challenger vào `.venv` hay `.venv-v62/*` | Mỗi ứng viên dùng venv riêng `.venv-v8-<ứng viên>/`; phải thêm `/.venv-v8-*/` vào `.gitignore` trước khi tạo |

## 2. Bố cục thư mục (đợt sau)

```text
benchmark/challengers/
  README.md                 # đặc tả này ở dạng mã
  model_catalog.json        # licence, URL, revision, sha weights, VRAM (V8-043)
  <tầng>/<ứng viên>/        # adapter: chỉ đọc input, ghi output canonical
cai tien v2/bao_cao/        # BASELINE_LOCK_REPORT, scorecard, dossier (Markdown)
scratch/benchmarks/<experiment_id>/{manifests,predictions,scorecards,errors,logs}/
```

Không đặt tên thư mục con là `reports/`, `logs/`, `lib/`, `build/`, `dist/`: `.gitignore` bỏ qua các tên này ở mọi cấp.

## 3. Mã thí nghiệm và identity

`experiment_id = EXP-V8-<TẦNG>-<YYYYMMDD>-<NNN>`, ví dụ `EXP-V8-REC-20261120-001`. Mỗi run của baseline và candidate có `run_id` riêng. Manifest của experiment gồm:

| Nhóm | Trường |
| --- | --- |
| Mã | Commit, dirty diff sha, `code_fingerprints()` (extraction/analysis/publication) |
| Cấu hình | sha của `config/profiles.yaml`, của registry model, của lock tương ứng |
| Ứng viên | Repo, revision, sha weights, licence (code và weights), dictionary/tokenizer |
| Dữ liệu | sha manifest PDF, chọn trang, DPI, sha ảnh, split (development/calibration/holdout) |
| Protocol | sha protocol, phiên bản metric (`DSER_strict`, …), α, ngưỡng, margin |
| Môi trường | GPU, VRAM, driver, CUDA, backend, seed, lệnh chạy, exit code, xác nhận cây tiến trình đã thoát |

Thiếu bất kỳ trường bắt buộc nào thì kết quả là `INCONCLUSIVE` / `NOT_EVALUATED`.

## 4. Output canonical

**Bắt buộc với mọi dự đoán:**
- `document_id`, `physical_page`, `region_id`;
- `engine`, `model_version`, `run_id`;
- `text_raw`, `bbox` cùng `coordinate_space`, `source_image_sha256`;
- `confidence` nếu engine có cung cấp. Engine không có thì để `null` kèm lý do, không tự tạo.

**Theo tầng:**

| Tầng | Định dạng | Evaluator có sẵn |
| --- | --- | --- |
| Detection | `primary-text-detections-v1` (`src/ocr_contracts/text_detection.py::validate_snapshot`) | `benchmark/scientific_evaluation/text_detection_metric.py::evaluate_page` |
| Recognition (crop cố định) | Danh sách `{crop_id, crop_sha256, text_raw}` | `ocr_metric.py` (CER/WER/DER) |
| Layout | Region có class và bbox | `dla_metric.py`, `canonical_layout.py` |
| Reading order | Danh sách block ID có thứ tự | `reading_order_metric.py` |
| Bảng | Ô có row, col, span, địa chỉ, text_raw | `teds_metric.py`, `numeric_metric.py` |
| Keyword | Occurrence có locator | `keyword_acceptance.py::evaluate` |
| So cặp | Đếm `ocr-paired-counts-v1` | `benchmark/qa/paired_effects.py::summarize` |

Adapter **không** được:
- sửa extraction hay receipt của production;
- ghép record chỉ vì text giống nhau;
- bỏ unit thiếu dự đoán khỏi mẫu số.

Output VLM là dự đoán, không bao giờ là GT. Output VLM phải ánh xạ về bbox nguồn và đi qua numeric guard, ownership và review.

## 5. Quyết định

| Quyết định | Khi nào |
| --- | --- |
| PROMOTE (đề xuất) | Đủ GT/coverage/identity, cải thiện vượt margin đã khóa, harm trong giới hạn, E2E đạt |
| KEEP BASELINE | Không cải thiện, hoặc gây harm, hoặc làm yếu hợp đồng dữ liệu |
| REJECT | Không bảo toàn nguồn/số, hoặc không chạy được trong giới hạn vận hành |
| INCONCLUSIVE | Thiếu GT, identity, coverage, hoặc protocol chưa khóa |

Quyết định luôn do người duyệt. PROMOTE chỉ mở một PR tích hợp riêng, có kế hoạch rollback và output mới. Fix rate = fixed / baseline_wrong; harm rate = harmed / baseline_correct. Mẫu số bằng 0 thì rate là `null`, không phải 0.
