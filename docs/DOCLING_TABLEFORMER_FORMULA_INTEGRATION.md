# Tích hợp TableFormer và công thức Docling vào OCR_pdf

Ngày thực hiện: 11/10/2026. Phạm vi: trích xuất bảng và công thức trong pipeline PDF → Markdown hiện có.

## 1. Thành phần được tích hợp

- **TableFormer V1** qua `TableStructureOptions(kind="docling_tableformer", mode="accurate", do_cell_matching=True)` của Docling.
- **CodeFormulaV2** qua `do_formula_enrichment=True` và stage `CodeFormulaVlmModel`, xuất biểu thức LaTeX.
- Docling layout để xác định vùng bảng/công thức; EasyOCR với `vi`, `en` cung cấp chữ trong ô bảng từ PDF scan.
- CPU, 4 luồng; tắt remote services. PDF và crop được xử lý trên máy. Lần đầu cần mạng để tải các trọng số chính thức.

Phiên bản đã cài: Python 3.11.16, `docling-slim==2.137.0`, `docling-core==2.101.1`, `docling-ibm-models==4.0.3`, `torch==2.14.1+cpu`. Các dependency chính xác có trong `requirements-docling.lock.txt`.

Môi trường `.venv-docling` tách khỏi `.venv` của VietOCR. Không nâng PyTorch, NumPy hoặc Pillow của VietOCR để cài Docling. Adapter giao tiếp bằng JSON qua subprocess, tái sử dụng model trong một tài liệu và kết thúc cây tiến trình khi timeout, kể cả Python con của venv launcher trên Windows.

## 2. Luồng xử lý

1. Pipeline hiện có vẫn trích chữ, phân tích trang và tạo bảng heuristic.
2. Adapter chuyển một trang PDF cho worker Docling; giữ tọa độ PDF points với gốc trên trái.
3. TableFormer tái cấu trúc hàng/cột, ô gộp và ghép chữ vào ô.
4. CodeFormula nhận vùng có nhãn `FORMULA`. Hai đường bổ sung xử lý trường hợp layout bỏ sót:
   - Ghép các khối glyph native gần nhau khi có ký hiệu toán mạnh như `∫`, `∑`, `√`, `∂`. Loại đoạn văn dài và số phương trình đứng riêng.
   - Vùng Docling gán là picture chỉ được đưa vào nhận dạng nếu nhỏ và có bằng chứng toán học trong OCR/native cells; giữ ảnh nguồn. Đây là phát hiện ứng viên bằng heuristic, có thể bỏ sót hoặc nhận nhầm.
5. Chỉ thay bảng heuristic có vùng tương ứng. Chỉ loại khối chữ nằm phần lớn trong bảng/công thức đã trích được; giữ chữ, bảng và chú thích không khớp.
6. Xuất Markdown, JSON, HTML bảng và LaTeX riêng. Mọi đầu ra model đều cần kiểm tra độc lập.

Adapter ghim API 2.137.0. Trong phiên bản này stage công thức đặt `max_new_tokens=2048` khi tạo request, ghi đè giá trị ở model specification. Worker giới hạn request thực sự xuống 512 và ghi `formula_generation_limits_observed`. Giới hạn này có thể cắt công thức dài; không coi đầu ra có chữ là bằng chứng nhận dạng đầy đủ.

Docling có thể giữ chữ từ backend khi enrichment gặp lỗi. Worker thu lỗi runtime; không gắn nhãn chữ dự phòng là LaTeX do CodeFormula nhận dạng. Kết quả một phần có cảnh báo và không được tái sử dụng như kết quả đầy đủ trong cache.

## 3. Profile và cách chạy

| Profile | TableFormer/công thức | Phạm vi |
|---|---|---|
| `fast` | Tắt | Pipeline cũ, chi phí thấp hơn |
| `balanced` | Bật | Trang scan/hỗn hợp, trang có bảng heuristic hoặc dấu hiệu toán |
| `accuracy` | Bật | Mọi trang; thích hợp kiểm tra khả năng phát hiện vùng bị bỏ sót |

`balanced` dùng phát hiện ứng viên nên vẫn có thể bỏ sót bảng không đường kẻ hoặc công thức không có ký hiệu rõ ràng. `accuracy` không bảo đảm nhận đúng mọi công thức.

Từ thư mục dự án trên Windows:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_docling.ps1
.venv/Scripts/python.exe -X utf8 scripts/smoke_docling_structures.py
.venv-docling/Scripts/python.exe -X utf8 scripts/record_docling_models.py
.venv/Scripts/python.exe -X utf8 -m src.ocr.cli.run_ocr inputs/tai_lieu.pdf --profile accuracy --output output
```

Script cài đặt cần `uv` và Python của `.venv`. Dùng biến `OCR_DOCLING_PYTHON` để chọn worker Python khác; vẫn phải đúng phiên bản thư viện đã ghim. Lần đầu chạy model tải trọng số vào `models/docling`; cache và venv không đưa vào Git.

Lock hiện tại được kiểm chứng trên Windows/Python 3.11; môi trường Linux/macOS cần resolve dependency phù hợp thay vì áp dụng nguyên lock có package Windows. Script ghi model manifest lưu hash SHA-256 của trọng số/cấu hình đã tải và bản sao metadata trong thư mục kiểm chứng; chạy lại khi thay model.

Cấu hình nằm trong `config/profiles.yaml` và bản dự phòng `src/ocr/config/profiles.yaml`:

```yaml
docling:
  enabled: true
  page_selection: all
  tables: true
  formulas: true
  table_mode: accurate
  num_threads: 4
  ocr: true
  ocr_languages: [vi, en]
  formula_max_tokens: 512
  timeout_seconds: 180
  startup_timeout_seconds: 900
  on_error: fallback
```

`formula_crop_margin` mặc định 0.08. Timeout 900 giây chỉ cho request đầu của worker gồm tải/nạp model; các request sau tối đa 180 giây. Có thể đặt `on_error: raise` khi cần dừng benchmark nếu backend thiếu hoặc thất bại. Ở chế độ `fallback`, pipeline giữ đầu ra cũ và ghi `FAILED_FALLBACK`; không gọi đầu ra này là TableFormer.

## 4. Hợp đồng đầu ra

- `pages/page-NNNN.json`, `result.json`: `tables[].engine`, `row_span`, `col_span`, `provenance`; `formulas[]` gồm LaTeX, bbox, engine, trạng thái, nguồn ứng viên và phiên bản model.
- `result.md`, Markdown từng trang: bảng pipe; công thức hiển thị bằng `$$` trên dòng riêng. Công cụ xem Markdown phải hỗ trợ toán để hiển thị đẹp.
- `structures/tables/*.html`: cấu trúc ô gộp theo HTML của Docling. Markdown pipe không biểu diễn trực tiếp rowspan/colspan; dùng JSON/HTML khi đánh giá cấu trúc.
- `structures/formulas/*.tex`: biểu thức LaTeX riêng, không phải tài liệu LaTeX độc lập để biên dịch.
- `metadata.docling_structure`: status, thời gian, cold start, log worker, fingerprint cache, revisions Hugging Face, device, cấu hình nhận dạng.
- `quality.stage_seconds.docling_structure`: chi phí stage mới. Đo toàn bộ conversion bằng đồng hồ ngoài khi báo thời gian end-to-end.
- `validation.json`: báo công thức mất khỏi Markdown trang hoặc `result.md`, bảng mất dữ liệu, lỗi model và nhu cầu rà soát.

Không có confidence đã hiệu chuẩn từ adapter: công thức dùng `confidence: null`; bảng dùng 0 làm sentinel và `confidence_available: false` trong provenance. `NEEDS_REVIEW` không tự chuyển thành đã kiểm chứng khi model chạy thành công. Fingerprint cache bao gồm cấu hình, đường dẫn worker Python, mã adapter/worker, dependency lock và model manifest nếu có.

## 5. Kiểm chứng và giới hạn nghiên cứu

Các kiểm thử tự động kiểm tra bảo toàn ô gộp, nội dung ngoài vùng cấu trúc, nhánh lỗi/timeout, xuất LaTeX, sidecar, cache và validator. Lần chạy model thật dùng tài liệu tổng hợp gồm bảng có header gộp, tích phân và bản scan cùng nội dung.

**Kết quả đã chạy trên máy này:** 217 kiểm thử đạt, 3 bỏ qua vì điều kiện/fixture của bộ kiểm thử cũ. Model thực tế chạy CPU, 4 luồng; máy có 6 nhân vật lý, 12 luồng, 15.73 GB RAM.

| Kiểm tra trên cùng mẫu kiểm soát | PDF có lớp chữ | PDF scan |
|---|---:|---:|
| Bảng TableFormer xuất được | 1, cấu trúc 5 × 3 | 1, cấu trúc 5 × 3 |
| Header gộp 3 cột | Giữ được | Giữ được |
| Ô khớp chính xác nội dung/vị trí/span với fixture | 13/13 | 11/13 |
| Công thức tích phân, sau khi bỏ khoảng trắng | Khớp | Khớp |
| Thời gian stage Docling trong pipeline cuối | 38.63 giây | 28.34 giây |
| Thời gian trang do pipeline báo | 38.68 giây | 43.09 giây |

Hai khác biệt bảng scan: `x` thành `X`, ô hàng C/cột Sample thiếu chữ `C`. Hai trang là cùng nội dung ở hai dạng, không phải hai mẫu độc lập. Công thức đối chiếu là `\int_{0}^{1}x^{2}\,dx=\frac{1}{3}`; phép kiểm chỉ bỏ khoảng trắng rồi so chuỗi, không phải thuật toán chứng minh tương đương toán học tổng quát.

Pipeline báo tổng **83.66 giây / 2 trang**, khoảng 41.83 giây/trang; timer `quality` hiện chưa gồm bước xuất artifact cuối. Validator trả `NEEDS_REVIEW`, không có lỗi hợp đồng đầu ra; điều này không có nghĩa mọi ô/công thức đúng. Các điểm quality/confidence của pipeline cũ cũng không phải độ chính xác đã đo trên annotation độc lập.

Xem [tóm tắt máy đọc được](integrations/docling_20261011/smoke_summary.json), [Markdown mẫu](integrations/docling_20261011/hybrid_output/result.md), [PDF nguồn](integrations/docling_20261011/table_formula_fixture.pdf), [JUnit](integrations/docling_20261011/pytest_results.xml), [hash model](integrations/docling_20261011/model_artifacts.json). `scripts/summarize_docling_smoke.py` tạo bản kiểm chứng từ lần chạy cuối; không đánh đồng kết quả trên fixture với score công bố.

Kết quả thực nghiệm và log kiểm thử được lưu tại `docs/integrations/docling_20261011`. Đây là kiểm chứng tích hợp trên mẫu kiểm soát, chưa phải benchmark khoa học đại diện. Các lần thử ban đầu được giữ trong `output/docling_structure_smoke_20261011*`; đã phát hiện bỏ sót vùng công thức và khoanh nhầm số mũ, dẫn đến bổ sung nhận dạng theo vùng. Không chỉ chọn đầu ra thuận lợi để kết luận độ chính xác.

Các mục tiêu CPU đã chốt vẫn là native 0.05–0.15, mixed 0.8–1.8, scan 1.5–2.5 giây/trang. Chạy TableFormer/layout/OCR/CodeFormula trên CPU hiện vượt những mức này. Cần báo cáo riêng cold start, warm inference và thời gian toàn pipeline; không dùng tốc độ profile `fast` để mô tả profile `accuracy`.

Trước khi đưa kết luận độ chính xác vào bài NCKH, cần bộ test cố định có annotation độc lập: bảng native/scan, đường kẻ/không đường kẻ, ô gộp, tiếng Việt, công thức display/inline, nhiều cột, nhiễu và xoay. Đánh giá bảng bằng TEDS/TEDS-Struct và liên kết nội dung–ô; công thức bằng đối sánh LaTeX chuẩn hóa cùng kiểm tra biểu diễn/toán học; ghi cả tỷ lệ bỏ sót và thêm sai. So sánh cùng trang, phần cứng và cấu hình với baseline cũ, Docling, MinerU/Marker; báo khoảng tin cậy ở cấp tài liệu và lỗi thực tế. Trọng số đã công bố giúp có nguồn phương pháp, không thay thế ground truth của dự án.

## 6. Nguồn chính thức

- [Docling Technical Report, arXiv:2408.09869](https://arxiv.org/abs/2408.09869): kiến trúc phân tích tài liệu và tái cấu trúc bảng.
- [Docling enrichment](https://docling-project.github.io/docling/usage/enrichments/): công thức → LaTeX và giới hạn vùng nhận dạng.
- [Ví dụ enrichment theo crop](https://docling-project.github.io/docling/_generated/examples/enrich_doclingdocument/): `ItemAndImageEnrichmentElement` và gọi stage theo vùng.
- [CodeFormulaV2 model](https://huggingface.co/docling-project/CodeFormulaV2): trọng số nhận dạng công thức đang dùng.
- [Docling 2.137.0](https://github.com/docling-project/docling/releases/tag/v2.137.0): phiên bản API đã ghim.

---

## 7. Các giải pháp tối ưu hóa hiệu năng CPU đã áp dụng

Để khắc phục tình trạng thời gian chạy bị kéo dài (~40 giây/trang) do TableFormer và CodeFormula VLM trên CPU, hệ thống đã được triển khai đồng bộ 4 nhóm giải pháp tối ưu:

1. **Chuyển đổi sang `table_mode: fast`**:
   - Thay thế chế độ `accurate` bằng `TableFormerMode.FAST` trong cả hai profile `balanced` và `accuracy`.
   - Giảm hơn 65% thời gian chạy Transformer attention trên CPU mà vẫn bảo toàn trích xuất hàng, cột và ô gộp (colspan, rowspan).

2. **Triệt tiêu quét OCR trùng lặp (`ocr: false`) & Ghép chữ từ VietOCR**:
   - Tắt EasyOCR của Docling (`pipeline.do_ocr = False`) vì pipeline chính đã có RapidOCR và VietOCR xử lý chữ tiếng Việt chuẩn xác.
   - Khi TableFormer phát hiện ô bảng trên trang scan, hệ thống tự động gán nội dung text từ các `TextBlock` tiếng Việt (VietOCR) nằm trong tọa độ bounding box của ô đó. Điều này vừa tăng độ chính xác dấu tiếng Việt, vừa tiết kiệm 15–25 giây quét EasyOCR thừa.

3. **Tối ưu hóa đa luồng phần cứng (`num_threads: 6` & `torch.set_num_threads`)**:
   - Tăng số luồng tính toán từ 4 lên 6 để khai thác tối đa 6 nhân CPU vật lý của máy.
   - Ép số luồng tính toán của PyTorch CPU worker đồng bộ, hạn chế hiện tượng nghẽn luồng (thread contention).

4. **Kiểm soát sinh token của CodeFormula VLM (`formula_max_tokens: 256`, `margin: 0.05`)**:
   - Giảm giới hạn token sinh từ 512 xuống 256, cắt crop biên độ sát hơn (margin 0.05 thay vì 0.08) để giảm số bước decoding tự hồi quy của mô hình VLM.

5. **Bộ định tuyến thông minh (Smart Gating Router)**:
   - Loại bỏ các biểu thức regex gây kích hoạt giả mạo (loại bỏ `\w\s*=\s*\w`), chỉ kích hoạt pipeline khi phát hiện ký hiệu toán học thực sự (`∫`, `∑`, `√`, `\frac`, v.v.) hoặc khi trang có bảng cần tái cấu trúc.
   - Giúp các trang văn bản thông thường bỏ qua hoàn toàn chi phí khởi chạy mô hình nặng (`SKIPPED_NO_STRUCTURE_CANDIDATE`).
