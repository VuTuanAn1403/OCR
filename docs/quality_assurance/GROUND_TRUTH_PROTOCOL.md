# Phương pháp Ground Truth và khóa benchmark

Ngày 07/11/2026. **DRAFT — chưa khóa corpus/split/GT, chưa phê duyệt protocol hoặc ngưỡng.** Ngoại lệ duy nhất: §7, quy trình xác minh text layer cho cổng dấu, đã LOCKED v1 ngày 09/11/2026 và v2 (lựa chọn đo §7.6) ngày 10/11/2026. Tài liệu này chuẩn hóa cách chuẩn bị, tương thích công cụ hiện có; không tự tạo một bộ đáp án. Tình trạng chưa có người A/B đã được bàn giao: không hỏi lại phân công, không dùng AI/model output thay GT. Chất lượng corpus giữ `NOT_EVALUATED`.

Nguồn chuẩn kỹ thuật: [catalog](../../src/ocr/collect/catalog.py), [ANNOTATION_V6](../../benchmark/ground_truth_tools/ANNOTATION_V6.md), [human annotations](../../benchmark/ground_truth_tools/human_annotations.py), [protocol_preflight](../../benchmark/scientific_evaluation/protocol_preflight.py) và [mẫu protocol hiện có](templates/benchmark_acceptance_protocol.example.yaml). Không sửa các schema hoặc mẫu DRAFT đó để ép preflight thành công.

## 1. Chọn phạm vi và nguồn

Khai báo population tài liệu, loại trang, mục tiêu downstream và modality cần đo trước lấy mẫu. Dùng nhãn digital/scan/mixed và các tag khó như chữ nhỏ, dấu, xoay, bảng/công thức, nhiều cột; các tag có thể chồng nhau nên tổng tag không phải số tài liệu độc lập. Cần báo nhóm thực tế và mẫu số, không suy quota “20 mỗi nhóm” hay quy mô “80 tài liệu” trong bài là yêu cầu đã được chốt.

Tái dùng inventory CSV và metadata `sources-v2`: document ID, relative path, PDF SHA-256, số trang và metadata nguồn/công ty đã xác minh. Không suy company/year/ngành từ tên file khi chưa có bằng chứng; giữ unknown. PDF hỏng/không đọc được có trạng thái lỗi riêng, không biến thành tài liệu 0 trang đã đạt.

Đề xuất dataset ID/version chỉ là metadata quản lý bên ngoài nếu cần. Không đưa JSON mẫu `documents: []` trong bài vào thay CSV/splits đang được code kiểm. Identity nghiệm thu nằm trong các artifact manifest/hash được preflight xác minh, không chỉ trong nhãn version.

## 2. Phân tập đúng hợp đồng hiện hữu

[`ACCEPTANCE_SPLITS`](../../src/ocr/collect/catalog.py) là **`train`, `development`, `calibration`, `holdout`**. Chia theo công ty và tài liệu, không chia ngẫu nhiên từng trang. Code yêu cầu đủ bốn partition với công ty đã xác minh, mỗi partition có ít nhất một công ty, không gán trùng và không có unknown. Nếu phạm vi mới muốn bỏ train hoặc đổi partition, đó là thay đổi protocol/code phải được xử lý riêng; audit này giữ hợp đồng hiện tại.

Tất cả năm/phiên bản cùng công ty, nhóm template hoặc near-duplicate đã rà phải ở cùng partition. PDF có cùng bytes không được quy cho hai công ty khác nhau. Các tài liệu đã dùng debug/tune/so sánh hoặc xem đáp án được ghi exposure, đặt `development_only`; không tự đẩy AGR/ASM/VIC và mẫu lịch sử sang holdout chỉ bằng cách đổi tên/cắt trang.

`split-leakage-audit-v2` cần:

- Hash CSV nguồn và đầy đủ membership cho `template_groups`/`near_duplicate_groups`, gồm cả nhóm một thành viên.
- `source_dispositions` cho từng document, kèm căn cứ lịch sử sử dụng và quyền dùng; `eligible_for_assignment` chỉ sau khi người phụ trách đã xác minh, không từ heuristic tương tự ảnh.
- Người rà, thời gian có timezone, trạng thái reviewed và holdout custodian thực sự. Audit còn thiếu giữ DRAFT.
- Tham chiếu quyền truy cập calibration và holdout riêng. CLI kiểm cấu trúc/hash/tham chiếu, không tự chứng minh quyền trên kho dữ liệu hoặc việc người gán nhãn độc lập.

Khóa bằng `lock_company_splits(..., audit=...)`, kiểm lại bằng `verify_company_splits`. Khi inventory/audit/assignments đổi, tạo phiên bản output mới; không ghi đè lock cũ. `splits-v1`/`train,dev,test` lịch sử có thể phục vụ diagnostic, không thay điều kiện nghiệm thu mới.

## 3. Gán nhãn từ nguồn và nhận dạng từng đơn vị

Mỗi annotation phải có document/PDF hash, physical page 1-based, region/source locator, ảnh/crop hash, bbox và coordinate space/transform đúng view đã xem. Không lấy bbox OCR là GT mặc định. Trang xoay/CropBox/spread phải có frame và phép đổi rõ ràng. Source crop thiếu hoặc chữ không đọc được phải ghi unresolved cùng lý do.

Tái dùng các kiểu nhãn hiện có theo nhiệm vụ:

- **Text/dấu:** transcription độc lập từ ảnh, giữ hoa/thường, dấu, số, đơn vị và multiplicity; áp đúng normalization protocol. Không prefill OCR/LLM thành đáp án độc lập. Không chắc ký tự giữ unresolved, không đoán theo câu/tài chính.
- **Detection/layout:** vùng/polygon hoặc bbox, loại vùng, ignore/crowd nếu protocol hỗ trợ; phân biệt vùng chữ với layout object. Nhãn detection bỏ trống khác với đã rà ảnh và xác nhận không có vùng chữ.
- **Bảng:** `structured-page-gt-v1` có table/cell IDs, text, địa chỉ hàng/cột, row/column spans, bbox và header/unit/năm; ownership và quan hệ qua trang cần nhãn tương ứng. Dùng [table boundary annotations](../../benchmark/ground_truth_tools/table_boundary_annotations.py) cho L5, không suy từ bảng logic heuristic.
- **Reading order:** GT node ID/precedence trên phạm vi đã khai báo. Prediction split/merge cần artifact căn span riêng `ocr-reading-order-alignment-v1`, ghim GT/extraction hash và người/thời điểm rà. Không sửa GT để khớp segmentation prediction.
- **Keyword:** GT occurrence theo source unit, nguyên cụm/vị trí và quyết định; snapshot dictionary/policy. Artifact alignment prediction riêng phải giải thích attribution/outside-scope. Cùng tổng không chứng minh cùng occurrence.
- **Công thức:** giữ [formula annotation](../../benchmark/ground_truth_tools/formula_annotations.py), alignment/content/critical và renderer policy. Công thức đã được dự án đặt trong scope; không tự loại để tăng coverage hay xem dung sai CDM riêng là phê duyệt mọi ngưỡng.

Phiếu A/B/phân xử, declaration/custody/seal hiện hữu phải được thực hiện với người thật và ảnh nguồn khi có nguồn lực. Tool kiểm tính đầy đủ, consistency và hash, không xác thực được nhận thức/độc lập của con người. Export từ pilot development vẫn giữ `eligible_for_quality_acceptance=false`; không đổi field để dùng làm holdout.

## 4. Phân biệt thiếu nhãn, nhãn rỗng và thiếu đầu ra

- Không có GT/unresolved: metric giữ null và `NOT_EVALUATED`, ghi số đơn vị đã khai báo/chưa được chấm, không kết luận absence of errors.
- Đã xem nguồn và xác nhận rỗng: giữ annotation state rõ; output thừa vẫn được đếm FP/insertion. Mẫu số rate bằng 0 thì rate null; không gọi “0 lỗi” chỉ vì không có mẫu số.
- Có GT nhưng thiếu prediction: giữ đơn vị trong mẫu số và phạt theo evaluator tương ứng. Không lọc trang/tài liệu thất bại khỏi benchmark để làm đẹp kết quả.
- Có GT chỉ một phần: báo partial coverage và các counts quan sát; không tổng quát thành toàn corpus đã đạt. Các metric khác scope có coverage riêng.

## 5. Khóa gói nghiệm thu

Protocol máy đọc hiện có là `ocr-benchmark-acceptance-proposal-v1`. `REQUIRED_ARTIFACTS` trong preflight là nguồn danh sách hash bắt buộc; scope công thức/release còn có yêu cầu bổ sung. Giữ các nhóm:

- Population/subgroup/sample plan, input inventory, company split, audit rò rỉ/quyền/exposure.
- GT manifest, annotation guideline/version, adjudication/alignments và source hashes.
- Projection `result.md`/`visible_strict_v1`, matching protocol, evaluator code/HEAD/dirty diff; dictionary/literal contract và disposition nguồn.
- Ngưỡng tuyệt đối theo nhóm, noninferiority margins, kế hoạch sample size/precision và multiple-comparison family; người duyệt có thật. Audit không tự ấn định con số.
- Review threshold/calibration report và holdout sample; model registry, dependency locks, interpreter/hardware manifest.
- Công thức/native/operation và các artifact bắt buộc khác theo scope release đã chọn; không bịa artifact rỗng để đủ hash.

Khóa candidate/code/config và metric definitions trước khi mở holdout. Calibration chỉ dùng để đặt ngưỡng review; development để sửa lỗi. Holdout dùng theo custody và giao thức đã khóa; nếu xem kết quả để điều chỉnh, ghi exposure và lập phiên nghiệm thu độc lập phù hợp thay vì gọi lại cùng holdout là chưa thấy.

`status: LOCKED`, approved_by hoặc hash chỉ hợp lệ khi hồ sơ thật đáp ứng yêu cầu. Markdown này chưa có quyền biến protocol DRAFT thành LOCKED. Preflight `INPUTS_VERIFIED` chỉ xác nhận readiness input; release gate và quyết định nghiệm thu là bước riêng.

## 6. Các lệnh điểm vào và tình trạng hiện tại

Chạy từ root bằng Python supervisor. Các lệnh help chỉ để tra CLI; chưa tạo corpus:

```powershell
.\.venv\Scripts\python.exe -B -m src.ocr.cli.collect --help
.\.venv\Scripts\python.exe -B -m benchmark.scientific_evaluation.protocol_preflight --help
```

Lệnh mẫu preflight đã thực chạy trong audit:

```powershell
.\.venv\Scripts\python.exe -B -m benchmark.scientific_evaluation.protocol_preflight "docs/quality_assurance/templates/benchmark_acceptance_protocol.example.yaml"
```

Exit 1, `NOT_READY_FOR_ACCEPTANCE_MEASUREMENT`: protocol DRAFT chưa LOCKED. [Bằng chứng](../../scratch/dev_sessions/20261107-qa-repository-audit/draft-preflight-probe.json). Chưa tạo assignments, source metadata, nhãn người, khóa dataset hoặc ngưỡng mới. Điều kiện tiếp tục là dữ liệu và hồ sơ thật đáp ứng công cụ sẵn có; phần thiếu giữ `NOT_EVALUATED`.

## 7. Nguồn GT cho cổng dấu v8 (V8-013, V8-011)

**Quy trình LOCKED v1 ngày 09/11/2026**, do người dùng quyết trong phiên chat. Khóa máy đọc là [`locks/v8_011_text_layer_procedure_lock_v1.json`](locks/v8_011_text_layer_procedure_lock_v1.json), sha256 `b0c20a846bf53fcac47cce73148f83fd523b7ed37adb5bfe8bf4b484a2bb2e0a`. File này do `scripts/lock_text_layer_procedure.py` tạo; lệnh `--verify <khóa> --pdf-root inputs` dựng lại đúng từng byte và khớp sha256 của 9 PDF (exit 0).

Khóa v1 chỉ cố định quy trình. Nó chưa phải gói nghiệm thu `ocr-benchmark-acceptance-proposal-v1` ở §5, và chưa thay việc khóa đủ bốn partition theo §2. Mọi trang vẫn `NOT_VERIFIED` cho tới khi người duyệt sàng lọc xong, và chất lượng giữ `NOT_EVALUATED`. Muốn đổi một mục dưới đây thì tạo khóa v2 trước khi xem kết quả đo; không sửa v1.

### 7.1 Quyết định đã khóa

- **Nguồn:** (b) text layer của PDF born-digital, theo [04 §5](../../cai%20tien%20v2/04_DAC_TA_DO_DAU_9999.md). Nguồn (a) chỉ dùng cho stress test. Nguồn (c) và (d) chưa chọn. Nguồn (e) bị cấm: output model, đồng thuận engine, output pipeline, nhãn AI.
- **Vai trò:** người duyệt (reviewer) và custodian holdout đều là người dùng (Git `VuTuanAn1403`). Tác nhân AI chỉ là operator: chạy công cụ tất định, tạo worklist, tính số. Operator không quyết nhãn, không điền sẵn quyết định và không mở holdout.
- **Split:** cả 9 PDF trong `inputs/` là `development_only`, vì đều đã có exposure. AGR, ASM và VIC đã có exposure từ trước. AAA, BCE, BHN và VIC đã dùng để dựng whitelist alias ([alias-rules-kaggle](../../scratch/dev_sessions/20261106-alias-rules-kaggle/handoff-before-merge.md)). AAA và ABT có so sánh keyword before/after ([keyword-continuity](../../scratch/dev_sessions/20261103-keyword-continuity/corpus_final/report.json)). Crop của BHN đã được AI xem ([retry-alias-rotation](../../scratch/dev_sessions/20261106-retry-alias-rotation/session.md)). Holdout sẽ là PDF mới (§7.4 F).
- **Tham số:** α = 0,05 một phía, cận Clopper-Pearson, yêu cầu p_U ≤ 10⁻⁴. Kế hoạch k = 0, nên cần N_eff ≥ 29.956. Metric chính là `DSER_strict`; báo kèm DER_VN_v1, `base_mismatch_slots`, dấu thừa và dấu chưa tổ hợp. Mệnh đề công bố theo 04 §1.
- **Seed và thứ tự:** seed là `V8-011-LOCK-20261109`. Trong mỗi PDF, trang được xếp theo sha256 tăng dần của chuỗi `seed:pdf_sha256:page`, nên không phụ thuộc bộ sinh ngẫu nhiên của ngôn ngữ nào.

### 7.2 Quy mô và trạng thái từng PDF

Nguồn số liệu là inventory [`v8_011_text_layer_inventory_v2_20261109.json`](../../scratch/v8/v8_011_text_layer_inventory_v2_20261109.json), sha256 `129f18dc87b1f83cc5ee7453454ce9ffddc87bda4f7e399b1270dde31632bf96`, chạy tại `2af5454`. Bản `..._2af5454_...` trùng bytes. Một trang là `CANDIDATE` khi có chữ hiển thị (không phải lớp OCR ẩn), mọi font tổ hợp đều có ToUnicode, và không có chẩn đoán hỏng. Đây vẫn chỉ là ứng viên, chưa phải GT.

| PDF | Producer | Trang ứng viên | Slot | Khóa v1 | Worklist sàng lọc |
| --- | --- | ---: | ---: | --- | --- |
| AAA 2020 | iLovePDF | 157/232 | 67.787 | Cần sàng lọc | 8 trang, 3.731 slot |
| ABT 2020 | (trống) | 2/43 | 40 | Loại: dưới 2.995 slot | — |
| ACL 2022 | SECnvtToPDF V1.0 | 0/24 | 0 | Loại: không có text layer | — |
| AGR 2020 | 3-Heights PDF Security Shell / pdcat | 83/84 | 32.150 | Cần sàng lọc | 10 trang, 3.132 slot |
| AGR 2022 | (trống) | 101/102 | 33.448 | Cần sàng lọc | 11 trang, 3.097 slot |
| ASM 2022 | GPL Ghostscript 9.53.3 | 94/164 | 29.912 | Cần sàng lọc | 9 trang, 3.022 slot |
| BCE 2022 | pdf | 62/62 | 23.460 | Cần sàng lọc | 4 trang, 3.226 slot |
| BHN 2022 | PDF24 | 72/75 | 28.497 | Cần sàng lọc | 12 trang, 3.511 slot |
| VIC 2020 | iLovePDF | 149/152 | 130.393 | Cần sàng lọc | 4 trang, 4.475 slot |

Tổng cộng 7 PDF cần sàng lọc, với 58 trang và 24.194 slot. Trước sàng lọc, development còn 345.647 slot trên 717 trang có slot. Mỗi trang là một cụm: cỡ cụm trung bình m̄ = 482,07, cỡ cụm có trọng số m_w = Σm²/Σm = 835,03. Danh sách trang của từng worklist và thứ tự đầy đủ nằm trong khóa.

### 7.3 Tiêu chí chọn mẫu cho mệnh đề ≥ 99,99%

1. **Phạm vi:** báo cáo thường niên tiếng Việt dạng PDF born-digital, luồng OCR trên ảnh render của chính trang đó, profile `unified_gpu_full_ocr`. Không ngoại suy sang scan hay luồng native.
2. **Đơn vị và cụm:** đơn vị là slot `DSER_strict` trên text layer sau NFC. Cụm là trang. Báo thêm k và N theo từng công ty.
3. **Điều kiện vào mẫu**, xét lần lượt:
   - PDF có ít nhất 2.995 slot ứng viên và đã được sàng lọc chấp nhận (§7.4 B).
   - Trang là `CANDIDATE`, có ít nhất một slot, và text layer không còn dấu chưa tổ hợp sau NFC (`diacritic_acceptance.py::uncomposed_vietnamese_marks`, cùng chẩn đoán `UnicodeNormalizer.analyze` mà inventory đã dùng).
   - Span có glyph thấy được trên ảnh render: không dùng render mode 3, nằm trong CropBox, không bị ảnh đè và có màu khác nền. Chữ nằm trong ảnh mà không có text layer thì ở ngoài mẫu số và được báo riêng.
4. **Lấy toàn bộ, không lấy mẫu con:** mẫu đo gồm mọi slot đủ điều kiện của partition. Không chọn hay bỏ trang theo kết quả OCR. Sau khi đã xem kết quả đo thì không loại thêm PDF hay trang nào.
5. **Cỡ mẫu:** custodian kiểm trước khi chạy OCR và chỉ dùng text layer. Custodian tính N và m_w của holdout. Holdout hợp lệ khi N ≥ 29.956 và ⌊N / DEFF⌋ ≥ 29.956, với DEFF = 1 + (m_w − 1)·ρ_U. Ở đây ρ_U là cận trên 95% của tương quan nội cụm theo trang, ước lượng trên development. Nếu thiếu slot thì bổ sung PDF trước khi chạy OCR. Ví dụ: với m_w = 835 và ρ_U = 0,005 thì DEFF ≈ 5,17, nên cần N khoảng 154.900 slot.
6. **Thiếu ρ:** nếu không ước lượng được ρ trên development, chẳng hạn vì quá ít lỗi, thì chỉ công bố mệnh đề trong mẫu. Mệnh đề tổng quát khi đó giữ `NOT_EVALUATED` (04 §4).
7. **Ghép trước khi căn:** ghép dòng OCR với span text layer theo bbox rồi mới căn ký tự. Nhờ vậy lỗi thứ tự đọc không bị đếm thành lỗi xóa slot. Slot GT không có dòng OCR tương ứng vẫn tính là lỗi xóa.
8. **Identity:** đo trên output mới của identity đã khóa tại thời điểm đo. Production hiện là khóa `BASELINE-V8-20261109-003` (PP-OCRv6_medium_det, fingerprint extraction `ccdbe84a3691d645`). Không dùng output của khóa 002 (PP-OCRv4).

### 7.4 Cơ chế người duyệt

**A. Độc lập.** Người duyệt chỉ quyết dựa trên ảnh render của đúng PDF (khớp sha256), phóng to tới khi đọc rõ dấu. Màn hình duyệt không hiện confidence, nguồn của chuỗi hay tên engine.

**B. Sàng lọc text layer**, làm trước khi đo và không xem output OCR. Với mỗi PDF cần sàng lọc, người duyệt đi theo worklist trong khóa. Trên từng trang, người duyệt so mọi chữ có slot dấu của text layer với ảnh và ghi một trong ba kết quả:
- `MATCH`;
- `MISMATCH`, kèm nguyên nhân: ToUnicode, font nhúng, ký tự bị thay, thiếu dấu, thừa dấu hoặc chữ ẩn;
- `UNRESOLVED`. Chữ loại này không tính vào 2.995 slot; người duyệt tiếp tục với các trang sau theo `order` trong khóa.

Kết luận cho từng PDF:
- 0 `MISMATCH` trên ít nhất 2.995 slot `MATCH`: chấp nhận PDF. Khi đó cận trên 95% của tỷ lệ sai text layer là 10⁻³.
- Có ít nhất một `MISMATCH` đã xác nhận: loại cả PDF và ghi nguyên nhân theo producer. Muốn chỉ loại theo font thay vì cả PDF thì phải có khóa v2.

Sai lệch được ghi theo producer để biết phần mềm nào làm hỏng text layer. Các bước re-encode của iLovePDF, Ghostscript và PDF24 có thể làm hỏng ToUnicode.

**C. Phân xử chênh lệch**, làm sau lần chạy đo. Người duyệt xem mọi slot mà OCR khác text layer: lỗi `DSER_strict`, `base_mismatch_slots`, dấu thừa và dấu chưa tổ hợp. Màn hình hiện crop ảnh và hai chuỗi A/B theo thứ tự lấy từ seed, không ghi bên nào là OCR. Quyết định được tính như sau:
- Text layer đúng: tính là lỗi OCR.
- OCR đúng: tính là lỗi GT. Sửa tham chiếu tại slot đó và đếm số lỗi GT riêng.
- Cả hai đều sai: tính là lỗi OCR, đồng thời sửa tham chiếu.
- `UNRESOLVED`: tính là lỗi OCR để giữ thế bảo thủ, và báo riêng.

Sau khi phân xử không loại PDF hay trang nào. Slot mà OCR trùng text layer thì không qua phân xử. Vì vậy, nếu cả hai cùng sai giống hệt nhau thì không phát hiện được. Rủi ro đó chỉ được giới hạn bởi cận 10⁻³ của bước sàng lọc và phải được công bố.

**D. Kiểm lại mù**, vì chỉ có một người duyệt. Sau ít nhất 7 ngày, người duyệt duyệt lại 10% các quyết định sàng lọc và phân xử (tối thiểu 50 mục), không xem quyết định cũ. Mẫu được chọn theo sha256 tăng dần của `seed:recheck:<decision_id>`. Báo tỷ lệ nhất quán. Mục nào lệch thì duyệt lần ba; nếu vẫn lệch thì chuyển thành `UNRESOLVED`.

**E. Hồ sơ.** Mỗi quyết định là một dòng JSONL gồm: `decision_id`, `pdf_sha256`, trang, bbox và offset ký tự trong text layer, sha256 của crop, thứ tự A/B đã hiện, quyết định, nguyên nhân, người duyệt, thời điểm có timezone (Asia/Bangkok) và commit của công cụ. File được seal bằng sha256 rồi ghi vào khóa phiên bản kế tiếp. Không sửa file đã seal; cần sửa thì tạo file mới.

**F. Custodian và holdout mới.** Custodian thu thập PDF born-digital tiếng Việt của các công ty ngoài AAA, ABT, ACL, AGR, ASM, BCE, BHN và VIC. Các PDF này được lưu ngoài `inputs/` và ngoài repo, kèm manifest (sha256, nguồn, ngày, timezone) ghi trước mọi lần chạy OCR. Các bước tiếp theo, theo thứ tự:
1. Chạy `inventory_text_layers.py` trên các PDF đó.
2. Tạo khóa holdout bằng `lock_text_layer_procedure.py --partition holdout --exclude-locked <khóa development>`. Lệnh này từ chối PDF trùng bytes; trùng công ty thì custodian tự kiểm.
3. Sàng lọc theo mục B.
4. Kiểm cỡ mẫu theo §7.3 mục 5.
5. Chạy OCR **một lần** trên identity đã khóa (04 §7).

Holdout nào đã bị xem hoặc dùng để chỉnh thì chuyển thành development và ghi exposure.

**G. Giới hạn phải công bố.** Chỉ có một người duyệt, và người đó cũng là người phát triển, nên không đo được đồng thuận giữa người duyệt. Lỗi trùng nhau giữa OCR và text layer không phát hiện được. Quy trình chỉ áp dụng cho PDF born-digital.

### 7.5 Còn thiếu trước khi đo

- Ngày 10/11 người duyệt đã sàng lọc 7 PDF development: cả 7 `ACCEPTED` (24.172 slot `MATCH`, 0 `MISMATCH`). Bản niêm phong nằm ở `scratch/v8/screening/sealed/`.
- Kiểm lại mù 10% (1.552 chữ, §7.4 D) làm từ 17/11, bằng phiếu ở `scratch/v8/screening/recheck/`.
- Holdout mới chưa được thu thập.

Công cụ đã có từ 09/11 (chỉ chạy CPU, không đọc output OCR trước khi sàng lọc xong):

| Bước | Công cụ |
| --- | --- |
| Đơn vị text layer và lọc glyph hiển thị | `benchmark/ground_truth_tools/text_layer_reference.py` |
| Phiếu sàng lọc (B), niêm phong (E), kiểm lại mù (D) | `scripts/screen_text_layer.py build`, `seal`, `recheck`, `agreement` |
| Khóa v2 các lựa chọn §7.6 và ghim công cụ | `scripts/lock_text_layer_measurement.py` |
| Đo OCR so với text layer đã chấp nhận, ghép theo bbox (§7.3 mục 7) | `scripts/measure_text_layer_diacritics.py` |
| Phân xử mù A/B (C) | `scripts/adjudicate_text_layer_diacritics.py build`, `seal` |
| Mở phiếu và tự lưu từng quyết định ra `<phiếu>/autosave/` | `scripts/serve_review_sheets.py` |
| ρ và cận trên, DEFF holdout | `benchmark/scientific_evaluation/cluster_correlation.py` |

`native_diacritic_replay.py` đo luồng native, không phải bộ ghép OCR với text layer. `check_vietnamese_charset.py` kiểm từ điển ký tự của model, không kiểm trang.

### 7.6 Khóa đo v2, v3, v4 (LOCKED 10/11/2026; v4 hiện hành)

Các lựa chọn dưới đây nằm trong công cụ nhưng chưa có trong khóa v1. Người dùng (VuTuanAn1403) duyệt nguyên bản nháp r2 và khóa chúng trong v2 ngày 10/11/2026, trước mọi kết quả đo. Luồng đo là `text_corrected`.

- **Khóa hiện hành v4:** `docs/quality_assurance/locks/v8_011_text_layer_measurement_lock_v4.json`, sha256 `c328379577624bbc0a8f1f66a31ce8b9cf233c884a393b5ed0449b59868b5ae2`. Khóa giữ nguyên v3 và thêm cỡ mẫu phân xử. Ngày 10/11 người dùng chọn chỉ phân xử một mẫu 3.000/9.733 mục trên development. Mẫu chọn theo sha256 tăng dần của `seed:adjudication-sample:<item_id>`; mọi mục ngoài mẫu tính là `UNRESOLVED`, tức là lỗi (đếm bảo thủ). Seal báo thêm tỷ lệ kết quả của mẫu với khoảng Clopper-Pearson, và một ước lượng có nhãn `ESTIMATE_NOT_A_GATE`. Holdout vẫn phải phân xử đủ.
- **Khóa v3 (đã bị thay):** `docs/quality_assurance/locks/v8_011_text_layer_measurement_lock_v3.json`, sha256 `396b1fd346098e1139dc8e68ea4cab5aeb7d403b9bcf04d73ee79be461639494`. Người dùng chọn quy tắc ghép `bbox-connected-groups-phase-a-v1`; khóa ghi 7 bản niêm phong sàng lọc.
- **Khóa v2 (đã bị thay):** `docs/quality_assurance/locks/v8_011_text_layer_measurement_lock_v2.json`, sha256 `a0dc5712dd767120aff2fe3031829d7195db2e101658429e5d61ed6ead0dc616` (byte LF, ghim qua `.gitattributes`).
- **Kiểm lại:** `scripts/lock_text_layer_measurement.py --verify <khóa>`.

Khóa v2 do `scripts/lock_text_layer_measurement.py` tạo:

- Khóa gắn với khóa v1 qua sha256 và ghi giá trị của 7 lựa chọn, đọc thẳng từ mã.
- Khóa ghim byte của 10 file công cụ (kể cả `diacritic_acceptance.py`, nơi quyết định đơn vị có dấu trơ), đọc CRLF thành LF. Sửa bất kỳ file nào trong số đó là khóa mất hiệu lực.
- `measure_text_layer_diacritics.py` từ chối chạy khi thiếu khóa v2 ở trạng thái `LOCKED_PROCEDURE`, cùng khóa v1 và cùng luồng đo. `adjudicate_text_layer_diacritics.py` kiểm lại khóa này ở cả hai bước `build` và `seal`.
- Bản nháp đã duyệt: `scratch/v8/v8_011_measurement_lock_v2_draft_r2_20261110.json` (sha256 `d1557cc0…`). Khóa v2 khác bản nháp ở ba chỗ: trạng thái, quyết định và luồng đo.
- Muốn đổi bất kỳ lựa chọn nào thì phải lập khóa mới. Phép đo đã chạy theo khóa cũ vẫn ghi sha256 của khóa đó.

**Phát hiện ở lần đo development đầu tiên (10/11).** Báo cáo: `scratch/v8/v8_011_measurement_dev_003_20261110.json`.

- Đo theo khóa v2 cho `DSER_strict` 83.127/345.300 slot, trong đó 78.192 là slot bị xóa.
- 71.884 slot bị xóa nằm trong item bảng (`t`). Lý do: mục 3 chỉ ghép text layer với item `b`, nên chữ trong bảng bị tính là OCR bỏ sót.
- Vì vậy kết quả này không phải độ chính xác dấu, và chưa dựng phiếu phân xử.
- Khóa v3 (`ocr-v8-text-layer-measurement-lock-v3`) biến quy tắc ghép thành một lựa chọn phải khóa, có ba giá trị:
  - `bbox-connected-groups-v1`: như v2;
  - `bbox-connected-groups-phase-a-v1`: ghép với dòng OCR pha A (`text_evidence.items`), phủ cả bảng;
  - `bbox-connected-groups-no-tables-v1`: dòng text layer nằm trong bảng ra khỏi mẫu (`TABLE_REGION_SLOTS`).
- Khóa v3 ghi sha256 của 7 bản niêm phong sàng lọc (§7.4 E), và phép đo phải dùng đúng 7 bản đó. Khóa cũng ghi khóa v2 là khóa bị thay thế, kèm lý do. Khóa v2 không còn cho phép đo.
- Bản nháp v3: `scratch/v8/v8_011_measurement_lock_v3_draft_20261110.json` (`8794b17a…`). Người dùng chọn ghép pha A, và khóa v3 LOCKED ngày 10/11.

**Đo development theo khóa v3 (10/11).** Báo cáo: `scratch/v8/v8_011_measurement_dev_003_v3_20261110.json`; trong mẫu, trước phân xử:

- `DSER_strict`: 13.751/345.300 slot, trên 717 trang.
- Lỗi theo loại: dấu thanh 4.421, đ 601, dấu mũ/móc 430, dấu thừa 366, slot bị xóa 7.933.
- 3.195 slot bị xóa thuộc các khối mà pha A đánh `REJECTED` trong vùng ảnh, tức chính lỗi đặc tả 13 §4.1.
- ρ = 0,022 (cận trên 0,025).
- 6.307 đơn vị chờ phân xử mù (§7.4 C).
- Đây là số đo trên development, không phải mệnh đề tổng quát. Số đếm chỉ chốt sau khi phân xử và kiểm lại mù.
- Dữ liệu dùng ở đây là development nên được phép chỉnh; holdout vẫn chỉ đo một lần, theo khóa đã cố định trước khi xem.

1. **Glyph hiển thị:** render trang hai lần ở 144 DPI, nguyên trạng và sau khi gỡ mọi glyph bằng redaction (giữ ảnh và nét vẽ). Ký tự gốc hiển thị khi có ít nhất 2 pixel đổi trong hộp của nó. Ký tự có hộp rộng 0 (thành phần ligature như `h` trong `Th`) lấy kết quả của ký tự gốc đứng trước. Một chữ vào mẫu khi mọi ký tự gốc hiển thị; chữ hiển thị một phần bị loại và báo riêng. Trên 58 trang worklist: BHN có 10 chữ nằm dưới ảnh trùng nội dung (14 slot), BCE có 4 chữ bị che một phần (8 slot); 5 PDF còn lại không có chữ nào bị loại.
2. **Đơn vị sàng lọc:** từng chữ có slot dấu. Người duyệt có thể ghi MATCH cho các chữ chưa quyết của một dòng bằng một thao tác; bản ghi đánh dấu `bulk: "line"`. Slot MATCH chỉ được đếm trên trang đã quyết đủ, theo thứ tự trong khóa.
3. **Ghép OCR với text layer:** từ khóa v3, phía OCR là dòng pha A (`text_evidence.items`); khóa v2 dùng mục `b` của `extraction.json`. Dòng OCR và dòng text layer hiển thị được nối khi giao nhau theo chiều ngang và chồng nhau ít nhất một nửa chiều cao nhỏ hơn. Mỗi nhóm liên thông là một đơn vị, xếp theo hàng rồi từ trái sang phải. Dòng text layer không có OCR thì tính toàn bộ slot là lỗi xóa. Dòng OCR không có text layer được báo riêng.
4. **Luồng đo:** `text_corrected`, khóa ngày 10/11. Công cụ vẫn bắt chọn luồng rõ ràng và từ chối luồng khác luồng đã khóa.
5. **Cổng:** số lỗi là `dser_errors` của `DSER_strict` trên `ref_slots`, đúng tham số `metric` của khóa v1. Từ 10/11, hai cổng `diacritic_acceptance.py` và `release_gate.py` cũng đếm theo `DSER_strict` như đặc tả 04 §3. DER_VN_v1 chỉ còn được báo bên cạnh.
6. **ρ_U:** cận trên của profile likelihood beta-binomial (một phía 95%). Một mô phỏng với tỷ lệ lỗi 0,001–0,01 cho thấy cận F của ANOVA chỉ phủ ρ thật ở 58–89% số lần, còn bootstrap theo trang ở 58–85%; cả hai sẽ làm DEFF nhỏ hơn thực tế. Profile likelihood phủ ở 92–96%.
7. **Phân xử:** mỗi đoạn token khác nhau có slot hoặc dấu là một mục. `Cả hai sai` bắt buộc người duyệt gõ chữ đúng. `Không quyết được` tính cả slot lệch chữ gốc của đoạn đó là lỗi.
