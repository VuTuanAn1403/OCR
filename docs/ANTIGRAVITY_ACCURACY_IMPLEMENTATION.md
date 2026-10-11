# Giao việc Antigravity: bộ đo accuracy có thể dùng cho nghiên cứu

**Ngày:** 09/10/2026. **Workspace:** `C:\kk_2\OCR_pdf`. **Mục tiêu:** triển khai và kiểm chứng evaluator theo [RESEARCH_PROTOCOL_V5.md](C:/kk_2/OCR_pdf/docs/RESEARCH_PROTOCOL_V5.md), tạo số đo có nguồn gốc cho PDF → Markdown đa loại. Tài liệu này là yêu cầu công việc, chưa xác nhận đã hoàn thành.

## 1. Đọc trước và thứ tự ưu tiên

Đọc protocol, [nguồn đã xác minh](C:/kk_2/OCR_pdf/docs/references/ACCURACY_SOURCES.md), `PROPOSAL_FIX_ACCURACY_RELIABILITY_PERFORMANCE.md`, mã và tests hiện tại. Review cũ là snapshot; tái hiện trên hash hiện tại trước khi đánh dấu lỗi còn/mới/đã sửa. Không reset working tree, xóa dữ liệu, sửa kỳ vọng tests để qua hoặc ghi đè evidence người khác đang thu.

Ưu tiên correctness của evaluator và provenance trước tối ưu inference. Không thêm model DLA/TSR nặng chỉ để có tên SOTA; task này là đo đúng. Những thay đổi production cần để giữ nội dung/chạy evaluator phải có test liên quan và được ghi riêng.

## 2. P0 — audit bằng chứng và tách nguồn số liệu

Lập `benchmark/research_v1/claim_evidence.csv`: file/section/claim/value/run_id/GT hash/output hash/code hash/status. Kiểm tra mọi số trong `ACADEMIC_RESEARCH_PAPER.md` và mọi câu “đã đạt” trong `RESEARCH_READINESS_20261009.md` bằng artifact/log thật. Chưa có bằng chứng thì ghi `UNVERIFIED` hoặc target; không sáng tác số, tác giả, đơn vị, dataset, CI, baseline hay kết luận. Sửa cách diễn đạt bản thảo theo bằng chứng và giữ lịch sử diff; không tự ký nghiệm thu nghiên cứu.

Tách synthetic fixtures và output thật trong manifest. Một artifact thiếu GT vẫn hữu ích để kiểm tra toàn vẹn/timing, nhưng accuracy là `NO_GROUND_TRUTH`. Đếm test pass, kiểm chứng evaluator và thực nghiệm PDF là ba phần khác nhau.

## 3. P1 — các module cần làm

| File/module | Công việc và điều kiện hoàn thành |
|---|---|
| `benchmark/scientific_evaluation/ocr_metric.py` | Counts S/D/I/H và normalized denominators; policy NFC/whitespace explicit; CER/WER_ws đối chiếu JiWER; DER_VN_v1 định nghĩa riêng với đ và trace |
| `markdown_evaluator.py` | Parser AST và byte-span mapping; GT từng phần luôn chấm result.md; missing marker không thay bằng page file; empty GT là annotation hợp lệ; bảng/escape/entity/ảnh được phân tích đúng |
| `teds_metric.py` | Adapter PubTabNet official commit; parity tests; matching bảng một-một đúng trang; TEDS matched/GT tách detection P/R/F1 và số bảng dư; không tự tuyên bố compatible từ vài identity tests |
| `dla_metric.py` | Adapter COCOeval chính thức, mapping images/categories, chuyển xyxy→xywh, scale/rotation, evaluator params và coverage; custom helper chỉ diagnostic nếu chưa parity |
| `numeric_metric.py` — mới nếu phù hợp | NumericTokenRecall riêng; NumericExact P/R/F1 và cell/location exact match; locale/sign/unit/date/leading zeros; TP/FP/FN |
| `reading_order_metric.py` hoặc module cũ | Ghép block một-một, duplicate handling, GT partial order; content recall; precedence/coverage/rho tách biệt; null khi chưa đánh giá |
| `scripts/run_scientific_benchmark.py` | Một schema status thống nhất, end-to-end và component scopes tách; tích hợp GT text/table/layout/number/order; no default synthetic metadata; JSON/CSV/LaTeX chịu null |
| `scripts/run_regression.py` | Dùng chung evaluator/policies/schema; manifest baseline gate; counts micro và document macro, không ghép bằng substring/index; no-save thực sự không ghi kết quả/baseline |
| `environment_profiler.py`, `ablation_runner.py` | Hash cả code dirty patch/lock/model thực; CPU provider; resample counts theo tài liệu; variant chạy thật; không CI giả khi một tài liệu |
| `requirements.txt` và lock evaluator | Liệt kê mọi dependency trực tiếp (hiện có scipy/bs4/lxml/parser/reference tools cần kiểm tra); pin môi trường evaluator riêng khi xung đột production; lưu license và upstream revision |

Không thay implementation metric chuẩn bằng approximation “gần đúng” để chạy nhanh mà vẫn giữ nhãn official. Chi phí evaluator GT được báo riêng, không cộng vào extraction latency; chất lượng của pipeline vẫn phải đo trên output thật.

## 4. P1 — các kiểm thử nghiệm thu bắt buộc

Các giá trị dưới đây là **fixture**, không phải số liệu PDF thực:

| ID | Tình huống | Kỳ vọng |
|---|---|---|
| A01 | CER GT `abc`, pred `axc`; pred `abcxyzxyz` | Lần lượt 1/3 và 2; không clamp/cắt |
| A02 | WER_ws GT `alpha beta`, pred `alpha` | 0,5; counts/mẫu số khớp JiWER |
| A03 | Cùng chữ dạng NFC và NFD | CER=0 sau NFC; strict vẫn phạt case/dấu/số sai |
| A04 | GT rỗng xác nhận, pred có chữ; không có GT | Hai trạng thái khác nhau; insertion count ở ca rỗng, NO_GROUND_TRUTH ở ca thiếu |
| A05 | GT `á`, pred `áá`; `đ`→`d`; sai thanh/cấu tạo dấu | DER_VN_v1 phạt đúng theo công thức/trace; không gọi đ là dấu NFD tự tách |
| A06 | GT trang 1, final.md có trang 2 nhưng mất trang 1; page-0001.md vẫn đúng | Không báo CER=0 của final; ghi missing/ALIGNMENT_FAILED đúng contract; không fallback |
| A07 | partial GT và result.md rỗng hoặc missing, marker/offset bị sửa | Phát hiện thiếu artifact/nội dung; không chấm file trung gian thay thế |
| A08 | Bảng giống/sai chữ, missing cell, rowspan/colspan, nested markup | So raw/canonical tracks với PubTabNet official; expected từ script tham chiếu, không hardcode một denominator để ép điểm |
| A09 | Một bảng đúng và một bảng dư | TEDS matched có thể 1; table precision=1/2, recall=1, F1=2/3; spurious=1 |
| A10 | Không GT bảng thật, HTML malformed, bảng đảo vị trí | N/A/invalid rõ ràng; không gán điểm hoàn hảo mặc định; matching không tối đa điểm nội dung |
| A11 | COCO xywh, duplicate predictions, sai class/image, absent class, crowd/ignore | Adapter và official COCOeval cùng kết quả; không default bbox/category/page |
| A12 | GT số `100 200`, pred `200 100 999` trong vị trí đã định nghĩa | Bag recall=1 có nhãn diagnostic; location exact P/R/F1 không hoàn hảo, FP/FN được đếm |
| A13 | Số âm `(100)`, `1.234`, `12%`, `00123`, ngày và đơn vị | Giữ nghĩa/vị trí; ambiguous locale không tự đoán để sửa số |
| A14 | Đoạn trùng tiền tố, block thiếu/dư, đảo hai cột, không GT order | Ghép một-một; không rho=1 hoặc order=1 khi chưa đo; coverage và precedence tách |
| A15 | Tài liệu dài/ngắn và nhiều dấu/ít dấu | Micro tính từ counts sau normalization, macro riêng; bootstrap cả documents, không nhân bản trang làm tài liệu độc lập |
| A16 | Baseline khác data/GT/policy/máy/cache; save_history=False | Không kết luận regression khi không comparable; không ghi baseline ngoài ý muốn |
| A17 | GT sai hash/trang, partial run, prediction thiếu | INVALID_INPUT hoặc missing prediction penalty; không bỏ trang khó để nâng score |
| A18 | CLI thiếu text/layout/TEDS/timing và xuất LaTeX | Báo null/status, không KeyError/None formatting và không tô PASS |
| A19 | Metadata mixed 1,8004 s/trang, processed=0/source_pages=100 | So số chưa làm tròn; không làm nguồn 100 trang thành mẫu số đã xử lý |
| A20 | Mọi fixture/self-test và workbook do test tạo | Không vào history khoa học, không ghi đè output thực hoặc claim evidence |

Chạy tests liên quan, sau sửa hoàn tất mới chạy suite đủ phạm vi. Không chạy full batch mỗi lần. Phải có ít nhất một smoke PDF thật cho artifact contract và một pilot **có GT thật** cho số đo; nếu chưa có GT, hoàn tất code và báo thiếu dữ liệu, không bịa GT để đóng task.

## 5. P2 — dataset và pilot nghiên cứu

Tạo manifest/annotation schema validator trước khi gán nhãn. Đầu ra đề xuất:

```text
benchmark/research_v1/
  dataset_manifest.json
  annotation_guideline.md
  annotations/<pdf_sha256>/page-0001.json
  reference_implementations.json
  claim_evidence.csv
  runs/<run_id>/{run_manifest.json,per_page.jsonl,per_document.jsonl,summary.json,execution.log}
  fixtures/                 # self-tests, không empirical metrics
```

Annotation schema phải phân biệt `not_annotated`, `annotated_empty`, `annotated_nonempty` cho từng loại text/table/layout/number/order, có scope spans và reviewer status. Sample/template ghi rõ `TEMPLATE_NOT_GROUND_TRUTH`. AI transcription không được coi là human verified; GT tuyển chọn theo proposal cần kiểm tra độc lập trên PDF.

Pilot đo từng nhóm native/mixed/scan có annotation phù hợp, dùng same subset cho V4.3/V5/baseline có khả năng chạy. Khóa config sau dev, không chỉnh GT/test theo lỗi của V5. Báo counts/CI và failures; mở rộng dataset theo độ phủ và độ rộng CI. Việc thêm PDF không thay cho việc có GT đa loại.

## 6. P2 — artifacts và nghiệm thu cuối

Mỗi run_manifest có run_id/time, command, code/version+dirty hash, dependencies/evaluator revisions+license, model/config/data/GT/output hashes, selected pages, machines/providers/threads/cache, normalization/matching/annotation policies. Bảng text/table/layout/number/order có metric status và numerator/denominator, coverage, counts theo type/domain. Timing riêng cold/warm toàn trình, completion rate và lỗi.

Các ngưỡng CPU giữ **native ≤0,15; mixed ≤1,8; scan ≤2,5 s/trang**. Không hạ đích thành 5/5,5 s; đó chỉ có thể là mốc trung gian. Accuracy chưa có ngưỡng tuyệt đối do người dùng chốt: báo `NOT_SPECIFIED`, không tự tuyên bố đạt 98/99% hay “research grade”.

Nộp `docs/ACCURACY_IMPLEMENTATION_REPORT.md` gồm: file đã sửa; tests/commands và hashes; bảng parity với evaluator gốc; corpus/provenance thật; số đo pilot; số liệu chưa đo; hạn chế; và claim_evidence đầy đủ. Đóng task triển khai evaluator khi correctness/provenance/tests đạt; chỉ đóng task nghiên cứu khi GT độc lập, thực nghiệm, CI, so sánh và yêu cầu CPU có đủ bằng chứng.

## 7. Prompt giao trực tiếp cho Anti

> Trong workspace C:\kk_2\OCR_pdf, đọc docs/RESEARCH_PROTOCOL_V5.md, docs/ANTIGRAVITY_ACCURACY_IMPLEMENTATION.md và docs/references/ACCURACY_SOURCES.md. Triển khai bộ đo độ chính xác PDF → Markdown cuối theo P0→P1→P2, ưu tiên dùng evaluator tham chiếu đã công bố và pin revision. Giữ phạm vi PDF đa loại, không thu hẹp thành báo cáo tài chính. Kiểm chứng độc lập CER/WER với JiWER, TEDS với PubTabNet và layout AP với COCOeval; định nghĩa rõ DER, reading order và numeric matching riêng. Không fallback GT, không dùng output trung gian để che nội dung thiếu trong result.md, không sáng tác kết quả hoặc tự ký human_verified. Giữ CPU mean end-to-end native ≤0,15, mixed ≤1,8, scan ≤2,5 s/trang. Mọi số trong bản thảo phải có run_id/GT/data/code/model/output hash và log. Nếu chưa có GT độc lập, hoàn tất evaluator/schema/tests và báo NO_GROUND_TRUTH. Nộp docs/ACCURACY_IMPLEMENTATION_REPORT.md với parity tests, actual pilot và phần chưa đo; không kết luận research grade chỉ từ test pass hoặc số liệu của bài tham khảo.
