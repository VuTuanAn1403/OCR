# Ưu tiên sửa bảo toàn số và nội dung cuối trước khi nâng model OCR

Bản tổng hợp ngày 03/11/2026, Asia/Bangkok. Nguồn là các báo cáo, phản ví dụ và artifact trong `Test case`, được nhận dạng trong [source_snapshot.json](evidence/source_snapshot.json). Phiên này kiểm lại nguồn và tổng hợp, không chạy lại inference hoặc sửa pipeline.

## 1. Những kết luận cần dùng để quyết định

Dự án đã hoàn thành xử lý kỹ thuật bốn PDF/511 trang, nhưng chưa có đủ GT độc lập để nghiệm thu độ chính xác toàn corpus. Cả bốn tài liệu vẫn `NEEDS_REVIEW`. Có sáu lỗi bảo toàn số/bộ chấm đã tái hiện bằng chương trình và sáu nhóm hạn chế nội dung/review được ghi nhận trong đối chiếu PDF–Markdown. Hai nhóm bằng chứng này có phạm vi khác nhau, không cộng số test, warning hoặc ô lệch thành một “tỷ lệ lỗi OCR”. [Giám sát](../Test%20case/05_GIAM_SAT_ANTIGRAVITY_20261103.md), [đối chiếu](../Test%20case/06_DOI_CHIEU_PADDLE_VA_CHUAN_KEYWORD_20261103.md).

Excel và JSON đếm đúng với chính `result.md` trong phạm vi đã kiểm. Điểm yếu được chứng minh nằm ở chữ nhận dạng và cách tạo văn bản cuối: nhầm O/0, sai dấu, xen cột, ngắt cụm và xuất hai biểu diễn của cùng nội dung. Vì vậy, chỉ chỉnh công thức Excel, mở đếm fuzzy hoặc tăng số test logic sẽ không khắc phục được các trường hợp này.

Ưu tiên trước mắt là bảo vệ số/đơn vị và tính đúng của bộ chấm; tiếp đó sửa nguồn đếm lặp và thứ tự/tiếp nối nội dung; sau đó mới thử các phương án nhận dạng. DPI, TableFormer mode, từ điển, fine-tune hoặc VLM là giả thuyết cần A/B trên dữ liệu có nhãn, chưa phải giải pháp đã chứng minh.

## 2. Phạm vi và trạng thái bằng chứng

### Lượt 03/11 có kết quả kỹ thuật, chưa có nghiệm thu accuracy

| Tài liệu | Trang PDF | Tổng theo bảng chuẩn người dùng | Tổng dự án | Ô lệch / 88 |
| --- | ---: | ---: | ---: | ---: |
| AAA | 232 | 19 | 17 | 2 |
| ABT | 43 | 2 | 2 | 0 |
| AGR | 84 | 4 | 2 | 2 |
| VIC | 152 | 141 | 110 | 10 |
| Tổng | 511 | 166 | 131 | 14 / 352 |

Nguồn: [keyword_summary.json](../Test%20case/doi_chieu_paddle_20261103/keyword_summary.json) và [kiểm publication cuối](../Test%20case/antigravity_review_20261103/final_verification_20261103_1655.json). Mẫu số là 4 tài liệu × 88 cột hiển thị, tương ứng 87 key canonical do một nhãn trùng. Không dùng kiểm kê lịch sử 7 PDF/787 trang cho lượt này.

Có 338/352 ô khớp, nhưng 316 ô cùng bằng 0; trong 36 ô có giá trị ở ít nhất một phía, chỉ 22 ô khớp hoàn toàn. Thiếu 37 lượt và thừa 2 lượt theo từng ô so với bảng người dùng, chênh tổng là 35. Đây là so sánh số đếm, không phải CER/WER hoặc accuracy. Chưa định vị đủ các lượt chênh nên không được ghi “37 lỗi bỏ sót OCR đã xác nhận”. [352 ô](../Test%20case/doi_chieu_paddle_20261103/keyword_comparison.csv), [14 ô đã thẩm định](../Test%20case/doi_chieu_paddle_20261103/keyword_differences_reviewed.csv).

Audit cuối ghi đủ trang, receipt/placement GPU, cây tiến trình thoát và revision 4 được acknowledge; tổng 37.360 warning không phải 37.360 lỗi độc lập. Những kết quả đó xác nhận hoàn tất và tính nhất quán của artifact trong lượt đã ghi, không xác nhận mọi chữ/số đúng. [Audit](../Test%20case/antigravity_review_20261103/audit_final_20261103_1655.json).

### Cách hiểu trạng thái trong tài liệu này

- **Lỗi đã tái hiện:** có expected/actual, bài kiểm và log thất bại. Chưa có bản sửa được xác minh.
- **Quan sát đã kiểm nguồn:** báo cáo đối chiếu có ảnh PDF, đoạn output và trace khi tìm được; chỉ khẳng định tại những vị trí đó.
- **Thiếu bằng chứng / `NOT_EVALUATED`:** chưa có nhãn, phép đo hoặc nghiệm thu cần thiết; không mặc nhiên là phần mềm hỏng.
- **Sửa đổi lịch sử:** có mã và kết quả kiểm ở mốc cũ; không gọi lại là lỗi chưa sửa, cũng không suy đã đạt accuracy.
- **Đề xuất:** công việc cần thực hiện; điều kiện nghiệm thu trong backlog chưa phải kết quả đã đạt.

## 3. Sáu lỗi mã/bộ chấm còn mở

Giữ nguyên ID và độ ưu tiên từ [findings.json](../Test%20case/antigravity_review_20261103/findings.json). Bộ phản ví dụ có 15 ca: 10 thất bại thể hiện sáu lỗi, 5 đối chứng đạt. Đây là lượt tái hiện lỗi, không phải hồi quy đạt. Hash phạm vi mã hiện tại vẫn khớp lúc ghi nhận; phiên tổng hợp không chạy lại bộ này. [Log/JUnit](../Test%20case/antigravity_review_20261103/counterexample_run).

| ID | Vấn đề và actual | Expected / điều kiện đóng chính |
| --- | --- | --- |
| AG-QA-001 · P1 | Guard chấp nhận `$120` → `€120`, `EUR 120` → `GBP 120`, `120 EUR` → `120 GBP` | Chặn đổi tiền tệ/ký hiệu trước và sau số; vẫn cho phép thay đổi chữ hợp lệ khi bằng chứng số không đổi |
| AG-QA-002 · P1 | `12‰` → `12` được coi là bảo toàn | Giữ đúng ký hiệu tỷ lệ, phân biệt `%`, `‰` và không có đơn vị |
| AG-QA-003 · P1 | `( 120 )` → `120` được chấp nhận, trong khi ngoặc không có khoảng trắng được chặn | Bảo toàn dấu/ngoặc kế toán với khoảng trắng và NBSP hợp lệ |
| AG-QA-004 · P1 | Hai record cùng thiếu `value`, cùng `None` hoặc chuỗi rỗng vẫn có thể báo `MEASURED`, F1=1 | Xác thực schema/giá trị; từ chối dữ liệu lỗi hoặc trả trạng thái không đánh giá được có lý do, không tính thiếu dữ liệu thành TP |
| AG-QA-005 · P2 | TP=1, FP=5, FN=0 cho F1=0,2858 thay vì 0,2857 vì làm tròn P/R trước | Tính F1 từ số đếm chưa làm tròn, chỉ làm tròn khi xuất |
| AG-QA-006 · P2 | GT có `cell_id` hợp lệ được match nhưng vẫn bị tính thiếu vị trí | Matcher và báo cáo coverage dùng cùng định nghĩa vị trí hợp lệ |

Điểm mã: [numeric_guard.py](../src/ocr_text/numeric_guard.py), `protected_numeric_fragments` / `preserves_numeric_evidence`; đường gọi [fallback_engine.py](../src/ocr_recognition/fallback_engine.py), `_safe_replacement`; [numeric_metric.py](../benchmark/scientific_evaluation/numeric_metric.py), `evaluate_numeric_exact_matching`.

Ba lỗi guard đã được probe qua hàm bảo vệ của fallback; chưa có bằng chứng một ô trong corpus thực bị thay tiền tệ/tỷ lệ/dấu âm bởi đường đi đầy đủ. Lỗi bộ chấm cũng chưa chứng minh GT hiện có chứa record hỏng. Không quy tác giả hoặc tỷ lệ phát sinh thực tế khi thiếu bằng chứng đó.

## 4. Nội dung OCR và ghép tài liệu còn làm sai phép đếm

### DC-01 · P1 — Mã ngắn dễ nhầm chữ và số

Sáu vị trí `O2O` của VIC tại trang PDF 24, 37 (hai vị trí), 52, 65, 66 thành `020`. Trang 24 đã sai ngay trong `text_raw` của source `094a6e4774e410da:p0024:b000022`; counter literal trả 0 đúng với chuỗi sai đó. [Ảnh sáu vị trí](../Test%20case/doi_chieu_paddle_20261103/visual_evidence/contact_o2o.png).

Cần phát hiện/retry/review nhóm O/0, I/l/1 bằng crop và ngữ cảnh có kiểm soát. Không thay toàn cục `020` thành `O2O`: phải giữ đối chứng số `020` thật. Đóng ca khi các vị trí có ảnh được xử lý đúng và đối chứng không bị sửa sai; không dùng đồng nghĩa hay fuzzy để tăng count.

### DC-02 · P1 — Dấu tiếng Việt sai làm mất cụm nguyên văn

VIC trang 36, 38, 58, 62, 81 có `chuyển đối số`; các vị trí khác có `đối mới`, `an ninh mang`; AGR trang 47 có `đối mói`; AAA trang 9 có `ĐỒI MỚI`. Block VIC trang 36 đã sai trong `text_raw` dù confidence 0,903 và quality 0,9418. [Ảnh chuyển đổi số](../Test%20case/doi_chieu_paddle_20261103/visual_evidence/contact_chuyen_doi_so.png), [trace gốc](../Test%20case/doi_chieu_paddle_20261103/source_block_traces.json).

Cần đo cả từ được sửa đúng và từ vốn đúng bị sửa sai; giữ số, tên, mã và bản thô. Tăng DPI hay thay model chỉ được chấp nhận sau thí nghiệm có baseline, GT và output riêng, không suy từ vài crop thuận lợi.

### DC-03 · P1 — Đúng từng dòng nhưng sai thứ tự cột

VIC trang 65: block `...:p0065:b000033` kết thúc bằng `xử lý ngôn ngữ tự`, block `...:p0065:b000037` tiếp bằng `nhiên và tiếng nói`; Markdown lại xen dòng cột khác vào giữa. Đây là bằng chứng điều tra bước ghép vùng/thứ tự đọc, không đủ để quy cho recognizer hoặc riêng TableFormer. [PDF trang 65](../Test%20case/doi_chieu_paddle_20261103/visual_evidence/full_VIC_p065.png).

Cần ghép theo cột/article và quan hệ trước–sau có nghĩa; lưu trace từ block gốc đến vị trí trong `result.md`. Nghiệm thu bằng cả cụm liên tục, thứ tự khối và đối chứng tiêu đề bắc ngang cột/footnote. Tăng chất lượng đọc ký tự riêng không tự chữa thứ tự xuất.

### DC-04 · P1 — Ngắt đoạn làm đứt cụm đúng

VIC trang 37 có `Quỹ Đổi` và `Mới Sáng Tạo` bị tách trước khi đếm; một trường hợp khác là `trí` / `tuệ nhân tạo`. Cần xác định ngắt dòng trình bày trong cùng câu, phân biệt với ranh giới đoạn, article, cột, ô hoặc trang.

Không nối toàn bộ khoảng trắng. AGR trang 40 có tiêu đề kết thúc `tài chính` rồi đoạn mới `Số liệu…`; phép nối mù tạo `tài chính Số` giả. [Đối chứng AGR 40](../Test%20case/doi_chieu_paddle_20261103/visual_evidence/full_AGR_p040.png). Sửa ở biểu diễn/tiếp nối có provenance; giữ nguyên quy tắc đếm cụm chính xác đã thống nhất.

### DC-05 · P1 — Giữ nguồn để review nhưng cùng nội dung đi vào phép đếm hai lần

AAA trang 100 có cụm `công nghiệp 4.0` ở bảng và block restored, tại dòng MD 3118 và 3126. Source `5d9a9d62e2c2ba84:p0100:b000033` còn `TABLE_SOURCE_UNMAPPED`, bảng cũng chứa chữ tương ứng. Giữ nguồn giúp tránh mất dữ liệu, nhưng chưa đủ xác định biểu diễn nào được đếm. [PDF trang 100](../Test%20case/doi_chieu_paddle_20261103/visual_evidence/full_AAA_p100.png).

Cần đối soát source occurrence, page/cell/bbox và quan hệ thay thế; mỗi occurrence có quyết định rõ về biểu diễn dùng cho nguồn đếm, các biểu diễn khác vẫn truy được. Không dedup toàn tài liệu theo chuỗi: VIC trang 137 có các dòng/số lặp hợp lệ ở phần tổng doanh thu và doanh thu thuần. [Đối chứng hợp lệ](../Test%20case/doi_chieu_paddle_20261103/visual_evidence/full_VIC_p137.png). Thay nguồn đếm là thay đổi hợp đồng cần version và kiểm tương thích, không âm thầm sửa output cũ.

### DC-06 · P2 — Review chưa được chứng minh hiệu quả ở cấp từ khóa

Điểm cao vẫn có lỗi chữ; cờ `NEEDS_REVIEW` và số warning lớn chưa chỉ ra người kiểm phải xem occurrence nào trước. Cần danh sách review có crop, source ID, cụm bị ảnh hưởng, lý do và đề xuất; không tự phê duyệt bằng confidence.

Giới hạn đã quan sát là score không bảo đảm đúng chữ và cảnh báo toàn tài liệu chưa chứng minh review hiệu quả. Review precision, lỗi bị bỏ sót và số phút người kiểm cần dùng vẫn `NOT_EVALUATED`; chưa có số liệu để tuyên bố giảm được bao nhiêu công sức.

## 5. Khoảng trống cần xử lý, không gán thành lỗi đã chứng minh

| ID | Phần chưa tốt / chưa đủ dữ liệu | Việc cần làm và điều kiện nghiệm thu |
| --- | --- | --- |
| GAP-01 | Chuẩn keyword có tổng nhưng thiếu vị trí occurrence | Gán SHA PDF, trang vật lý, bbox/đoạn, nguyên cụm và quyết định tính/không tính. Khép ba ô chưa xác minh vị trí, một ô cần kiểm lại phạm vi và ba ô mới truy một phần |
| GAP-02 | Thiếu GT độc lập đầy đủ cho chữ, số theo ô, thứ tự đọc và review | Tách development/calibration/holdout theo tài liệu/công ty; nhãn độc lập từ ảnh, phân xử và protocol khóa trước đánh giá. Công bố coverage, missing output, số đếm và giới hạn từng metric |
| GAP-03 | Primitive crop xoay chưa nghiệm thu toàn chuỗi bridge/export | Kiểm transform, coordinate space, roundtrip 0/90/180/270°, CropBox/Rotate, spread và cell ownership trên dữ liệu có nhãn |
| GAP-04 | Repetition guard có rủi ro cắt suffix/bỏ dòng | Kiểm trực tiếp hàm, caller và serialized evidence; bảo toàn raw trước cleanup, có disposition/review cho nội dung bị từ chối, giữ lặp thật có suffix |
| GAP-05 | Ma trận TC chưa tự chứng minh mọi ca có fixture/test/evidence thực | Lập trace TC → loại kiểm → test → input/GT → run/artifact → giới hạn; tách test double khỏi inference. Harness hiện chấm từng tài liệu, không tự nhận gốc batch để nghiệm thu toàn bộ |
| GAP-06 | Một lượt 4 PDF chưa chứng minh tải dài, phục hồi sự cố hoặc hiệu năng ổn định | Kế hoạch soak/fault-injection ở output thử nghiệm riêng; kiểm resume, hash, revision/ack, cây tiến trình, RAM/VRAM, timeout/OOM và thời gian quan sát có điều kiện chạy |
| GAP-08 | Tài liệu gốc còn số minh họa, khẳng định tuyệt đối và nhận định lỗi thời | Dùng bản hiệu đính 00–04 làm lớp giải thích; trích nguồn có trạng thái/ngày/identity; không lấy bảng mẫu, native text hoặc tên hệ thống lớn làm kết quả đo |

GAP-01 cụ thể: VIC `Internet vạn vật` chuẩn 7 và `tài chính số` chuẩn 1; AGR `tài chính số` chuẩn 1 chưa có vị trí nguyên văn được xác minh. VIC `dữ liệu lớn` chuẩn 7/dự án 8 cần kiểm đầy đủ phạm vi. VIC `Trí tuệ nhân tạo`, `nhà thông minh` và AAA `Đổi mới` mới truy một phần nguyên nhân. Người dùng không có bảng vị trí; giữ nguyên workbook chuẩn và tổ chức annotation từ ảnh, không tự sửa chuẩn về 0 hay ép output khớp. [Phân loại từng ô](../Test%20case/doi_chieu_paddle_20261103/keyword_differences_reviewed.csv).

GAP-03/04 là hạng mục đã được nêu trong [đặc tả 02, mục 11–12](../Test%20case/02_DAC_TA_NANG_CAP_VA_NGHIEM_THU_20261030.md). Phiên này không chạy thí nghiệm end-to-end mới cho chúng. GAP-06 và các ngưỡng trong đặc tả là kế hoạch đề xuất, không phải tuyên bố đã thử 500 PDF hoặc đã đạt chuẩn chất lượng.

### Những điểm đã sửa trước đây phải tiếp tục giữ

[Báo cáo 03](../Test%20case/03_KET_QUA_KIEM_CHUNG_20261030.md) ghi harness chuyển sang evaluator thật; giữ review qua export; matching số một-một; đối soát occurrence bảng; thêm primitive crop dọc. Lượt hồi quy lịch sử đạt 1.389 test, bỏ qua 1. Diagnostic CTS 25/70/75 có cải thiện trên một số chuỗi được chọn.

Không ghi các sửa đổi đó là chưa làm. Đồng thời, các lỗi AG-QA mới cho thấy bộ chấm/guard vẫn còn biên chưa được bảo vệ; DC-05 cho thấy giữ nguồn không đồng nghĩa đã loại lặp ở nguồn đếm; crop dọc đọc được một số chuỗi chưa chứng minh đúng mọi ô qua bridge. Lượt 1.389 test cũ và 15 phản ví dụ sau đó là hai tập/phạm vi khác nhau, không mâu thuẫn và không cộng thành chứng nhận accuracy hiện tại.

### Paddle cung cấp ứng viên đối chiếu, không làm GT mặc định

Bản Paddle có lỗi chính tả và đoạn lặp dài đã kiểm ảnh: AAA dòng 1603 có một cụm sáu từ lặp 357 lần, ảnh PDF 122 không có đoạn lặp tương ứng. Bộ dò tìm 16 ứng viên lặp dài ở Paddle và 0 ở dự án theo ngưỡng đã ghi; không coi cả 16 là lỗi độc lập đã xác nhận hay suy dự án không bao giờ lặp. Nguồn dịch vụ không có runtime receipt/hash PDF upload để so tốc độ, cấu hình hoặc xếp hạng. [Đối chiếu 06](../Test%20case/06_DOI_CHIEU_PADDLE_VA_CHUAN_KEYWORD_20261103.md).

Tiếp tục tuân thủ yêu cầu đối chiếu: bỏ cấu trúc/thẻ HTML nhưng giữ chữ và số trong ô. Khác biệt cấu trúc bảng không được đổi thành lỗi nội dung. 15.975 chunk khác và 9 khoảng dài chưa căn được chỉ là chỉ mục chẩn đoán, không phải số lỗi hoặc CER/WER.

## 6. Thứ tự thực hiện và điều kiện dừng

Các đợt dưới đây là thứ tự đề nghị, không phải lịch đã cam kết. Phần bổ sung 03/11 làm rõ phụ thuộc GAP-02/DC-06; xem [kế hoạch triển khai, trace và điều kiện hoàn tất](04_HOAN_THIEN_KE_HOACH_TRIEN_KHAI.md). ID, phụ thuộc và điều kiện đóng gốc nằm trong [backlog](03_BACKLOG_CAI_TIEN.csv), hiện cần phục hồi encoding trước khi dùng tiếp. Giữ ưu tiên P1/P2 của lỗi gốc; P3 chỉ dùng cho nghiên cứu chưa được lựa chọn.

**Chuẩn bị từ đầu:** lập trace GAP-05 và chuẩn bị nhãn GAP-01/02 theo đặc tả. Có thể chuẩn bị guideline, annotation và danh sách review sớm; phép đo nghiệm thu chỉ dùng bộ chấm đã sửa/xác minh và protocol đã khóa. Hoàn tất phần GT cần thiết của GAP-02 trước khi nghiệm thu hiệu quả DC-06.

1. **Làm đúng bộ bảo vệ và phép đo:** AG-QA-001–004 trước, sau đó 005–006. Sửa sát hàm, chạy phản ví dụ và đối chứng liên quan; thay hợp đồng liên module thì hồi quy tương ứng. Dừng công bố metric bị ảnh hưởng nếu dữ liệu/schema chưa hợp lệ; không dùng score lỗi để chọn model.
2. **Làm đúng nguồn văn bản và occurrence:** DC-05, DC-03, DC-04. Bắt đầu từ AAA 100, VIC 65/37, kèm đối chứng VIC 137 và AGR 40. Mỗi thay đổi có trace, output/analysis mới và kiểm tương thích; không che mất nguồn để làm count đẹp.
3. **Cải thiện nhận dạng/review:** DC-01, DC-02; triển khai DC-06 theo phần chuẩn bị/GT của GAP-01/02. Chỉ nghiệm thu DC-06 sau điều kiện GT nêu trên; thiếu GT thì giữ việc mở. Kiểm các crop đã xác nhận, giữ đối chứng số/từ đúng; vị trí GT còn thiếu tiếp tục chưa đánh giá thay vì tự đoán. Hướng sửa model chỉ chọn sau khi biết lỗi còn ở chặng nào.

OCR mới vẫn dùng pipeline/profile chuẩn và CUDA theo [AGENTS](../AGENTS.md). Không sửa receipt, model, lock hay batch đã chốt; không tái sử dụng stage chỉ vì cùng HEAD. Có thể dùng analysis mới trên extraction đã xác minh theo hợp đồng hiện có để tránh OCR lại khi câu hỏi chỉ thay ở tầng phân tích.

## 7. Cải tiến cách làm việc qua nhiều phiên và tối ưu ngữ cảnh

Công việc tài liệu/ngữ cảnh là một phần của kế hoạch cải tiến, với ba đầu việc WF-01–03 trong backlog. Các công cụ nền đã có: [AGENTS](../AGENTS.md), [PROJECT_MAP](../docs/development/PROJECT_MAP.md), [HANDOFF](../docs/development/HANDOFF.md), [quy trình phát triển](../docs/development/README.md), [build_dev_context.py](../scripts/build_dev_context.py) và [mẫu SESSION](../docs/development/templates/SESSION.md).

- **Tránh ảo giác dữ liệu:** mỗi kết luận có mệnh đề, trạng thái, mẫu số, identity và bằng chứng. Không lấy nội dung tóm tắt cũ làm dữ liệu gốc; phải kiểm lại hash/phạm vi khi dùng lại. Giữ thiếu dữ liệu là `NOT_EVALUATED`, không phải 0.
- **Tăng năng suất sau mỗi phiên:** chốt đầu ra và tiêu chí hoàn tất trước; làm xong một kết quả kiểm được, lưu lệnh/log/artifact, cập nhật HANDOFF ngắn với bước tiếp theo đủ cụ thể để thực hiện. Không gọi số file sửa hoặc số test chạy là năng suất sản phẩm.
- **Tối ưu token/ngữ cảnh:** đọc theo tầng và câu hỏi; dùng script xử lý dữ liệu lớn trên đĩa, chỉ nạp thống kê/chênh lệch và record liên quan. Một quy tắc có một nơi chuẩn; báo cáo dài nằm ngoài bộ khởi đầu, chỉ được mở theo ID công việc. Token thực và hiệu quả tiết kiệm hiện `NOT_MEASURED`; ngân sách byte chỉ cảnh báo kích thước tài liệu.

[Tài liệu phương pháp](02_PHUONG_PHAP_LAM_VIEC_DU_AN_LON.md) có quy trình áp dụng, cách lưu bằng chứng, kiểm khi đổi ngữ cảnh và số đo cần thu. Phần này không tuyên bố đã triển khai một bộ nhớ tự động hoặc đã tiết kiệm một tỷ lệ token cụ thể.

## 8. Nguồn, kiểm lại và giới hạn của phiên tổng hợp

Nguồn đọc chính: [00](../Test%20case/00_DOC_KET_QUA_TRUOC.md), [01](../Test%20case/01_DANH_GIA_TAI_LIEU_VA_DIEM_YEU_20261030.md), [02](../Test%20case/02_DAC_TA_NANG_CAP_VA_NGHIEM_THU_20261030.md), [03](../Test%20case/03_KET_QUA_KIEM_CHUNG_20261030.md), [04](../Test%20case/04_MAU_BAO_CAO_NGHIEM_THU_KHONG_SO_GIA.md), [05](../Test%20case/05_GIAM_SAT_ANTIGRAVITY_20261103.md), [06](../Test%20case/06_DOI_CHIEU_PADDLE_VA_CHUAN_KEYWORD_20261103.md), findings và CSV/JSON bằng chứng. Các tài liệu gốc được giữ để tra lịch sử; điểm hiệu đính của chúng được đối chiếu qua báo cáo 01 và các phần liên quan, không tái dùng số liệu minh họa trong đó.

HEAD kiểm lại: `a95c806965118b53b3afc28d2ebbff37dec0cfc7`, working tree có thay đổi chưa commit. Phạm vi 344 file source/config/lock/registry/scripts vẫn có SHA-256 `1eb382e72786c85b87ad6f4a00b3191ecedfe0ee1ac2e8c8a956809e5d08f35a`, khớp mốc giám sát; phạm vi này không bao gồm trọng số model/interpreter. 13 tệp bàn giao lịch sử và báo cáo 06 khớp hash đã lưu. Không suy cùng HEAD là cùng mọi thành phần runtime.

Các phép kiểm của phiên này: nguồn/hash, số liệu CSV tổng hợp, ID/phụ thuộc backlog, liên kết nội bộ, ngân sách tài liệu và bảo toàn phạm vi mã. Chi tiết trong [verification.json](evidence/verification.json). Không chạy lại pytest sản phẩm, GPU, audit batch hoặc chấm GT; các kết quả xử lý/ảnh/test nêu trên thuộc lượt bằng chứng gốc. Tài liệu mới không thay thế [mẫu nghiệm thu có GT](../Test%20case/04_MAU_BAO_CAO_NGHIEM_THU_KHONG_SO_GIA.md).

Đoạn kiểm trên thuộc mốc tổng hợp ban đầu. Sau đối chiếu, CSV đã đổi hash/lỗi UTF-8; mục 6 và README được bổ sung có chủ ý. Trạng thái và giới hạn hiện hành của phần bổ sung nằm trong [tài liệu 04](04_HOAN_THIEN_KE_HOACH_TRIEN_KHAI.md) và [kiểm tài liệu mới](evidence/verification_plan_addendum_20261103.json); không dùng verification cũ để chứng nhận các byte mới.
