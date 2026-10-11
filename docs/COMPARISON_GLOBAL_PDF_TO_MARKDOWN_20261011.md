# Đối chiếu OCR_pdf với Docling, MinerU và Marker

Ngày khảo sát: **11/10/2026**. Dự án: **C:/kk_2/OCR_pdf**. Phạm vi đề tài: chuyển nhiều loại PDF sang Markdown, kiểm chứng độ chính xác bằng phương pháp khoa học và đáp ứng mục tiêu thời gian trên CPU đã được người dùng xác nhận.

**Kết luận:** OCR_pdf có pipeline thực, cơ chế native/OCR, xử lý tiếng Việt, bảng, ảnh và hàng đợi rà soát. Tuy nhiên, hiện chưa có bằng chứng đủ để khẳng định độ chính xác hoặc hiệu năng ngang hay hơn Docling, MinerU, Marker. Khoảng cách rõ nhất là năng lực phân tích cấu trúc phức tạp, tính nhất quán của bộ đo, khả năng tái lập thực nghiệm và ground truth độc lập. Dự án hiện phù hợp làm nền tảng tiếp tục nghiên cứu; các tuyên bố đã đạt chuẩn nghiên cứu quốc tế trong một số tài liệu chưa được hồ sơ hiện có chứng minh.

## Mục lục

1. [Phạm vi và cách khảo sát](#1-phạm-vi-và-cách-khảo-sát)
2. [Phiên bản đối chiếu](#2-phiên-bản-đối-chiếu)
3. [So sánh năng lực](#3-so-sánh-năng-lực)
4. [Điểm mạnh thực tế của OCR_pdf](#4-điểm-mạnh-thực-tế-của-ocr_pdf)
5. [Phát hiện ảnh hưởng đến độ tin cậy nghiên cứu](#5-phát-hiện-ảnh-hưởng-đến-độ-tin-cậy-nghiên-cứu)
6. [Hiệu năng CPU và dữ liệu đầu ra hiện có](#6-hiệu-năng-cpu-và-dữ-liệu-đầu-ra-hiện-có)
7. [Kiểm thử và mức độ tái lập](#7-kiểm-thử-và-mức-độ-tái-lập)
8. [Hướng đóng góp khoa học](#8-hướng-đóng-góp-khoa-học)
9. [Thiết kế thực nghiệm đối đầu công bằng](#9-thiết-kế-thực-nghiệm-đối-đầu-công-bằng)
10. [Thứ tự cải tiến và tiêu chí nghiệm thu](#10-thứ-tự-cải-tiến-và-tiêu-chí-nghiệm-thu)
11. [Kết luận có thể sử dụng hiện nay](#11-kết-luận-có-thể-sử-dụng-hiện-nay)
12. [Hồ sơ bằng chứng](#12-hồ-sơ-bằng-chứng)

## 1. Phạm vi và cách khảo sát

Khảo sát gồm kiểm kê toàn workspace, phân tích cú pháp/AST mã Python, đọc các luồng triển khai chính, rà soát phép đo và tuyên bố trong hồ sơ nghiên cứu, kiểm tra sự tồn tại của dữ liệu/kết quả, chạy bộ kiểm thử và tái hiện phản ví dụ. Thông tin đối thủ được đối chiếu từ kho mã, tài liệu và công bố chính thức; không dùng số sao GitHub làm thước đo chất lượng.

| Nội dung | Kết quả khảo sát |
| --- | --- |
| Kiểm kê workspace | 1.883 file: mã, tài liệu, model, dữ liệu và đầu ra; không gồm `.git`, `.venv`, cache, `__pycache__` và thư mục bằng chứng của chính đợt khảo sát |
| Phạm vi phân tích triển khai | 126 file trong mã, scripts, tests, benchmark, config và các file gốc liên quan |
| Python trong phạm vi triển khai | 108 file, 17.632 dòng; không phát hiện lỗi cú pháp trong bước AST |
| Những vùng đọc sâu | CLI/batch; route/convert/process/export; native text/OCR/fallback; layout/table/diagram/reading order; cache/manifest/validator; evaluator/benchmark/ablation; tests và tài liệu tuyên bố kết quả |
| HEAD gốc | `bc187a1f90aadcc5d3448211f380fd21c6e75cf8`; working tree có thay đổi chưa commit |
| Kiểm tra bất biến | SHA-256 của 126 file đã kiểm kê không đổi từ lúc bắt đầu đến lúc chạy chẩn đoán |
| Kiểm thử hiện tại | **199 passed, 3 skipped, 2 warnings, 8,30 giây** |
| Phản ví dụ | 14 tình huống chẩn đoán tổng hợp; có script và kết quả JSON để chạy lại |
| Đầu ra hiện có | 9 thư mục tài liệu có hồ sơ quality/validation được kiểm tra; nhóm 7 PDF đầu vào hiện còn trên máy có tổng 494 trang |
| Đối đầu thực nghiệm với đối thủ | **Chưa thực hiện**: môi trường hiện tại không cài Docling/MinerU/Marker, chưa có bộ GT đã thẩm định dùng chung |

Đây là khảo sát toàn dự án theo kiểm kê và rà soát các luồng quan trọng, không phải chứng nhận mọi dòng mã không có lỗi hoặc kiểm tra bằng mắt toàn bộ ảnh/trang đầu ra. 14 tình huống tổng hợp dùng để kiểm tra hành vi mã; chúng không phải mẫu thực nghiệm để tính chất lượng OCR trên PDF thực.

## 2. Phiên bản đối chiếu

Các phiên bản mới nhất hiển thị trên trang release tại thời điểm khảo sát:

| Công cụ | Phiên bản | Commit rút gọn | Nguồn xác nhận |
| --- | --- | --- | --- |
| OCR_pdf | Manifest ghi 5.0.0; README còn tên V4.3 | HEAD như mục 1, cùng working tree hiện tại | [ManifestExporter](C:/kk_2/OCR_pdf/src/ocr/infrastructure/export/manifest_exporter.py:5), [README](C:/kk_2/OCR_pdf/README.md) |
| Docling | 2.137.0 | `d0f5546` | [Release Docling](https://github.com/docling-project/docling/releases/tag/v2.137.0) |
| MinerU | 4.0.11 | `f232373` | [Release MinerU](https://github.com/opendatalab/MinerU/releases/tag/mineru-4.0.11-released) |
| Marker | 2.0.0 | `947d768` | [Release Marker](https://github.com/datalab-to/marker/releases/tag/v2.0.0) |

Không đồng nhất phiên bản phần mềm với checkpoint mô hình hoặc phiên bản evaluator. Ví dụ, công bố MinerU2.5 giải thích một mô hình VLM; nó không tự chứng minh kết quả cho mọi cấu hình MinerU 4.0.11. Tài liệu ở nhánh `main/master` có thể đi trước release; khi chạy benchmark phải khóa cả mã, model và cấu hình thực sự được sử dụng.

## 3. So sánh năng lực

Cột OCR_pdf phản ánh triển khai hiện tại đã đọc. Cột đối thủ phản ánh khả năng được tài liệu chính thức mô tả, không phải độ chính xác đã đo trên dữ liệu tiếng Việt của đề tài.

| Tiêu chí | OCR_pdf hiện tại | Docling | MinerU 4 | Marker 2 |
| --- | --- | --- | --- | --- |
| Đầu vào theo đề tài | PDF; native, mixed, OCR được định tuyến | PDF, nhiều định dạng | PDF/ảnh, nhiều định dạng | PDF; thêm định dạng qua extras |
| Native/OCR | PyMuPDF + RapidOCR/VietOCR; retry theo chất lượng | OCR và pipeline tùy chọn | Tier Flash/Basic/Standard/Advanced | Text layer + OCR chọn lọc |
| Layout/thứ tự đọc | Hình học và luật; ONNX là nhánh tùy chọn chưa nối model mặc định | Model layout, representation cấu trúc | Small models hoặc kết hợp VLM | Layout model nhẹ hoặc VLM |
| Bảng | Native `find_tables` và tái dựng hình học OCR | TableFormer | Model bảng theo tier | Bảng và sửa bằng OCR/LLM tùy chọn |
| Công thức | Có nhãn FORMULA; chưa có engine công thức → LaTeX riêng | Hỗ trợ công thức | Có nhận dạng công thức | Hỗ trợ công thức |
| Đầu ra | Markdown, JSON, ảnh, manifest, review queue | Markdown/HTML/JSON và lựa chọn khác | Markdown và cấu trúc/định dạng khác | Markdown/JSON/HTML và lựa chọn khác |
| CPU | VietOCR ép CPU; chưa chứng minh đạt giới hạn đề tài | Có CPU | Basic chạy CPU; VLM cần khóa runtime | Có CPU; no-OCR là cấu hình riêng |
| Bằng chứng trên tập Việt của đề tài | Thiếu GT và đối đầu cùng điều kiện | Chưa đo tại đây | Chưa đo tại đây | Chưa đo tại đây |

Nguồn cho các khả năng của đối thủ: [Docling chính thức](https://github.com/docling-project/docling), [MinerU và các tier/runtime](https://opendatalab.github.io/MinerU/usage/tiers/), [Marker chính thức](https://github.com/datalab-to/marker). Hỗ trợ nhiều định dạng ngoài PDF là khác biệt sản phẩm, không phải yêu cầu bắt buộc để đề tài PDF → Markdown của người dùng đạt chất lượng.

**Docling:** phù hợp làm đối chứng về biểu diễn tài liệu và pipeline cấu trúc. Technical Report mô tả model layout dựa trên DocLayNet và TableFormer, với mục tiêu chạy trên phần cứng phổ thông. Báo cáo này là công bố về Docling v1; cần dùng tài liệu release hiện tại cho cấu hình v2. [Docling Technical Report](https://arxiv.org/abs/2408.09869).

**MinerU:** phù hợp làm đối chứng bảng/công thức và layout khó. Basic sử dụng small models, không cần local VLM; Standard kết hợp VLM. Chọn Basic cho phép thử CPU chính, còn Standard/Advanced phải ghi rõ engine và thiết bị. [Tiers and Runtimes](https://opendatalab.github.io/MinerU/usage/tiers/). Cơ chế phân tích toàn trang và nhận dạng crop độ phân giải cao có cơ sở trong công bố [MinerU2.5](https://arxiv.org/abs/2509.22186); hiệu quả trên tiếng Việt vẫn cần đo riêng.

**Marker:** phù hợp làm đối chứng đường native nhanh và OCR chọn lọc. Release 2.0 mô tả model layout nhẹ 20M tham số, mặc định fast trên CPU/MPS, balanced trên GPU; cấu hình tắt OCR chạy CPU nhưng không đại diện chất lượng PDF scan. [Marker 2.0 release](https://github.com/datalab-to/marker/releases/tag/v2.0.0).

**Đánh giá:** OCR_pdf có hướng chuyên biệt tiếng Việt và dễ điều chỉnh các chính sách chất lượng. Các đối thủ có pipeline cấu trúc và hệ sinh thái đầy đủ hơn theo tài liệu. Chưa có cơ sở xếp thứ hạng độ chính xác tiếng Việt hoặc kết luận OCR_pdf nhanh hơn/chậm hơn chúng trên cùng máy.

## 4. Điểm mạnh thực tế của OCR_pdf

1. **Có pipeline nhiều bước đang hoạt động.** Mã chia domain/application/infrastructure; có route, OCR/native, fallback, reconstruction, export và validation. Đây là nền tảng có thể tiếp tục phát triển, thay vì chỉ có bản đề xuất.
2. **Có lựa chọn nhận dạng tiếng Việt.** Balanced/accuracy sử dụng RapidOCR detection kết hợp VietOCR Seq2Seq, xử lý Unicode NFC, đánh giá dấu và các tín hiệu chất lượng. Đây là tiềm năng cần kiểm chứng bằng GT, chưa phải bằng chứng tốt hơn OCR đa ngôn ngữ.
3. **Có thông tin để điều tra lỗi.** Region, EvidenceBlock, bbox, source, confidence và review queue giúp truy vết nội dung đáng nghi. Mức độ truy vết phiên bản/model còn phải hoàn thiện.
4. **Có cơ chế giữ ảnh và cảnh báo.** Validator kiểm tra tài sản ảnh, nội dung bảng và vùng cần review. `NEEDS_REVIEW` là cảnh báo hữu ích; không đồng nghĩa kết quả chính xác hoặc đã nghiệm thu.
5. **Có kiểm thử hồi quy cho nhiều lỗi từng gặp.** Two-up, orientation, Unicode, bảng, fallback, header/footer và metric đã có fixture. Bộ metric mới đã cải thiện việc không chặn CER ở 1, xử lý absent class và phạt thiếu prediction trong một số đường đánh giá.
6. **Đã loại bỏ hệ số ablation mô phỏng trong runner.** Tuy nhiên, runner hiện chỉ phát ra một dòng hệ thống đầy đủ; cần thực thi các biến thể thật để có ablation.

Không nên bỏ các phần này để viết lại toàn bộ ngay. Cần sửa tính đúng của pipeline đo, giữ nguyên khả năng quan sát lỗi, rồi đo lợi ích từng thành phần.

## 5. Phát hiện ảnh hưởng đến độ tin cậy nghiên cứu

Mức **P1** ở đây nghĩa là cần giải quyết trước khi công bố kết quả hoặc kết luận đạt yêu cầu; **P2** là vấn đề vận hành/tái lập cần sửa để thực nghiệm ổn định. Đây không phải phân loại lỗ hổng bảo mật.

### F01 — P1: Hồ sơ kết quả chưa hỗ trợ các tuyên bố “đã đo/đã xác minh”

[ACCURACY_IMPLEMENTATION_REPORT](C:/kk_2/OCR_pdf/docs/ACCURACY_IMPLEMENTATION_REPORT.md:72) ghi parity 0.0000 với evaluator tham chiếu và liệt kê CER 0.015, TEDS 0.92, các thời gian 0.12/1.45/2.10 giây/trang ở trạng thái MEASURED. Cả 7 file kết quả được viện dẫn đều không tồn tại tại vị trí chỉ định trong lần khảo sát này.

[Dataset manifest](C:/kk_2/OCR_pdf/benchmark/research_v1/dataset_manifest.json) mới liệt kê 2 PDF; cả 2 đường dẫn đều không tồn tại, các nhãn text/table/layout/numeric/order đều `not_annotated`, không có PDF SHA-256. [Claim ledger](C:/kk_2/OCR_pdf/benchmark/research_v1/claim_evidence.csv) vẫn dùng chuỗi hash minh họa. Không suy ra số liệu bị cố ý làm sai, nhưng chúng chưa kiểm chứng được và không thể làm bằng chứng bài báo.

**Cần làm:** chuyển claim thiếu chứng cứ sang `UNVERIFIED`/`TARGET_SPECIFICATION` hoặc loại khỏi bảng thực nghiệm; chỉ đánh dấu MEASURED khi có đầu vào, GT, output, code/model/config hash, lệnh chạy và raw kết quả. Không gọi `DER_VN_v1` là “ICDAR Vietnamese Standard”: registry hiện xác định đó là metric do dự án định nghĩa.

### F02 — P1: CLI vẫn dùng evaluator cũ có thể báo điểm tốt giả

[ConvertDocumentUseCase](C:/kk_2/OCR_pdf/src/ocr/application/convert_document.py:228) vẫn gọi [benchmark/evaluate.py](C:/kk_2/OCR_pdf/benchmark/evaluate.py:191). Bộ này ghép GT bằng số đầu tiên trong tên file, không xác nhận document identity, bỏ qua prediction thiếu và trả model mặc định khi không có trang được đo.

Phản ví dụ đã chạy:

- `doc_A/pages/page-0001.md` giống text của `doc_B_page_0001.txt`; `doc_A/result.md` rỗng: evaluator vẫn báo CER/WER 0, 1 trang được đo.
- Thư mục GT không có file: báo 0 trang được đo nhưng mean CER/WER vẫn 0, diacritic/order mặc định 1.

**Cần làm:** đưa CLI và batch về một evaluator khoa học duy nhất; ghép bằng `(PDF SHA-256, document_id, page_id, annotation_revision)`; thiếu GT phải là `NOT_EVALUATED` và giá trị null; thiếu prediction trên phạm vi GT phải được tính lỗi. Phải đánh giá Markdown cuối thực sự phát hành.

### F03 — P1: Runner khoa học vẫn có thể che mất lỗi của Markdown cuối

[run_scientific_benchmark.py](C:/kk_2/OCR_pdf/scripts/run_scientific_benchmark.py:143) tính các trường `mean_cer/wer/der` từ Markdown từng trang. Nhánh partial GT lại fallback sang file trang nếu không tìm thấy marker trong `result.md`.

Phản ví dụ 14: tài liệu khai báo 2 trang, GT chỉ trang 1; file trang 1 đúng, `result.md` có nội dung khác và mất đoạn GT. Cả `academic_metrics.mean_cer` và trường CER gắn nhãn đánh giá Markdown cuối vẫn bằng 0 do fallback. Hàm helper `evaluate_final_markdown(..., partial_gt=True)` cũng chưa dùng cờ này để giới hạn vùng được gán nhãn.

**Cần làm:** tạo ánh xạ trang/khối sang Markdown cuối khi export, khóa hash `result.md`; không thay artifact đang đo bằng intermediate. Không có mapping hợp lệ thì báo `ALIGNMENT_UNAVAILABLE`; tách full-GT và partial-GT. Các headline metric phải phát sinh từ cùng artifact và phạm vi đã công bố.

### F04 — P1: NumericExact có wildcard vị trí

[numeric_metric.py](C:/kk_2/OCR_pdf/benchmark/scientific_evaluation/numeric_metric.py:127) cho match khi `gt_loc` hoặc `p_loc` là null. GT có 100 tại cell_A và 200 tại cell_B; prediction trả 200 rồi 100, cả hai không có vị trí: kết quả P/R/F1 vẫn bằng 1.

**Cần làm:** NumericExact theo vị trí phải đòi hỏi alignment hợp lệ; thiếu vị trí là không đủ điều kiện đo metric này. Bag-of-numbers chỉ là diagnostic recall. Kiểm tra thêm dấu âm, ngoặc âm, số 0 đầu, %, đơn vị và ngày tháng theo hợp đồng cụ thể.

### F05 — P1: Reading order có thể dùng lại một occurrence

[reading_order_metric.py](C:/kk_2/OCR_pdf/benchmark/scientific_evaluation/reading_order_metric.py:90) fallback tìm từ đầu toàn văn; một occurrence có thể phục vụ nhiều reference. Khi hai đoạn GT giống nhau nhưng prediction chỉ có một, coverage vẫn 1 và Spearman rho vẫn 1 do NaN được đổi thành 1. Trong phản ví dụ này precedence và penalized score bằng 0, nên không phải tất cả trường đều cho điểm hoàn hảo.

**Cần làm:** matching một-một bằng block ID/span; không tái sử dụng occurrence. Rho không xác định phải null kèm lý do. Luôn báo coverage, precision/recall và precedence; công bố chính sách đối với block ngắn và partial order.

### F06 — P1: Làm sạch Markdown gây sai nội dung được đo

[markdown_evaluator.py](C:/kk_2/OCR_pdf/benchmark/scientific_evaluation/markdown_evaluator.py:94) dùng regex thay cho parser đầy đủ. Các phản ví dụ hiện tại:

| Nội dung | Kết quả hiện tại | Vấn đề |
| --- | --- | --- |
| `price_usd` | `priceusd` | Xóa dấu gạch dưới có nghĩa |
| `<p>A &amp; B</p>` | `A &amp; B` | Không decode entity thành văn bản nhìn thấy |
| Ô Markdown chứa `A\|B` | Bị tách thành 2 ô | Đo cấu trúc bảng khác artifact nhìn thấy |

**Cần làm:** parser Markdown/HTML có contract rõ; kiểm tra literal symbols, code, escape, entity, sub/sup và công thức. Cùng một policy cho mọi công cụ, giữ raw output và xuất manifest của quá trình normalization. API CER detailed hiện xử lý mẫu rỗng bằng null khá tốt; API scalar làm mất status nên caller vẫn có thể báo 0 không hợp lệ.

### F07 — P1: IR lưu ô gộp nhưng Markdown không giữ thông tin gộp

[TableStructure](C:/kk_2/OCR_pdf/src/ocr/domain/models/table.py:433) có `row_span`, `col_span` và `to_html()` giữ spans. Nhưng [MarkdownExporter](C:/kk_2/OCR_pdf/src/ocr/infrastructure/export/markdown_exporter.py:288) luôn dùng pipe table; validator hiện còn cấm HTML table. Phản ví dụ colspan=2 xuất thành header có một ô trống bên cạnh, mất quan hệ gộp.

**Cần làm:** xác định nhất quán hợp đồng output. Nếu yêu cầu pipe-only được giữ, cần công bố giới hạn biểu diễn ô gộp và lưu span trong JSON kèm mapping; không tuyên bố Markdown bảo toàn cấu trúc gộp. Nếu mở rộng hỗ trợ bảng HTML trong Markdown để bảo toàn spans, phải cập nhật exporter, validator, parser và benchmark đồng bộ. Không chỉ bổ sung hàm HTML mà coi như đã giải quyết đường xuất thực tế.

### F08 — P1: Thời gian trong quality/benchmark không phải E2E đầy đủ

[convert_document.py](C:/kk_2/OCR_pdf/src/ocr/application/convert_document.py:156) dừng `total_duration` trước [ExportDocumentUseCase.execute](C:/kk_2/OCR_pdf/src/ocr/application/convert_document.py:220), nên không bao gồm toàn bộ export ảnh/Markdown/JSON và validation. Thời gian trang cũng dừng trước một số bước dựng evidence/Markdown/cache.

Batch có timer ngoài converter ở [batch_runner.py](C:/kk_2/OCR_pdf/src/ocr/cli/batch_runner.py:336), đây là điểm tốt; tuy nhiên scientific runner lấy thời gian từ `benchmark.json`/`quality.json`, không tự chứng minh timer được chọn đúng. `peak_memory_mb` hiện là RSS chụp sau xử lý, không phải peak được lấy mẫu suốt run. Dữ liệu thời gian làm tròn sớm không thích hợp kiểm tra giới hạn 0,15 giây.

**Cần làm:** thống nhất ranh giới E2E từ bắt đầu nhận input đến ghi xong toàn bộ artifact và validation; dùng monotonic high-resolution clock, lưu giá trị chưa làm tròn; tách startup/cold/warm/cache/resume/retry. Ghi RSS peak của process tree bằng sampling nếu báo bộ nhớ đỉnh.

### F09 — P1: Timeout không thực sự dừng worker

[process_page.py](C:/kk_2/OCR_pdf/src/ocr/application/process_page.py:99) gọi `future.result(timeout)` bên trong context `ThreadPoolExecutor`. Khi timeout, thoát context vẫn đợi worker. Chẩn đoán engine giả chạy 0,12 giây với timeout 0,01 giây: hàm trở về sau khoảng 0,12 giây, dù đã ghi timeout.

**Cần làm:** deadline tuyệt đối cho cả trang, quản lý thời gian còn lại cho mọi OCR/retry/fallback; dùng cơ chế worker có thể kết thúc hoặc API hỗ trợ cancellation. Đảm bảo timeout đi vào status/artifact; không chỉ tăng bộ đếm nội bộ hoặc log.

### F10 — P2: Cache và định danh chưa khóa trạng thái nghiên cứu

[ArtifactCache](C:/kk_2/OCR_pdf/src/ocr/infrastructure/cache/artifact_cache.py:26) trả hash rút gọn 16 ký tự, khóa gồm hash/page/profile/DPI; chưa khóa effective config, code, model, schema. [BatchOCRRunner.is_cached](C:/kk_2/OCR_pdf/src/ocr/cli/batch_runner.py:149) chủ yếu kiểm tra sự tồn tại/số trang và status, chưa đối chiếu hash input/model/config. Document ID và output directory lấy từ filename stem.

**Tác động:** đổi model/chính sách trong cùng profile hoặc thay PDF giữ tên có thể dùng lại artifact cũ; hai file cùng stem có thể trùng output. Ghi đè trực tiếp chưa tạo run bất biến hoàn chỉnh.

**Cần làm:** full SHA-256 cho định danh nghiên cứu, fingerprint code/config/model/schema, run directory riêng, atomic/staged export, kiểm tra cache fingerprint trước reuse. Có thể dùng hash rút gọn để hiển thị, nhưng giữ full hash làm bằng chứng.

### F11 — P1: Trạng thái “verified adapter” chưa có parity thực nghiệm tương ứng

[reference_implementations.json](C:/kk_2/OCR_pdf/benchmark/research_v1/reference_implementations.json) đánh dấu VERIFIED_ADAPTER. Môi trường kiểm tra có APTED nhưng không có distributions JiWER, pycocotools, lxml, distance; không tìm thấy raw parity logs tương ứng tuyên bố 0.0000.

TEDS hiện tạo cây bằng BeautifulSoup và giản lược DOM; AP hiện là triển khai nội bộ, chưa dùng COCOeval đầy đủ. Tính đúng một số fixture không chứng minh tương đương official evaluator trong mọi policy, matching, ignore/crowd/maxDets hoặc trường hợp DOM.

**Cần làm:** khóa evaluator tham chiếu bằng version/commit cụ thể, chạy cả hai trên golden corpus và tình huống biên, ghi giá trị/delta/input hash. Chưa có log thì ghi `IMPLEMENTED_UNVERIFIED`. DER/NumericExact phải công bố là metric tùy biến và chứng minh tính đúng riêng.

### F12 — P2: Ablation và bảng xuất bản chưa hoàn thiện

[ablation_runner.py](C:/kk_2/OCR_pdf/benchmark/scientific_evaluation/ablation_runner.py:77) chỉ tạo dòng Full System; mô tả dòng này vẫn nhắc TableNet dù đường xử lý bảng hiện tại chưa có TableNet được nối vào. Hàm bootstrap đã có nhưng scientific runner mới import, chưa gọi để tạo CI. [latex_generator.py](C:/kk_2/OCR_pdf/benchmark/scientific_evaluation/latex_generator.py:77) format null bằng `:.3f`, gây TypeError ở tình huống mAP/TEDS chưa đo.

**Cần làm:** chạy và lưu riêng biến thể thật; không lấy hệ số mô phỏng. Bootstrap theo tài liệu với paired difference giữa các phương pháp; mẫu rỗng/không đủ phải có status. Bảng báo cáo render `N/A` cho metric chưa áp dụng/chưa đo, không chuyển thành 0 hoặc tự suy luận điểm.

### F13 — P2: Hợp đồng chọn trang và môi trường chưa đủ chặt

[parse_pages_arg](C:/kk_2/OCR_pdf/src/ocr/cli/run_ocr.py:23) nhận `abc` hoặc `5-2` và trả None; converter hiểu None là toàn tài liệu. API cũng lọc trang ngoài phạm vi mà không fail rõ. Điều này có thể làm sai số trang và thời gian thí nghiệm.

Hai bản config ở root và `src/ocr/config` đang khác nhau; `requirements.txt` dùng version ranges, thiếu khai báo trực tiếp BeautifulSoup4/SciPy dù metric import chúng. Chưa có CI workflow trong workspace hiện tại. Các helper cài đặt vẫn mang một số nhãn phiên bản cũ.

**Cần làm:** selector không hợp lệ phải báo lỗi trước xử lý; một nguồn effective config; dependency lock theo môi trường thí nghiệm; chạy kiểm tra fresh-install và CI cho counterexamples lẫn fixture thực có sẵn hợp lệ.

## 6. Hiệu năng CPU và dữ liệu đầu ra hiện có

Giữ nguyên các mục tiêu CPU đã được người dùng xác nhận. Giá trị dưới đầu khoảng không bị xem là thất bại; giới hạn trên là điều kiện cần kiểm chứng.

| Nhóm PDF/trang theo protocol | Khoảng mục tiêu | Giới hạn trên |
| --- | --- | --- |
| Có lớp chữ khỏe | 0,05–0,15 giây/trang | 0,15 giây/trang |
| Hỗn hợp | 0,8–1,8 giây/trang | 1,8 giây/trang |
| Scan | 1,5–2,5 giây/trang | 2,5 giây/trang |

Các file quality của nhóm đầu ra 7 PDF hiện có:

| PDF | Trang | Native / Mixed / OCR | Thời gian tự ghi, giây | Tự ghi giây/trang | Validation |
| --- | ---: | --- | ---: | ---: | --- |
| PVP | 21 | 0 / 0 / 21 | 225,05 | 10,717 | NEEDS_REVIEW |
| RDP | 49 | 0 / 0 / 49 | 814,47 | 16,622 | NEEDS_REVIEW |
| SAB | 105 | 72 / 18 / 15 | 547,01 | 5,210 | NEEDS_REVIEW |
| SBA | 61 | 44 / 10 / 7 | 567,65 | 9,306 | NEEDS_REVIEW |
| SC5 | 54 | 0 / 0 / 54 | 577,47 | 10,694 | NEEDS_REVIEW |
| SFC | 77 | 33 / 39 / 5 | 811,17 | 10,535 | NEEDS_REVIEW |
| SGN | 127 | 0 / 0 / 127 | 1.350,04 | 10,630 | NEEDS_REVIEW |
| **Tổng** | **494** | **149 / 67 / 278** | **4.892,86** | **9,905** | **7/7 cần review** |

Nguồn: [artifact_evidence_audit.json](C:/kk_2/OCR_pdf/docs/comparisons/20261011/artifact_evidence_audit.json). Đây là phép tổng hợp hồ sơ có sẵn, không phải run benchmark mới. Nhãn Native/Mixed/OCR là kết quả định tuyến của pipeline, chưa phải nhãn ground truth của loại PDF.

Quan sát này cho thấy rủi ro hiệu năng đáng kể: các tài liệu đi toàn bộ qua OCR tự ghi khoảng 10,6–16,6 giây/trang. Nhưng chưa thể dùng bảng để chứng nhận hiệu năng CPU của phiên bản hiện tại: thiếu khóa code/model/provider, chưa tách cache/startup và timer quality không bao gồm E2E đầy đủ. Với tài liệu pha nhiều loại trang, trung bình cả file không được dùng để kết luận từng loại trang đạt ngưỡng.

Cả 7 file đều là báo cáo thường niên doanh nghiệp năm 2020. Chúng hữu ích để debug bảng/số liệu, nhưng chưa đại diện sách, bài báo đa cột, biểu mẫu, tài liệu hành chính, scan xấu hoặc nhiều kiểu nội dung khác của đề tài. Quality Score khoảng 0,91–0,98 là tín hiệu nội bộ, không phải accuracy 91–98% được GT kiểm chứng.

Không đặt tốc độ quảng cáo của đối thủ cạnh bảng này để xếp hạng: [benchmark phần cứng của Docling](https://github.com/docling-project/docling/blob/main/docs/usage/gpu.md) dùng cấu hình/máy khác; [Marker 2](https://github.com/datalab-to/marker/releases/tag/v2.0.0) phân biệt throughput có GPU, nhiều worker và đường CPU tắt OCR. Pages/second của nhiều worker cũng không bằng độ trễ của một trang.

## 7. Kiểm thử và mức độ tái lập

Full suite chạy bằng `.venv/Scripts/python.exe`, Python 3.11.16. Kết quả được xác nhận trong JUnit: **199 passed, 3 skipped**. Lần chạy sandbox ban đầu gặp WinError 5 ở pytest temp; lần chạy lại với temp mới trong workspace hoàn tất. Lỗi quyền của lần đầu không được tính là lỗi của pipeline.

Ba test bị bỏ qua:

| Test | Lý do |
| --- | --- |
| Golden CLW | Chưa có predictions CLW trong output |
| Integration BHN | Không có `inputs/BHN_Baocaothuongnien_2022.pdf` |
| Integration CLW | Không có `inputs/CLW_Baocaothuongnien_2020.pdf` |

Hai warning: deprecation `pkg_resources` từ gdown và pytest mark `integration` chưa đăng ký. Chúng không giải thích các lỗi metric đã tái hiện.

**Điều kết quả kiểm thử chứng minh:** các assertion hiện có đều đạt trên fixture hiện có. **Điều chưa được chứng minh:** accuracy trên PDF thực, parity upstream, tính tổng quát ngoài báo cáo doanh nghiệp, đáp ứng CPU E2E, hoặc chất lượng ngang đối thủ. Counterexamples mới cho thấy bộ test vẫn còn khoảng trống, dù tỷ lệ pass cao.

## 8. Hướng đóng góp khoa học

Hướng hợp lý là nghiên cứu **tối ưu chất lượng tiếng Việt dưới ngân sách CPU với cơ chế định tuyến và kiểm soát lỗi có thể kiểm chứng**. Không cần tái tạo toàn bộ sản phẩm Docling/MinerU/Marker để có bài nghiên cứu có giá trị.

Các giả thuyết có thể kiểm tra:

| Giả thuyết | Cách kiểm chứng |
| --- | --- |
| VietOCR + định tuyến thích hợp giảm lỗi dấu tiếng Việt so với baseline | CER/WER và DER tùy biến trên GT độc lập; paired CI; tách native/mixed/scan |
| Retry theo vùng cải thiện lỗi khó với chi phí CPU giới hạn | Full vs no-fallback; ghi số crop/call, latency, tỷ lệ sửa đúng và sửa sai |
| Kiểm soát số liệu theo cấu trúc giảm lỗi nghiêm trọng | Location-aware numeric P/R/F1 trên bảng và văn bản; bảo toàn dấu/đơn vị |
| Review queue phát hiện được lỗi đáng quan tâm | Precision/recall cảnh báo dựa trên lỗi được người gán nhãn đánh giá độc lập; đường cong risk/coverage |
| Native-first mang lại trade-off phù hợp trên tập Việt | So với all-OCR, all-native và đối thủ trên cùng corpus/hardware; báo frontier chất lượng/thời gian |

Native-first/hybrid/selective OCR hiện đã có ở các đối thủ, nên tự thân không đủ làm tính mới. Tính mới cần nằm ở chính sách định tuyến, tối ưu ngân sách, phép đo/GT tiếng Việt có chất lượng, hoặc một cải tiến được ablation và đối chứng xác nhận.

Luật bảng và sơ đồ hiện thiên về báo cáo doanh nghiệp. DiagramBuilder còn suy ra cạnh/nhãn từ vai trò tổ chức; chưa đủ bằng chứng coi là engine hiểu mọi sơ đồ. Cần phân biệt text/ảnh được bảo toàn với cấu trúc/quan hệ được nhận dạng đúng. Nhãn FORMULA cũng không tương đương chuyển công thức thành LaTeX.

## 9. Thiết kế thực nghiệm đối đầu công bằng

### 9.1. Bộ dữ liệu

Tạo corpus tiếng Việt có mã tài liệu và PDF SHA-256, phân tầng đồng thời theo:

- Modality thực: native khỏe, native hỏng/OCR layer lỗi, mixed, scan.
- Loại tài liệu: bài báo, sách/giáo trình, hành chính, biểu mẫu/hóa đơn, báo cáo doanh nghiệp và tài liệu trình bày.
- Độ khó: 1/2/3 cột, bảng có/không viền, ô gộp, chữ nhỏ, xoay, nền màu, dấu tiếng Việt, công thức, hình ảnh/ảnh chứa chữ.

Chia dev/test theo tài liệu, nguồn và template để tránh rò rỉ. GT được con người gán nhãn và kiểm tra chéo/adjudication; có thể dùng AI trợ giúp nhưng không tự động gọi đó là human_verified. GT cần text, block/order, bảng/cell/span, vị trí số, vùng ảnh và nhãn loại PDF độc lập với route của pipeline. Xác định cỡ mẫu theo độ rộng CI hoặc pilot; không lấy một số trang tùy ý làm bảo đảm độ tin cậy.

Sử dụng thêm benchmark công khai để kiểm tra khả năng tổng quát. [OmniDocBench](https://github.com/opendatalab/OmniDocBench) có đánh giá text/table/formula/layout/order; các nhãn ngôn ngữ được tài liệu liệt kê là tiếng Anh, Trung giản thể và pha Anh–Trung, nên không thay thế corpus Việt. Khóa version dataset/evaluator vì cách matching và điểm tổng hợp đã thay đổi. [olmOCR-Bench](https://github.com/allenai/olmocr/tree/main/olmocr/bench) kiểm tra các facts trên PDF một trang; điểm pass checks bổ sung cho CER, không phải CER hoặc accuracy ký tự.

### 9.2. Cấu hình đối chứng

| Track | Cấu hình cần khóa | Ý nghĩa |
| --- | --- | --- |
| OCR_pdf CPU | Fast/balanced/accuracy; config thật; VietOCR/RapidOCR model hashes; CPU provider thực | Xác định profile nào đáp ứng đồng thời chất lượng và thời gian |
| Docling CPU | Standard PDF pipeline, CPU, OCR language/model rõ; table mode rõ | Đối chứng pipeline cấu trúc trên CPU |
| MinerU CPU | Basic, small backend ONNX/CPU; ép table device CPU; ghi logs provider | Đối chứng có OCR/bảng/công thức, không trộn VLM GPU |
| Marker CPU native-only | Fast + disable OCR, CPU | Chỉ so trên tập native phù hợp; không đại diện PDF scan |
| Marker CPU có OCR | Cấu hình hỗ trợ CPU được phiên bản khóa cho phép; xác nhận mọi inference/provider/server chạy CPU | Nếu máy/cấu hình không hỗ trợ thực tế thì báo NOT_RUN, không thay bằng GPU âm thầm |
| GPU/VLM bổ sung | MinerU Standard/Advanced, Marker balanced, Docling VLM tùy mục tiêu | Báo riêng như trade-off; không dùng kết quả GPU làm chứng cứ đáp ứng CPU |

Đây là **kế hoạch cấu hình**, chưa phải xác nhận các baseline đã cài/chạy thành công ở máy hiện tại. Mỗi tool chạy trong môi trường riêng; snapshot model/config/input cố định; không bật LLM/API bên ngoài trong track CPU local chính. Nếu đánh giá LLM-assisted, công bố riêng chi phí, latency và cấu hình.

### 9.3. Đầu ra và phép đo

1. Mọi phương pháp xuất final Markdown và assets theo cùng contract; giữ bản raw trước normalization. Trích text nhìn thấy bằng cùng parser/policy có version và parity tests.
2. CER/WER báo S/D/I/H, reference length, micro và macro theo tài liệu; không chỉ lấy trung bình trang. Không đổi `NOT_EVALUATED` thành 0. CER có thể lớn hơn 1.
3. DER là metric Việt tùy biến: định nghĩa slots/mẫu số/Unicode policy rõ; không nhận là chuẩn ICDAR.
4. TEDS sử dụng official reference đã khóa; báo TEDS content/structure cho bảng matched cùng precision/recall bảng và missing/spurious count. Matching không phụ thuộc việc biết trước nhãn GT của prediction.
5. NumericExact đòi hỏi vị trí/block/cell mapping; báo diagnostic bag recall riêng.
6. Reading order dùng matching một-một, coverage và precedence; rho null khi không xác định. Layout AP nếu đo phải dùng COCOeval với mapping tọa độ/category/image identity đúng.
7. Báo mất/trùng trang, broken assets, output lỗi và tỷ lệ review. Failure không bị loại khỏi mẫu số thành công.
8. Bootstrap theo tài liệu hoặc source cluster và paired differences giữa phương pháp; công bố CI, n tài liệu và cách xử lý metric không áp dụng.

Có thể dùng [harness benchmark của Marker](https://github.com/datalab-to/marker/blob/master/benchmarks/README.md) làm ví dụ tổ chức runner, nhưng scorer/normalization/worker phải khóa và rà soát. Điểm của tác giả, điểm bên thứ ba và điểm chạy tại máy của đề tài phải được ghi thành ba nguồn khác nhau.

### 9.4. Đo thời gian

Đo trên cùng máy, cùng process/thread budget và cùng file SHA-256. Track chính công bố E2E gồm đọc/render/detect/recognize/layout/retry/export/validation; model download không tính nhưng startup model phải có chính sách cold/warm rõ. Cache/resume đo riêng.

Ghi raw seconds cho từng run và stage; báo mean/median/P95, tổng số trang, timeout/error, peak RSS thực. Đánh giá giới hạn theo nhóm PDF/trang đã gán nhãn độc lập, không gán cả tài liệu nhiều loại trang thành một loại để chọn ngưỡng dễ hơn. Với tài liệu hỗn hợp, có thể báo thêm ngân sách tổng `0,15*N_native + 1,8*N_mixed + 2,5*N_scan`, nhưng không dùng nó thay kiểm tra từng nhóm.

Người dùng đã xác nhận mục tiêu thời gian; ngưỡng accuracy tuyệt đối cho toàn đề tài chưa được xác nhận trong cuộc trao đổi. Không tự gán một con số 99% rồi tuyên bố đạt. Ngưỡng accuracy phải định trước khi mở kết quả test; kết quả tốt hơn đối thủ cũng phải dựa vào dữ liệu cùng điều kiện.

## 10. Thứ tự cải tiến và tiêu chí nghiệm thu

| Ưu tiên | Việc giao triển khai | Hoàn thành khi |
| --- | --- | --- |
| P0 | Sửa claim ledger và tài liệu kết quả | Mỗi MEASURED nối được đủ artifact/hash/log; mọi claim thiếu chứng cứ có status đúng |
| P0 | Hợp nhất evaluator CLI/batch/scientific | Các phản ví dụ F02–F06 không còn báo tốt giả; đánh giá đúng final artifact và coverage |
| P0 | Xác minh upstream parity | Có môi trường khóa và raw parity logs; null/missing giữ đúng status |
| P1 | Timer E2E, deadline, provider/memory logs | Timer bao gồm export/validation; worker quá hạn bị chặn đúng; raw số đo và actual provider được lưu |
| P1 | Cache/run provenance | Thay PDF/config/model/code làm invalidation; run mới không ghi đè run cũ; source và final artifact có full hash |
| P1 | Output bảng phức tạp | Contract pipe-only hoặc HTML được quyết định rõ; exporter/validator/evaluator cùng policy; span loss được đo/công bố |
| P2 | GT Việt đa loại và corpus công khai | Manifest không chứa đường dẫn thiếu; annotation coverage và review provenance đầy đủ; test split được đóng băng |
| P2 | Baseline runner riêng cho 3 đối thủ | Cùng input/hardware/time boundary; model/config locks; raw artifacts và failure logs đầy đủ |
| P2 | Ablation/paired CI/report | Các variant chạy thật; kết quả có CI và traceability; bảng missing metric hiển thị N/A |
| P3 | Nâng model layout/table/formula khi cần | Chọn dựa trên phân tích lỗi; chỉ tích hợp model mang lại lợi ích trên test hợp lệ trong ngân sách CPU |

Không cần đổi toàn bộ sang VLM chỉ để giống đối thủ. Điều kiện chọn model mới là cải thiện đo được dưới giới hạn tài nguyên, hoặc được báo riêng như cấu hình chất lượng cao hơn.

## 11. Kết luận có thể sử dụng hiện nay

| Tuyên bố | Trạng thái tại 11/10/2026 |
| --- | --- |
| Dự án có pipeline PDF → Markdown hoạt động và nhiều cơ chế xử lý lỗi | Có bằng chứng mã, kiểm thử và artifact |
| 199 test hiện có đạt | Đã chạy và có JUnit; 3 test khác bị skip |
| Dự án đạt accuracy khoa học với CER/TEDS/mAP như tài liệu liệt kê | **Chưa được chứng minh** |
| Dự án đã đạt các mục tiêu CPU trên nhiều loại PDF | **Chưa được chứng minh**; hồ sơ hiện có còn dấu hiệu vượt ngân sách |
| Dự án chính xác/nhanh hơn hoặc ngang Docling/MinerU/Marker | **Chưa thể kết luận** khi chưa có đối đầu cùng GT/hardware |
| Dự án có thể tiếp tục thành đề tài nghiên cứu có giá trị | Có, nếu tập trung đóng góp cụ thể và hoàn thiện phương pháp kiểm chứng |

Về độ đầy đủ của pipeline cấu trúc và khả năng tái lập, OCR_pdf hiện còn khoảng cách so với các nền tảng đối chiếu. Về chất lượng tiếng Việt và trade-off CPU, kết luận phải chờ thực nghiệm. Việc dựa vào nghiên cứu đã công bố giúp chọn phương pháp và baseline đáng tin; nó không chuyển số liệu chưa kiểm chứng của dự án thành số liệu khoa học.

## 12. Hồ sơ bằng chứng

- [Kiểm kê workspace](C:/kk_2/OCR_pdf/docs/comparisons/20261011/workspace_inventory.json): danh sách 1.883 file, kích thước, hash cho file text phù hợp, phạm vi loại trừ.
- [Manifest scan mã](C:/kk_2/OCR_pdf/docs/comparisons/20261011/project_scan_manifest.json): 126 file triển khai, SHA-256, số dòng và AST.
- [Audit hồ sơ thực nghiệm](C:/kk_2/OCR_pdf/docs/comparisons/20261011/artifact_evidence_audit.json): package versions, GT/data thiếu, 7 file chứng cứ thiếu, các hồ sơ output đã kiểm tra.
- [JUnit đã chạy thành công](C:/kk_2/OCR_pdf/docs/comparisons/20261011/pytest_results_verified.xml) và [log pytest](C:/kk_2/OCR_pdf/docs/comparisons/20261011/pytest_results_verified.txt).
- [Script chẩn đoán](C:/kk_2/OCR_pdf/docs/comparisons/20261011/run_current_counterexamples.py) và [kết quả 14 tình huống](C:/kk_2/OCR_pdf/docs/comparisons/20261011/current_counterexamples.json).

Chạy lại chẩn đoán từ project root:

```powershell
.\.venv\Scripts\python.exe -X utf8 docs/comparisons/20261011/run_current_counterexamples.py
```

Script chỉ tạo fixture trong thư mục evidence của đợt khảo sát; không thay production code, không chạy các công cụ đối thủ và không đo accuracy OCR trên PDF thực. Khi mã nguồn thay đổi, kết quả audit này cần được cập nhật; không dùng snapshot ngày 11/10 để chứng nhận một bản update sau đó.
