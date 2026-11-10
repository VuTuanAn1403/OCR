# Challenger adapters (v8)

Mã của hợp đồng [05](../../cai%20tien%20v2/05_HOP_DONG_BENCHMARK_ADAPTER.md) (V8-040). Mọi tầng production là **Baseline**; model mới là **Challenger** và chỉ sống ở đây.

## Ranh giới

- Production (`src/`, mọi gói `ocr_*`) **không** import `benchmark.challengers`. Contract `challengers` trong `pyproject.toml` kiểm việc này, kể cả import gián tiếp (V8-041).
- Không thêm `.py` dưới `src/` cho challenger: file đó vào OCR identity (`src/ocr_runtime/fingerprint.py::_source_entries`).
- Mỗi ứng viên có venv riêng `.venv-v8-<ứng viên>/` (đã bỏ qua trong `.gitignore`). Không cài vào `.venv` hay `.venv-v62/*`.
- Adapter chỉ đọc input và ghi output canonical. Adapter không sửa extraction hay receipt production, không ghép record theo text giống nhau, không bỏ unit thiếu dự đoán khỏi mẫu số.

## Mô-đun

| Mô-đun | Việc |
| --- | --- |
| `experiment.py` | `experiment_id = EXP-V8-<TẦNG>-<YYYYMMDD>-<NNN>`; kiểm manifest identity (§3) và cặp baseline/candidate; liệt kê quyết định được phép; tạo `scratch/benchmarks/<experiment_id>/{manifests,predictions,scorecards,errors,logs}/` |
| `canonical.py` | Kiểm bản ghi dự đoán canonical (§4): `text_raw`, `bbox` + `coordinate_space`, `source_image_sha256`, `confidence` hoặc `null` kèm lý do; `MISSING_OUTPUT` vẫn là bản ghi |
| `catalog.py`, `model_catalog.json` | Catalog ứng viên (V8-043): licence code/weights, URL, revision, sha weights, VRAM. `download_allowed` chỉ mở khi licence `VERIFIED`, revision đã ghim và có sha256 weights; licence copyleft/phi thương mại/có điều kiện cần thêm `licence_review` |
| `reading_order_rules.py` | Thứ tự đọc rule-based theo 8 quy tắc R-RO của đặc tả 11 (V8-071), chỉ dùng thư viện chuẩn và tất định; chạy và so với production bằng `scripts/run_reading_order_challenger.py` |
| `acronym_diacritics.py` | Khôi phục Đ trong từ viết tắt in hoa có trong danh sách (HĐQT, BĐH, ĐHĐCĐ…), không sửa chuỗi gốc. Đo fix/harm bằng `scripts/run_acronym_challenger.py` (V8-030) |
| `vlm/` | VLM fallback (V8-090): `selection.py` chỉ chọn trang có chẩn đoán, `adapter.py` ghi bản ghi `page_text` canonical có `review_required`, `backends.py` chỉ mở model cục bộ khi catalog cho phép và sha weights khớp; CLI `scripts/run_vlm_challenger.py` |

Thiếu bất kỳ trường identity nào thì manifest là `INCONCLUSIVE`, và quyết định duy nhất được phép là `INCONCLUSIVE`. Không có protocol LOCKED hoặc GT độc lập cũng vậy. Fix/harm tính bằng `benchmark/qa/paired_effects.py::summarize`; mẫu số 0 cho rate `null`.

## Chưa có

- Revision, sha weights và VRAM đo được của từng ứng viên: ghi khi chọn ứng viên cho một pha. Từ 10/11/2026 có 1/8 ứng viên được phép tải: `vintern-1b-v3.5`, ghim theo yêu cầu của người dùng (xem [`vlm/README.md`](vlm/README.md)); VRAM của nó chưa đo.
- Adapter cho từng tầng `<tầng>/<ứng viên>/`: từ P3 trở đi, sau khi P1 khóa GT và protocol. Đã có thứ tự đọc rule-based và VLM với mã suy luận cho Vintern-1B-v3.5; model này chưa chạy lần nào.

Chất lượng: `NOT_EVALUATED`.
