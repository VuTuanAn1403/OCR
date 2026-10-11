# Giao thức đo lường khoa học V5 — PDF → Markdown

**Phiên bản:** 1.0, ngày 09/10/2026. **Trạng thái:** đặc tả phải triển khai và nghiệm thu; không phải chứng nhận dự án đã đạt.

Tài liệu này quy định phép đo và bằng chứng cần lưu. Antigravity thực hiện theo [tài liệu giao việc](C:/kk_2/OCR_pdf/docs/ANTIGRAVITY_ACCURACY_IMPLEMENTATION.md). Nguồn phương pháp và mã tham chiếu nằm trong [danh mục nguồn](C:/kk_2/OCR_pdf/docs/references/ACCURACY_SOURCES.md); BibTeX ở [accuracy_metrics.bib](C:/kk_2/OCR_pdf/docs/references/accuracy_metrics.bib).

## 1. Bài toán và giới hạn tuyên bố

Đo chất lượng trích xuất **PDF đa loại thành Markdown cuối**, đồng thời đo thời gian toàn trình trên CPU. Phủ native, mixed, scan; phân tầng thêm theo miền tài liệu và đặc trưng bảng, nhiều cột, xoay/nghiêng, ảnh chứa chữ, lớp text lỗi. Không đổi phạm vi thành chỉ báo cáo tài chính.

Các công trình đã công bố cung cấp phương pháp hoặc evaluator tham chiếu. Việc trích dẫn chúng không chứng minh implementation hiện tại đúng, không chứng minh model đó đã được tích hợp, và không cho phép lấy kết quả của công trình khác làm kết quả của dự án.

Tách ba trạng thái: `METRIC_IMPLEMENTATION_VERIFIED`, `EXPERIMENT_MEASURED`, `RESEARCH_CLAIM_SUPPORTED`. Unit test đạt chỉ hỗ trợ trạng thái thứ nhất trong phạm vi đã test. Khi thiếu GT, thời gian, model hoặc baseline: lưu `null` cùng lý do, không thay bằng 0/1 hay self-test.

## 2. Ground truth và danh tính dữ liệu

### 2.1. Khóa và manifest

Khóa chuẩn là `(pdf_sha256, page_index_1based, annotation_version)`. `document_id` chỉ là tên hiển thị, không thay hash. Bbox GT và prediction phải dùng cùng hệ tọa độ, kích thước, đơn vị và phép biến đổi render.

GT manifest cần có: dataset_id/version/hash; nguồn PDF và quyền sử dụng; hash PDF; tổng trang; danh sách trang chọn và seed/quy tắc lấy mẫu; loại trang/miền/đặc trưng; split; hash render; annotation hash; phiên bản guideline; phạm vi được gán nhãn cho từng metric; người gán nhãn/review ở dạng ID; trạng thái và lịch sử chỉnh sửa.

Không ghép GT bằng substring tên thư mục, CLW/sample fallback, vị trí file trong danh sách hoặc tên gần giống. Hash sai, page_id trùng hoặc category mapping không hợp lệ phải làm phép đo `INVALID_INPUT`.

### 2.2. Quy trình gán nhãn

Gán nhãn theo nội dung nhìn thấy trên trang, không lấy prediction của hệ thống làm GT. Nếu AI/OCR hỗ trợ bản nháp, lưu `DRAFT_ASSISTED` và provenance; chỉ người kiểm tra độc lập mới chuyển thành `HUMAN_REVIEWED`. Agent không tự ký `human_verified`.

Giữ văn bản, dấu, chữ hoa/thường, số, dấu âm, đơn vị, ô bảng và quan hệ đọc. Đánh dấu `illegible` bằng vùng cố định được chọn trước; báo tỷ lệ không chấm, không bỏ vùng khó sau khi xem kết quả. Hai người gán nhãn một tập con phân tầng, thống nhất bất đồng; báo text edit disagreement, label/bbox agreement và cell agreement phù hợp từng phần. Đây là quy trình QA của dự án, không phải lời bảo đảm của một hội nghị.

Tách tài liệu dùng tinh chỉnh với tài liệu test khóa trước khi đo. Trang cùng tài liệu và bản trùng/gần trùng không được rải qua dev/test. GT sparse text anchors chỉ được chấm anchor recall, không được báo CER toàn trang. GT bảng/layout không đồng nghĩa đã có GT văn bản.

### 2.3. Cỡ mẫu

Bắt đầu bằng pilot có GT trên các nhóm chính để kiểm tra evaluator và ước lượng biến thiên. Bộ 60 trang trong đề xuất cũ có thể làm bộ hồi quy kỹ thuật; không tự coi là test set đủ cho mọi kết luận. Chọn quy mô nghiên cứu theo độ phủ, số tài liệu độc lập, sai số/khoảng tin cậy mong muốn và nguồn lực. Lưu bảng số tài liệu/trang/block/bảng/token theo nhóm; nhóm chưa có GT phải ghi chưa đánh giá.

## 3. Chấm đúng artifact Markdown cuối

Đầu vào chính là `result.md` đã xuất và hash của nó, cùng các assets nó tham chiếu. `result.json`, evidence và Markdown từng trang chỉ phục vụ truy vết/đo thành phần; không được thay thế nội dung thiếu ở `result.md`.

Yêu cầu exporter lưu ánh xạ trang/block đến **byte range trong chính result.md** hoặc dùng page markers có hợp đồng rõ ràng. Kiểm tra hash và range trước chấm. GT một phần: chỉ chấm các span đã gán nhãn tương ứng trong artifact cuối, báo coverage theo trang/block/ký tự. Nếu marker/range mất, báo `ALIGNMENT_FAILED` hoặc tính thiếu nội dung nếu đã xác định được trang; **không fallback sang pages/page-*.md** để báo điểm của result.md.

Tách văn bản đọc được, bảng HTML/Markdown, công thức nếu trong phạm vi, và ảnh/figure. Parser Markdown phải có AST/version, xử lý escape `\|`, code, link, HTML entity, Unicode và bảng gộp ô. Không xóa ký tự mang nghĩa bằng regex chung như dấu `_`, `-`, `<`, `>` trong nội dung.

Hai policy được khóa trước đo:

- `visible_strict_v1`: bỏ cú pháp trình bày và marker do exporter sinh, NFC, chuẩn hóa line endings; giữ case, dấu, dấu câu, chữ số, đơn vị và nội dung đọc được.
- `reading_normalized_v1`: thêm chuẩn hóa khoảng trắng và xuống dòng do bố trí; nếu xử lý ngắt từ cuối dòng phải có luật được kiểm chứng. Áp dụng cùng phép biến đổi cho GT và prediction.

Header/footer được loại khỏi một track chỉ khi annotation policy đã xác định nội dung đó ngoài phạm vi. Báo thêm recall nội dung bị lọc; không chọn policy cho từng file dựa trên policy nào cho điểm tốt hơn.

## 4. Định nghĩa các chỉ số

### 4.1. CER và WER — chỉ số chính cho chữ

Sau policy chuẩn hóa, căn chỉnh chuỗi bằng edit distance với chi phí substitution/deletion/insertion bằng 1:

`CER = (S_char + D_char + I_char) / N_char_GT`

`WER_ws = (S_token + D_token + I_token) / N_token_GT`

WER dùng định nghĩa edit-based của Morris và cộng sự [S1]; CER áp dụng cùng thao tác trên ký tự. Đối chiếu implementation độc lập bằng JiWER [T1] với cùng transformations. Không dùng cùng helper trong hai nhánh rồi gọi là kiểm chứng độc lập. Không cắt prediction, không clamp về 1: lỗi chèn có thể làm CER/WER vượt 100%.

Đơn vị ký tự chính: Unicode code point sau NFC; ghi rõ cách xử lý whitespace. `WER_ws` tách token theo whitespace, không tuyên bố đây là tách từ ngôn ngữ học tiếng Việt. WER có bộ tách từ tiếng Việt, nếu thêm, là track riêng với version tokenizer cố định.

Lưu S/D/I/H và mẫu số **sau chuẩn hóa**. GT rỗng thật: lưu insertion_count và empty_page_false_positive, tỷ lệ CER/WER là `null` vì mẫu số 0 trong protocol này. Đầu ra rỗng với GT không rỗng: deletion=N, CER/WER=1. Không có GT khác với GT xác nhận rỗng.

### 4.2. DER — chỉ số bổ sung, không thay CER

Tên `DER_VN_v1`, ghi là **định nghĩa riêng của dự án**, không gán là metric chuẩn của một bài báo khi chưa có nguồn trùng định nghĩa. Căn chỉnh ký tự NFC đầy đủ trước, sau đó so representation NFD: base, dấu cấu tạo nguyên âm và dấu thanh. Xử lý `đ/Đ` bằng thuộc tính stroke riêng vì không được NFD tách thành `d/D` cộng combining mark.

Mẫu số `N_diacritic_GT` là tổng thuộc tính dấu có ở GT. Representation tiếng Việt có ba slot: `shape` (breve/circumflex/horn), `tone` (acute/grave/hook/tilde/dot-below), `stroke` (đ/Đ). Base cho riêng DER không phân biệt hoa/thường; CER strict vẫn phân biệt. Slot trống ký hiệu 0. Với mỗi cặp đã align, mỗi slot có ít nhất một phía khác 0 tính một lỗi nếu giá trị slot khác hoặc base khác. Không đếm thêm lỗi base lần thứ hai cho cùng slot. Ký tự gap có mọi slot=0; vì vậy deletion/insertion dấu được tính. Mỗi slot GT khác 0 đóng góp một vào mẫu số; `á`→`à` có một lỗi/một dấu, `ấ`→`ầ` có một lỗi/hai dấu. Combining marks ngoài tập tiếng Việt phải được thống kê riêng, không âm thầm diễn giải là dấu tiếng Việt. Chốt alignment ties trước đo và lưu trace.

Không dấu GT: DER tỷ lệ `null`, báo số dấu sinh dư. Không lấy trung bình DER có trọng số bằng tổng ký tự; micro-DER = tổng lỗi dấu / tổng dấu GT trong phạm vi có mẫu số. Báo cả loại lỗi dấu và CER để tránh diễn giải DER như độ chính xác toàn văn bản.

### 4.3. Bảng — TEDS tham chiếu và detection riêng

Dùng TEDS của Zhong và cộng sự [S2] qua adapter evaluator PubTabNet chính thức [T2]. TEDS-S dùng chế độ structure-only của cùng evaluator khi commit đã pin hỗ trợ. Tên báo cáo, parser HTML, cách xử lý `thead/tbody`, `th/td`, nested markup và denominator phải theo phiên bản tham chiếu. Nếu canonicalize HTML để so bảng Markdown với GT, áp cùng adapter cho cả hai và công bố đó là track đã thích nghi, không giả là raw official score.

Xuất HTML từ **bảng hiện trong Markdown cuối**, bảo toàn ô trống/rowspan/colspan. Ghép bảng một-một bằng annotation correspondence có kiểm chứng hoặc matching bbox cùng trang trước khi chấm nội dung; không ghép để tối đa TEDS và không zip theo thứ tự khi bảng có thể thiếu/dư.

Báo riêng: table precision/recall/F1, missing/spurious counts, mean TEDS của bảng matched, và `TEDS_GT` trên tất cả bảng GT với bảng thiếu = 0. Bảng dư bị phạt trong precision/F1; không tuyên bố TEDS đơn lẻ chứng minh không có bảng dư. Nếu muốn score phạt cả bảng dư, đặt tên riêng `TEDS_document_penalized`, nêu công thức và không gọi đó là TEDS chính thức. Không có bảng GT: TEDS=`null`, vẫn báo spurious count/detection status.

### 4.4. Layout — evaluator COCO

Dùng `pycocotools.COCOeval(iouType="bbox")` [T3], báo AP50 và AP@[.50:.05:.95], lưu evaluator params. Bài COCO [S3] là cơ sở dataset; quy tắc thực thi lấy từ evaluator đã pin. Layout là metric thành phần, không thay độ chính xác chữ trong Markdown.

Ánh xạ `images.id` đến PDF hash/trang, `categories.id` đến label đã khóa. COCO bbox là `[x,y,width,height]`; bbox nội bộ `[x0,y0,x1,y1]` phải chuyển đúng, scale/rotation đúng. GT phải là annotation thật, có area/iscrowd khi contract yêu cầu; không tạo bbox/default score để làm đầy input. Class không có GT là not evaluated, không gán AP=1. Lưu maxDets, areaRng, ignore/crowd và class coverage. Adapter phải khớp official evaluator trên fixtures trước khi dùng số AP.

### 4.5. Reading order và tính đủ nội dung

OmniDocBench [S4, T4] cung cấp hướng đánh giá parsing end-to-end, gồm reading order; chỉ báo điểm OmniDocBench chính thức nếu thực sự dùng đúng dataset/evaluator/version. Trên bộ tiếng Việt riêng, ghi rõ adapter và định nghĩa riêng.

GT gồm block_id và quan hệ trước/sau, cho phép thứ tự bộ phận khi nhiều thứ tự đều hợp lệ. Ghép block một-một bằng provenance/span/bbox được kiểm chứng, độc lập với thứ tự prediction. Tránh `find()` tiền tố 35 ký tự vì đoạn lặp có thể ghép cùng vị trí.

Báo: block precision/recall/F1, matched coverage; pairwise precedence trên các cặp GT được ràng buộc, với cặp thiếu block tính sai; Spearman rho chỉ trên các block matched có thứ tự toàn phần. Rho là tương quan có miền [-1,1], không phải accuracy. Không có cặp đủ điều kiện: order score=`null`. Nếu dùng `precedence × coverage`, ghi đó là custom penalized score, không đặt tên Spearman. Với <2 matched blocks, rho=`null`, không suy ra thứ tự hoàn hảo.

### 4.6. Số liệu — exact matching có vị trí

Đổi phép đo bag-of-numbers hiện có thành `NumericTokenRecall`; giữ như chẩn đoán, không gọi là accuracy đầy đủ. Metric nghiên cứu riêng: `NumericExact_P/R/F1` và `NumericCellExactMatch`.

GT lưu number_id, span/block_id, table_id, row/column, raw_text, sign/unit/currency/percent/date và locale khi có. Ghép một-một theo **vị trí/ngữ cảnh**, không ghép chéo ô chỉ vì giá trị giống. TP đúng giá trị và vị trí; FP số dư/sai, FN số thiếu/sai. Giá trị sai thay thế sinh cả FP và FN. Precision=TP/(TP+FP), recall=TP/(TP+FN), F1=2TP/(2TP+FP+FN).

Track chính giữ raw số sau NFC/whitespace hợp lệ; track semantic-normalized riêng dùng locale/schema GT khóa trước. Không tự đổi `1.234` thành 1,234 hoặc 1234 khi chưa biết locale; giữ số 0 đầu mã định danh, dấu âm ngoặc, đơn vị và phần trăm. Một số đúng nhưng nằm sai ô vẫn thất bại. Không có số ở GT và prediction: `NOT_APPLICABLE`, không cộng 100% vào trung bình.

### 4.7. Ảnh, sơ đồ và công thức

Image link existence/hash và broken-asset count là chỉ số toàn vẹn kỹ thuật. Muốn báo figure recall cần GT figure correspondence, không chỉ đếm link. Chữ chỉ được giữ dưới dạng ảnh không được coi là text extracted đúng. Sơ đồ/công thức chỉ được báo semantic accuracy nếu có GT và evaluator phù hợp; chưa có thì `NOT_MEASURED`. Không dùng confidence/quality_score/LLM tự chấm làm accuracy chính.

## 5. CPU, thời gian và khả năng tái lập

Giữ mục tiêu người dùng: native 0,05–0,15; mixed 0,8–1,8; scan 1,5–2,5 giây/trang. Giới hạn nghiệm thu lần lượt **≤0,15; ≤1,8; ≤2,5** trên mean toàn trình. Nhanh hơn đáy khoảng không phải thất bại.

Đo bằng perf_counter từ trước mở PDF đến hoàn tất xuất Markdown/JSON/assets của lượt xử lý; công bố rõ có/không bao gồm model initialization. Báo **cold end-to-end có initialization** và **warm end-to-end** riêng, không chọn warm để chứng minh cold đạt. Nếu initialization chia sẻ batch, báo batch wall-clock và quy tắc phân bổ trước; không phân bổ chi phí chung để chọn điểm đẹp.

Theo nhóm: số trang yêu cầu, thành công, lỗi/timeout; thời gian trang kể cả retry/export/failed work; mean/p50/p95/max, throughput, peak RSS, threads. Loại PDF/trang lấy từ annotation metadata, không suy ra bằng route mà model tự chọn. Mẫu số là các trang thực trong run, không tổng trang PDF nguồn khi chỉ chạy một phần. Fail/timeout không được biến mất khỏi speed table; báo completion rate cùng thời gian.

Ghi CPU/model/RAM/OS/Python/dependency lock, ONNX provider thực, code SHA và dirty-patch hash, config/model/input/GT/output hashes, thread limits, cache/cold-warm policy, seeds, lệnh chạy. Tắt CUDA khi đo CPU và xác minh provider/device thực. Không đưa thời gian unit test hoặc evaluator GT vào extraction latency.

## 6. Baseline và ablation

Chạy V4.3, V5 và baseline phù hợp trên cùng test documents, policy, máy và run settings; chọn baseline theo câu hỏi nghiên cứu và khả năng chạy, không lấy số từ leaderboard khác máy. Nếu một baseline không hỗ trợ bảng/Markdown, báo phạm vi tương thích và phần không hỗ trợ.

Ablation phải chạy thật các cấu hình bỏ routing, retry/fallback, lọc noise/header, layout/table khi phù hợp. Mỗi hàng có run_id, config/code/data/model hash và raw metrics. Tên model trong description phải đúng model thực sự loaded; heuristic phải ghi heuristic. Không nhân hệ số để tạo biến thể, không dùng output cũ sau code đổi.

Baseline được chọn cố định, tách khỏi history. So sánh phải kiểm tra dataset/split/page selection/annotation/policy/evaluator/machine/cache manifests tương thích. So khác corpus chỉ là hai quan sát, không kết luận regression/cải tiến. Ngưỡng hồi quy kỹ thuật cũ 0,5 điểm phần trăm không thay cho kiểm định hoặc mức accuracy tuyệt đối.

## 7. Tổng hợp, bất định và chênh lệch

Lưu counts để tính micro-CER/WER bằng tổng S+D+I trên tổng mẫu số; macro theo tài liệu và theo trang là cột riêng. Không lấy độ dài raw làm trọng số cho metric tính trên text đã chuẩn hóa. DER dùng mẫu số dấu; Numeric P/R/F1 dùng pooled TP/FP/FN.

Áp dụng ý tưởng bootstrap của Koehn [S6] theo **cụm tài liệu**, là điều chỉnh thiết kế cho dự án này: resample document IDs, giữ mọi trang của tài liệu được lấy, tính lại toàn metric. So hệ thống dùng cùng mẫu tài liệu cho mỗi replicate và báo CI95% của delta. Pin seed và số replicate (mặc định kỹ thuật 2.000, có kiểm tra ổn định). Một tài liệu không đủ CI tổng quát; báo insufficient_documents. Báo sample counts, effect size và giới hạn chọn mẫu; không diễn giải mọi chênh lệch nhỏ là cải tiến.

## 8. Nghiệm thu evaluator

Phải có đối chiếu độc lập với JiWER, PubTabNet và COCO official tương ứng; pin version/commit/hash, lưu license và adapter normalization. Kiểm thử identity, deletion, insertion vượt 100%, Unicode NFC/NFD, dấu tiếng Việt/đ, duplicate text, missing/extra tables, spans, wrong class/page, malformed input, zero denominator và Markdown bị mất trang.

Các ca bắt buộc và kế hoạch sửa file ở tài liệu giao việc. Golden outputs từ evaluator tham chiếu phải được dựng lại bằng command/version lưu được; không sửa expected để khớp code đang sai. Fixtures và self-test lưu riêng, không vào kết quả thực nghiệm.

## 9. Báo cáo và điều kiện công bố số liệu

Metric record cần `name`, `definition_version`, `track`, `scope`, `status`, `value`, counts/denominator, GT/output coverage, provenance và reference implementation. Các trạng thái tối thiểu: `MEASURED`, `NO_GROUND_TRUTH`, `NOT_APPLICABLE`, `ALIGNMENT_FAILED`, `INVALID_INPUT`, `UNSUPPORTED`, `INSUFFICIENT_DOCUMENTS`. `null` là chưa có tỷ lệ, không phải 0 lỗi. CSV/Markdown/LaTeX phải giữ trạng thái, không crash khi None, không tô PASS khi chưa đo.

Tách `evaluation_valid`, `accuracy_requirement_met`, `performance_requirement_met`, `research_claim_supported`. Người dùng chưa chốt ngưỡng accuracy tuyệt đối: lưu `accuracy_targets_status=NOT_SPECIFIED`, báo kết quả đo và CI, không tự đặt CER/TEDS mục tiêu rồi tuyên bố đã đạt. Protocol/evaluator đúng vẫn không tự bảo đảm hội nghị/tạp chí chấp nhận.

Mỗi con số/tuyên bố trong bản thảo phải nối với run_id, raw result, GT manifest và code/model hash. Câu không có bằng chứng ghi hypothesis/target/unverified; không chuyển unit test hoặc trích dẫn nghiên cứu khác thành empirical result. Đọc lại `ACADEMIC_RESEARCH_PAPER.md` và `RESEARCH_READINESS_20261009.md`: các tuyên bố đã đạt và số liệu chưa có provenance phải được kiểm chứng/cách ly rõ ràng, giữ lịch sử tài liệu.

## 10. Nguồn và quyền sử dụng

Dùng mã nguồn tham chiếu theo license, pin revision thay vì chỉ URL `main/master`. Dataset công khai vẫn cần kiểm tra license, phiên bản và điều kiện sử dụng. Nhãn đúng implementation: nguyên bản, adapter tương thích đã đối chiếu, hoặc custom. Không gọi custom metric là “chuẩn ICDAR/IEEE” chỉ vì bài tham khảo được công bố tại hội nghị đó.

Các mã [S1]–[S6], [T1]–[T4] được định nghĩa và liên kết trực tiếp trong [ACCURACY_SOURCES.md](C:/kk_2/OCR_pdf/docs/references/ACCURACY_SOURCES.md).
