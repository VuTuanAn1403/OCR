# Phương pháp Ground Truth và khóa benchmark

Ngày 07/11/2026. **DRAFT — chưa khóa corpus/split/GT, chưa phê duyệt protocol hoặc ngưỡng.** Tài liệu này chuẩn hóa cách chuẩn bị, tương thích công cụ hiện có; không tự tạo một bộ đáp án. Tình trạng chưa có người A/B đã được bàn giao: không hỏi lại phân công, không dùng AI/model output thay GT. Chất lượng corpus giữ `NOT_EVALUATED`.

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

**Quyết định ngày 09/11/2026 (người dùng, trong phiên chat):** cổng dấu 99,99% dùng nguồn **(b) text layer của PDF born-digital** theo [04 §5](../../cai%20tien%20v2/04_DAC_TA_DO_DAU_9999.md). Dữ liệu tổng hợp (a) chỉ dùng cho stress test. Nguồn (c) và (d) chưa chọn. Nguồn (e) vẫn bị cấm: output model, đồng thuận engine, output pipeline, nhãn AI.

**Chưa có:** người duyệt, custodian holdout, split, α/k và kế hoạch design effect. Vì vậy V8-013 còn `IN_PROGRESS`, mục này còn **DRAFT**, và chất lượng giữ `NOT_EVALUATED`.

### 7.1 Quy mô ứng viên (đã đo, chưa phải GT)

Lệnh `scripts/inventory_text_layers.py inputs --report scratch/v8/v8_011_text_layer_inventory_2af5454_20261109.json`, chạy tại `2af5454`, cho 720/938 trang `CANDIDATE` với 345.687 slot dấu. Trang `CANDIDATE` là trang có chữ hiển thị (không phải lớp OCR ẩn), font tổ hợp có ToUnicode, và không có chẩn đoán hỏng.

| PDF | Trang ứng viên | Slot | Producer |
| --- | ---: | ---: | --- |
| AAA 2020 | 157/232 | 67.787 | iLovePDF |
| ABT 2020 | 2/43 | 40 | (trống) |
| ACL 2022 | 0/24 | 0 | SECnvtToPDF V1.0 |
| AGR 2020 | 83/84 | 32.150 | 3-Heights PDF Security Shell / pdcat |
| AGR 2022 | 101/102 | 33.448 | (trống) |
| ASM 2022 | 94/164 | 29.912 | GPL Ghostscript 9.53.3 |
| BCE 2022 | 62/62 | 23.460 | pdf |
| BHN 2022 | 72/75 | 28.497 | PDF24 |
| VIC 2020 | 149/152 | 130.393 | iLovePDF |

### 7.2 Quy trình xác minh đề xuất (DRAFT, cần khóa trước khi đo)

1. **Khóa trước khi xem kết quả OCR:** danh sách trang, seed lấy mẫu, α = 0,05, k và mệnh đề công bố theo 04 §1.
2. **Xác minh theo producer:** với mỗi producer, người duyệt so text layer với ảnh render trên mẫu trang ngẫu nhiên (seed đã khóa) và ghi sai lệch theo loại slot. Producer có sai lệch hệ thống thì loại cả nhóm. Re-encode của iLovePDF, Ghostscript và PDF24 có thể làm hỏng ToUnicode.
3. **Kiểm ký tự:** `scripts/check_vietnamese_charset.py` loại trang có dấu chưa tổ hợp hoặc code point lạ sau NFC.
4. **Phạm vi hiển thị:** chỉ tính span text layer có glyph thấy được trên ảnh render (loại chữ bị cắt, chữ trắng, lớp ẩn). Chữ trong ảnh không có text layer nằm ngoài mẫu số và báo riêng.
5. **Ghép trước khi căn:** thứ tự text layer khác thứ tự đọc của OCR. Phải ghép dòng OCR với span text layer theo bbox trước khi căn ký tự cho `DSER_strict`, nếu không lỗi thứ tự sẽ bị đếm thành lỗi xóa slot.
6. **Split theo §2:** AGR, ASM và VIC đã có exposure, nên chỉ dùng cho development. AAA, BCE và BHN là ứng viên holdout nếu audit exposure xác nhận. ACL không có text layer.
7. **Design effect:** ước lượng ρ theo cụm trang trên development. Với khoảng 410–430 slot mỗi trang, holdout chỉ có AAA (67.787 slot) cần ρ ≤ 0,0029 để N_eff ≥ 29.956. Holdout gồm AAA, BCE và BHN (119.744 slot) cần ρ ≤ 0,0073. Không ước lượng được ρ thì chỉ công bố mệnh đề trong mẫu.
8. **Identity:** đo trên output mới của identity production hiện tại, tức khóa `BASELINE-V8-20261109-003` (detector PP-OCRv6_medium_det, fingerprint extraction `ccdbe84a3691d645`). Không dùng output của khóa 002 (PP-OCRv4) để kết luận về production hiện tại.
