# Bàn giao chi tiết dự án OCR PDF (13/11/2026, 23:40 Asia/Bangkok)

Tài liệu này chụp lại toàn bộ trạng thái dự án tại thời điểm viết, dành cho người hoặc phiên tiếp quản. Bản tóm tắt ngắn hằng ngày vẫn là [HANDOFF.md](HANDOFF.md). Nguồn trạng thái duy nhất là `cai tien v2/10_TRANG_THAI_V8.json`; xem nhanh bằng `.venv/Scripts/python.exe scripts/check_knowledge_map.py --summary`.

Quy ước: mọi số đo dưới đây là **development**. Tham chiếu là text layer đã sàng lọc, không phải GT độc lập, nên chất lượng vẫn `NOT_EVALUATED`. "Sửa/sai" là fix/harm theo cặp, không phải accuracy.

## 1. Dự án đang ở đâu

**Pipeline sản phẩm chạy được đầu-cuối**: PDF → OCR GPU (phát hiện dòng PP-OCRv6, nhận dạng VietOCR) → layout và bảng (Docling) → `result.md`, Excel đếm keyword, SQLite. Mã nguồn vẫn `PIPELINE_VERSION 7.0.0`; v8.0 là nhãn chương trình nâng cấp.

**Chương trình v8 chưa xong**, và điểm nghẽn là dữ liệu kiểm định chứ không phải mã:

| Hạng mục | Trạng thái |
| --- | --- |
| Backlog V8 (38 mục) | 25 `DONE`, 12 `IN_PROGRESS`, 1 `TODO` (V8-160) |
| Tầng L0–L9 | 8 tầng `IMPLEMENTED`; L6 (bảng/công thức) và L8 (keyword) `PARTIAL`; chất lượng của mọi tầng `NOT_EVALUATED` |
| Khoảng trống G01–G10 | 1 `IMPLEMENTED` (G06 taxonomy), 9 `PARTIAL` |
| Lộ trình | P0 khóa baseline `DONE`; R1, P1–P9 `IN_PROGRESS` |
| Cổng bảo toàn dấu 99,99% | `NOT_EVALUATED`. Dev đo được khoảng 3,98% lỗi DSER, còn rất xa mục tiêu 0,01% |
| Bản đồ kiến thức | 0 lỗi, 0 STALE; `verified_head` = `8e4d342` |

Phần lớn các mục `IN_PROGRESS` đang chờ người: nhãn hoặc quyết định của người duyệt, hoặc PDF holdout bổ sung. Máy vẫn còn bốn việc, liệt kê ở §11 giai đoạn 1:
- lượt OCR holdout còn lại;
- chạy production trên OmniDocBench;
- chạy end-to-end ứng viên nhận dạng;
- merge nhánh tích hợp.

## 2. Mốc Git

- Nhánh làm việc: `v8-diacritic-bounds-keyword-challenger`, PR [#1](https://github.com/VuTuanAn1403/OCR/pull/1). HEAD `77e5050`, hơn `origin` 23 commit, **chưa push**.
- Nhánh tích hợp: `v8-integration-keyword-pending` (commit `3d44756`), nằm ở worktree `C:\kk_2\OCR_pdf_wt_v8int`. Nhánh này đổi `src/`, nên **chỉ merge sau khi batch GPU holdout xong**; nếu merge sớm, batch sẽ dừng vì `IdentityMismatch`.
- Commit chính ngày 13/11:
  - `a474cf1`: khóa đo v8 (`ƣ`→`ư`) và khóa quy trình holdout.
  - `959c003`: chuyển quyết định phân xử sang phiếu v8.
  - `8e4d342`: challenger `O2O`/`020`, gói duyệt Q1–Q10, ứng viên V8-065.
  - `5de92d0`: ghim và đo 3 ứng viên nhận dạng (Q9).
  - `77e5050`: ghi các trả lời Q1–Q10, script chuỗi bằng chứng.
  - `ff49073`, `af379b5`, `afaab3f`, `b9dd432`, `eb2b21f`: sổ sách và `verified_head`.
- Hồi quy CPU: 2.693 test đạt, 1 bỏ qua trên `8e4d342` (`scratch/runs/20261113-171130-c290d927`). Trên nhánh tích hợp: 2.696 đạt, 3 bỏ qua.

## 3. Baseline và khóa

| Khóa / output | Vai trò |
| --- | --- |
| `BASELINE-V8-20261113-001` → `output/v8_006_arena1536_20261112` | Baseline hiện hành (Q1 A), 9/9 PDF `MATCH`, 938 trang |
| `BASELINE-V8-20261113-002` → `output/v8_007_arena1536_upscale2_20261112` | Candidate phóng dòng ×2 (`config/candidates/v8_050_line_upscale2.yaml`) |
| `docs/quality_assurance/locks/v8_011_text_layer_procedure_lock_v1.json` | Quy trình text layer development (9 PDF) |
| `docs/quality_assurance/locks/v8_011_text_layer_measurement_lock_v8.json` (`c2a61bf4`) | Khóa đo hiện hành: đọc `ƣ`/`Ƣ` thành `ư`/`Ư` |
| `docs/quality_assurance/locks/v8_011_text_layer_procedure_lock_holdout_v1.json` | Quy trình holdout: 13 PDF, 6 PDF cần sàng lọc |

## 4. Trạng thái từng mục đang mở

| ID | Việc | Đã có | Còn thiếu |
| --- | --- | --- | --- |
| V8-011 | Text layer làm tham chiếu dấu | 7 PDF dev sàng lọc `ACCEPTED`; khóa v8; dev 006: 13.777/346.393 lỗi trước phân xử; phiếu v8 9.485 mục, đã nhận 5.011 quyết định chuyển từ v7 | Người duyệt chấm 4.474 mục (VIC 3.763, BHN 434, ASM 277) rồi `seal`; kiểm lại mù sàng lọc từ 17/11 |
| V8-012 | Cỡ mẫu holdout | 13 PDF khóa; `BCE_2022`, `BHN_2022` trùng byte dev nên loại; 6 PDF, 163.662 slot | Cổng chỉ đạt khi ρ_U ≤ 0,0046, trong khi dev đo khoảng 0,025: cần khoảng 4–5 lần số slot. Người duyệt sàng lọc 6 PDF; custodian bổ sung PDF born-digital của công ty mới |
| V8-030 | Khôi phục Đ trong từ viết tắt | Challenger `acronym_diacritics.py`. Khóa v8: 006 282 sửa / 2 sai; trên ×2 chỉ còn 4/2, vì phóng ×2 đã sửa gần hết | Đo trên phiếu đã seal hoặc trên holdout |
| V8-050 | Tiền xử lý, phóng ×2 | Khóa v8: DSER 13.777 → 11.671, 1.780 sửa / 307 sai; keyword 3/0 | Đo holdout (Q3 A; batch đang chạy) |
| V8-060 | Detector | PP-OCRv6 vào production 09/11; so v4 bằng đồng thuận | Nhãn GT lô 3 (9 trang) |
| V8-065 | Nhận dạng | 3 ứng viên trên 3.000 crop, 35.118 slot; DSER production 1.223. Lỗi DSER, kèm số crop sửa/sai: VietOCR `vgg_transformer` 815 (276/69), AsterNet 482 (363/188), Tesseract `vie` 842 (371/189) | Chọn ứng viên chạy end-to-end (exit gate: crop rồi end-to-end); đo holdout |
| V8-070 | Layout | PP-DocLayout_plus-L: 558 vùng trên 44 trang | Nhãn GT lô 4 |
| V8-071 | Thứ tự đọc | Challenger 8 quy tắc: đồng thuận 0,951 với production; PP-StructureV3 0,89 | Nhãn GT lô 2 (8 trang) |
| V8-080 | Bảng, số, ownership | Dòng mất 3.652 → 0; ô số không truy được 292 → 2; phiếu 72 số seal, kết quả trùng ở 003/006/007 | Nhãn GT lô 1 (18 trang bảng) để đo TEDS |
| V8-085 | Công thức | 9 PDF dev không có công thức; OmniDocBench được duyệt (Q8 A, chỉ đo nội bộ); đã tải 223 trang tiếng Anh có công thức display, chọn trước khi dự đoán (`scratch/v8/v8_085_omnidocbench_aa1ee96d`, 115 MB) | Chạy production và chấm theo `FORMULA_ACCEPTANCE_POLICY_V7` |
| V8-100 | Đếm keyword | So text layer 718 trang: literal thiếu 28 / thừa 2; tầng chờ duyệt (alias + `020`↔`O2O`) còn thiếu 14, 0 ứng viên sai. Q6 B, Q7 A đã làm trên nhánh tích hợp | Merge nhánh tích hợp; GT keyword |
| V8-140 | Hồ sơ quyết định E2E | Q1–Q10 đã trả lời; chưa PROMOTE (Q2 B) | Kết quả holdout |
| V8-160 | Nâng 8.0.0 | — | Chỉ sau khi PROMOTE (Q5 A) |

## 5. Quyết định của người duyệt (13/11)

Nguyên văn: "Q1 A Q2 B Q3 A Q4 A Q5 A Q6 B Q7 A Q8 A Q9 1 2 3 Q10 A VÀ B còn lại tự động hóa quy trình". Chi tiết từng câu ở [gói duyệt](../../cai%20tien%20v2/bao_cao/GOI_DUYET_V8_20261113.md).

- **Baseline:** 006.
- **Nhóm sửa bất biến dữ liệu:** chưa PROMOTE, chờ holdout. Vì vậy chưa nâng 8.0.0.
- **Candidate ×2:** đo trên holdout trước. **Vintern:** giữ baseline.
- **Keyword:** đếm keyword trong dòng bị A1 loại thành cột chờ duyệt riêng (Q6 B); đưa `020`↔`O2O` vào tầng chờ duyệt (Q7 A).
- **Dữ liệu ngoài:** OmniDocBench chỉ đo nội bộ; tải 3 ứng viên nhận dạng.
- **Holdout:** chạy so cặp trên 6 PDF hiện có, có ghi độ lệch protocol §7.3 mục 5 (chạy OCR trước khi đủ slot); song song bổ sung PDF.
- **Quy trình:** các bước còn lại được tự động hóa bằng `scripts/run_v8_evidence_chain.py`.

## 6. Việc đang chạy

- **Batch OCR holdout baseline** (phiên "OCR PDF v8 exit gates"): `run_batch.py --input ocr_holdout/pairs6_20261113 --output output/v8_h01_baseline_pairs6_20261113`. Lúc viết đã xong 3/6 PDF (BRC, C47, CDC) và đang chạy DHA. Lượt candidate ×2 chạy sau.
- **Trong lúc batch chạy, không ai được sửa `src/**/*.py` trong `C:\kk_2\OCR_pdf`.**
- **Số đo holdout chỉ được tính sau khi 6 phiếu sàng lọc đã seal.** Không xem số holdout để chỉnh mã (protocol dòng 63).

## 7. Việc của người dùng, theo thứ tự

Mọi phiếu phải mở qua `scripts/serve_review_sheets.py`. Cấu hình nằm trong `.claude/launch.json`. Khung trình duyệt của app làm mất localStorage.

1. **Sàng lọc holdout** (`holdout-screening-sheets`, cổng 8769): BRC, C47, CDC, DHA, DTT, FCN; tổng 12.360 đơn vị. Mỗi PDF cần ít nhất 2.995 slot và 0 mismatch.
2. **Phân xử v8** (`adjudication-sheets`, cổng 8767): nạp `migrated-d613bd4747c8289f.jsonl`, chấm 4.474 mục.
3. **Nhãn GT cấu trúc** (`structured-gt-sheets`, cổng 8768), theo 4 lô trong gói duyệt.
   - Lô 4: vẽ cả header/footer, kể cả header lặp đã bị ẩn.
   - Khi export, anh/chị chọn `--iou-threshold` và `--ignore-overlap`.
4. **Bổ sung PDF holdout:** báo cáo thường niên born-digital của công ty ngoài AAA, ABT, ACL, AGR, ASM, BCE, BHN, VIC. Ghi manifest trước khi chạy OCR.
5. Push nhánh khi muốn.

Sau mỗi bước, chạy `.venv/Scripts/python.exe scripts/run_v8_evidence_chain.py` để xem tiến độ. Thêm `--run --out scratch/v8/evidence_chain` để seal và chấm các phần đã xong. Bước cần quyết định (khóa đo holdout, ngưỡng export) chỉ được in thành lệnh.

## 8. Rủi ro và giới hạn

- **Ngân sách byte tài liệu:**
  - backlog 23.993/24.000 B và registry gần 28.000 B: gần như không còn chỗ;
  - lần ghi tiếp theo phải rút gọn, hoặc nâng giới hạn trong `scripts/build_dev_context.py` (cần người dùng đồng ý).
- **Hai phiên Claude cùng repo:** phiên "OCR PDF v8 exit gates" có `/goal` với stop hook, nên có thể tự chạy lại. Khi không cần nữa, chạy `/goal clear` trong phiên đó. Mỗi phiên chỉ `git add` file của mình.
- **Ổ C còn khoảng 20 GB.** Mỗi lượt OCR 9 PDF chiếm khoảng 2,7 GB.
- **Docling đôi khi crash không tất định** (`0xC0000005`) trên vài trang. Fallback giữ chữ pha A và gắn review.
- **Holdout hiện chỉ đủ để so cặp candidate**, không đủ để kết luận cổng 99,99%.
- **`ocr_holdout/`** (gitignored) có 2 bản trùng dev (`BCE_2022`, `BHN_2022`) và thư mục `pairs6_20261113` do phiên kia tạo cho batch.

## 9. Lệnh hay dùng

```bash
.venv/Scripts/python.exe scripts/check_knowledge_map.py --summary
```

```bash
.venv/Scripts/python.exe scripts/run_pytest_scratch.py tests/unit tests/scientific tests/legacy_compat -q --capture=fd
```

```bash
.venv/Scripts/python.exe scripts/run_v8_evidence_chain.py
```

```bash
.venv/Scripts/python.exe scripts/compare_keywords_text_layer.py --help
```

Sửa registry hoặc backlog thì chạy `check_knowledge_map.py --render`, rồi `export_v8_docx.py --update-registry`, rồi `--check`.

## 10. Bằng chứng chính

- Gói duyệt: `cai tien v2/bao_cao/GOI_DUYET_V8_20261113.md`; hồ sơ candidate: `cai tien v2/bao_cao/CANDIDATE_SELECTION_DOSSIER.md`.
- Đo dev theo khóa v8: `scratch/v8/v8_011_measurement_dev_006_v8_20261113.json` và `_007_`.
- So cặp ×2: `scratch/v8/v8_050_upscale2_e2e_dser_006_vs_007_v8_20261113.json`.
- Keyword: `scratch/v8/v8_100_keywords_text_layer_review_tier_r2_006_vs_007_20261113.json`.
- Chạy thử chấm GT: `scratch/v8/review_packages/scoring_dryrun_20261113/README.md`.
- Nhật ký phiên: `scratch/dev_sessions/20261113-v8-review-package/session.md`, `scratch/dev_sessions/20261113-v8-exit-gates-cho/session.md`.

## 11. Kế hoạch chi tiết để hoàn thành dự án

### 11.1 Thế nào là "hoàn thành"

1. **Backlog:** mọi mục đạt đúng exit gate trong `06_BACKLOG_V8.csv`, có artifact kiểm lại được.
2. **Pha:** R1 và P1–P9 chuyển `DONE`.
3. **Phát hành 8.0.0** (V8-160), theo Q5 A:
   - người duyệt đã PROMOTE ít nhất một candidate;
   - có PR tích hợp và output mới;
   - có khóa baseline mới, audit đạt, hồi quy đạt;
   - nhánh đã push và PR #1 đã hợp nhất.
4. **Cổng dấu 99,99%** được đo trên holdout đủ slot và báo cáo đúng kết quả (PASS hoặc FAIL).

Lỗi DSER dev hiện khoảng 3,98%, tức gấp khoảng 400 lần mức 0,01%. Vì vậy nếu đo ngay, cổng gần như chắc chắn ra FAIL. Phần 11.4 có câu hỏi Q11 để người duyệt chọn cách xử lý.

### 11.2 Chuỗi phụ thuộc (đường găng)

Ba chuỗi chạy song song. Một bước chỉ bắt đầu khi bước trước nó xong.

- **Chuỗi A, holdout, quyết định PROMOTE:**
  sàng lọc 6 PDF → seal → khóa đo holdout → đo 006 và 007 trên holdout → so cặp → hồ sơ V8-140 bản 2 → PROMOTE/KEEP/REJECT → PR tích hợp 8.0.0.
- **Chuỗi B, GT cấu trúc:**
  nhãn lô 1–4 → export → chấm → V8-060/070/071/080 đạt exit gate → hồ sơ V8-140.
- **Chuỗi C, cổng dấu:**
  phân xử v8 → seal → số dev bảo thủ và ρ_U cuối → tính lại cỡ mẫu → bổ sung PDF holdout → khóa holdout v2 → đo cổng.

### 11.3 Các bước theo giai đoạn

Ký hiệu: **O** = operator (Claude), **N** = người duyệt, **C** = custodian holdout. Ở dự án này, N và C đều là người dùng.

#### Giai đoạn 1: hoàn tất việc máy đang làm

| # | Ai | Việc | Đầu ra / điều kiện xong |
| --- | --- | --- | --- |
| 1.1 | O | Chạy hết batch holdout baseline (`output/v8_h01_baseline_pairs6_20261113`), rồi lượt candidate ×2 (`config/candidates/v8_050_line_upscale2.yaml`). Chạy `scripts/audit_batch_outputs.py --validate` và `scripts/check_baseline_identity.py` (khớp khóa 001/002). Ghi exposure và độ lệch §7.3 mục 5 | 6/6 PDF `COMPLETED` mỗi lượt; identity `MATCH`; chưa ai xem số holdout |
| 1.2 | O | Merge nhánh `v8-integration-keyword-pending` vào nhánh làm việc **sau** 1.1. Tạo output analysis mới bằng `run_batch.py --analysis-from output/v8_006_arena1536_20261112 --output output/<mới>` (CPU, không OCR lại) | Excel có 2 sheet chờ duyệt mới; hồi quy đạt |
| 1.3 | O | V8-085: chạy production trên 223 trang OmniDocBench. Viết CLI chấm (chưa có; dùng `omnidocbench_adapter.py` và `formula_scorecard.py`) theo `FORMULA_ACCEPTANCE_POLICY_V7` | Số nền của CodeFormulaV2 (TEXT CER, CDM, inline/display). Chưa có ứng viên công thức, nên chỉ là số nền |
| 1.4 | O | V8-065: soạn đề xuất ứng viên chạy end-to-end. Đề xuất: VietOCR `vgg_transformer`, vì tỉ lệ crop sửa/sai tốt nhất (276/69), cùng thư viện với production và chạy được trong `.venv-v62/text`. Chờ Q12 | Phiếu quyết định Q12 |
| 1.5 | O | Đóng R1 và P7 nếu exit gate đã đạt (mọi mục backlog của hai pha đã `DONE`). Ghi evidence, chạy `--render` và `--check` | Registry cập nhật |

#### Giai đoạn 2: việc của người (song song với giai đoạn 1)

| # | Ai | Việc | Khối lượng | Đầu ra |
| --- | --- | --- | --- | --- |
| 2.1 | N | Sàng lọc 6 PDF holdout (cổng 8769) | 12.360 đơn vị; mỗi PDF ≥ 2.995 slot, 0 mismatch | 6 phiếu `ACCEPTED` sau `run_v8_evidence_chain.py --run` |
| 2.2 | N | Phân xử v8 (cổng 8767) | 4.474 mục | Seal phân xử v8 |
| 2.3 | O→N | Kiểm lại mù sàng lọc dev (từ 17/11): O dựng phiếu bằng `screen_text_layer.py recheck`, N chấm | 10% quyết định đã seal, tối thiểu 50 mỗi PDF | Đồng thuận lần 1 và lần 2 |
| 2.4 | N | GT cấu trúc, lô 1 → 4 (cổng 8768) rồi export | 18 + 8 + 9 trang, lô 4 gồm cả 44 trang | `scratch/gt/<DOC>.structure.json` |
| 2.5 | C | Bổ sung PDF holdout: báo cáo born-digital của công ty mới, ghi manifest trước khi OCR | Ước tính khoảng 22 PDF đủ điều kiện nữa (xem chú thích dưới bảng) | Thư mục và manifest mới |
| 2.6 | O→N | GT keyword cho V8-100: O viết phiếu duyệt occurrence (chưa có; bộ chấm `keyword_acceptance.py` đã có), N duyệt trên mẫu trang | Phạm vi do N chọn | Occurrence đã duyệt |

Chú thích ước tính ở bước 2.5:
- Tính lại khi có ρ_U cuối từ bước 3.3; m_w cũng đổi khi thêm PDF.
- DEFF ≈ 1 + (967 − 1) × 0,025 ≈ 25,2, nên cần N ≈ 29.956 × 25,2 ≈ 754.000 slot. Hiện có 163.662, còn thiếu khoảng 590.000.
- Mỗi PDF đủ điều kiện có trung bình khoảng 27.300 slot, nên cần khoảng 22 PDF đủ điều kiện nữa.
- Trong lô vừa rồi chỉ 6/13 PDF đủ điều kiện, nên nếu không lọc trước có thể phải thu khoảng 47 PDF. Nên ưu tiên PDF xuất từ InDesign/Word, có text layer hiện.

#### Giai đoạn 3: đo và quyết định

| # | Ai | Việc | Cần trước | Đầu ra |
| --- | --- | --- | --- | --- |
| 3.1 | N→O | N duyệt khóa đo holdout (`lock_text_layer_measurement.py`, ràng buộc 6 seal). O đo 006 và 007 (`measure_text_layer_diacritics.py`), rồi so cặp (`compare_text_layer_runs.py`) | 1.1, 2.1 | Sửa/sai ×2 và V8-030 trên holdout |
| 3.2 | O | Chấm GT cấu trúc (`run_v8_evidence_chain.py --run`): TP/FP/FN detector, P/R layout theo class, pair accuracy thứ tự đọc, TEDS và ô số | 2.4 | V8-060, 070, 071, 080 đạt exit gate |
| 3.3 | O | Seal phân xử, số dev bảo thủ cuối và ρ_U cuối; tính lại cỡ mẫu holdout | 2.2 | V8-011 tiến gần exit gate; V8-012 có kế hoạch cuối |
| 3.4 | O | Nếu Q12 chọn ứng viên: viết adapter trong worktree, chạy end-to-end 9 PDF dev, rồi holdout | 1.4 + Q12 | Sửa/sai DSER, CER, keyword (exit gate V8-065) |
| 3.5 | O | Chấm keyword trên GT đã duyệt (`keyword_acceptance.py`), cho cả literal và tầng chờ duyệt | 2.6 | V8-100 đạt exit gate |
| 3.6 | O→N | Hồ sơ V8-140 bản 2 với số holdout; N quyết PROMOTE/KEEP/REJECT/INCONCLUSIVE cho từng candidate (bất biến dữ liệu, ×2, acronym, REC, layout) | 3.1–3.5 | V8-140 `DONE` |

#### Giai đoạn 4: tích hợp và phát hành 8.0.0

| # | Ai | Việc | Đầu ra |
| --- | --- | --- | --- |
| 4.1 | O | PR tích hợp: gộp các candidate đã PROMOTE; `src/ocr_runtime/version.py` lên 8.0.0; cập nhật test `tests/unit/runtime/test_config_and_paths.py` | Nhánh tích hợp xanh |
| 4.2 | O | Output mới cho 9 PDF dev: `scripts/smoke_unified.py`, `scripts/audit_batch_outputs.py --validate`; khóa baseline mới bằng `scripts/lock_baseline.py` | Khóa `BASELINE-V8-…` của 8.0.0 |
| 4.3 | O | Hồi quy đầy đủ; map `--render`/`--check`; `verified_head`; HANDOFF | Bản đồ 0 lỗi |
| 4.4 | O | Khi holdout đủ slot (2.5): khóa holdout v2, chạy OCR **một lần** bằng identity 8.0.0, đo cổng dấu | Báo cáo PASS hoặc FAIL kèm cận trên |
| 4.5 | N | Duyệt PR, cho push và hợp nhất PR #1 | Phát hành |

### 11.4 Quyết định mới cần người duyệt

| Mã | Câu hỏi | Đề xuất của operator |
| --- | --- | --- |
| Q11 | Cổng 99,99% cần giảm lỗi khoảng 400 lần. v8.0 nên (A) giữ mục tiêu, báo FAIL kèm cận trên đo được, rồi cải tiến tiếp ở v8.x; hay (B) đặt mục tiêu trung gian cho v8.0? | A: giữ nguyên tiêu chí đã khóa, không hạ chuẩn sau khi xem số |
| Q12 | Ứng viên nhận dạng nào chạy end-to-end? | VietOCR `vgg_transformer` trước; AsterNet sau, vì số crop làm sai cao (188) |
| Q13 | Nâng giới hạn byte của backlog (24.000) và registry (28.000)? | Đồng ý, để không phải xóa bằng chứng cũ |
| Q14 | Khi nào push và mở review PR #1? | Ngay sau giai đoạn 1, để có bản sao ngoài máy |

### 11.5 Năm việc làm ngay

1. **O:** theo dõi batch holdout đến 6/6 cho cả hai lượt (1.1), rồi merge nhánh tích hợp (1.2).
2. **N:** bắt đầu sàng lọc holdout (2.1): đây là đầu chuỗi A, chuỗi dài nhất.
3. **C:** thu thêm PDF born-digital (2.5).
4. **N:** trả lời Q11–Q14.
5. **O:** viết CLI chấm công thức (1.3) và phiếu GT keyword (2.6), vì hai mục này đang thiếu công cụ.
