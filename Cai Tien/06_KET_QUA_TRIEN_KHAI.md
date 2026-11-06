# Kết quả triển khai cải tiến 03/11/2026

Múi giờ Asia/Bangkok. Báo cáo này cập nhật trạng thái thực hiện sau tài liệu 01/04; không thay bằng chứng lịch sử, GT hoặc receipt của batch cũ. Đợt này sửa mã bảo vệ số, bộ chấm, ghép văn bản/nguồn bảng, repetition và vocabulary review; phục hồi backlog và lập trace kiểm thử.

## 1. Phạm vi và phiếu thực hiện

- Thực hiện và tự kiểm: Codex trong phiên này. Người kiểm độc lập: chưa phân công; không tự gán người/lịch. Công và thời gian dựng ngữ cảnh: NOT_MEASURED.
- Đợt mã: AG-QA-001–006, DC-03/04/05, GAP-04; mở rộng cảnh báo cho DC-02. Phụ thuộc nghiệm thu accuracy DC-01/02/06 và các GAP vẫn giữ theo backlog.
- Đầu ra tổ chức: CSV phục hồi, [trace 65 TC](05_TRACE_KIEM_THU.csv), báo cáo này, SESSION/HANDOFF và evidence mới. Trace có thể ghi chưa có fixture, không suy từ thiếu link rằng đã chứng minh thiếu mã.
- HEAD đầu phiên: `a95c806965118b53b3afc28d2ebbff37dec0cfc7`. Có nhiều thay đổi chưa commit từ trước. Snapshot [đầu](../scratch/dev_sessions/20261103-trien-khai-cai-tien/start.json), [cuối](../scratch/dev_sessions/20261103-trien-khai-cai-tien/end.json); bản trước của các file sửa tiếp nằm trong `before/`. Hash focus không nhận dạng toàn bộ interpreter/trọng số.

## 2. Thay đổi đã thực hiện

| Nhóm | Hành vi mới và bằng chứng mã |
| --- | --- |
| AG-QA-001/002/003 | [numeric_guard](../src/ocr_text/numeric_guard.py) giữ mã/ký hiệu tiền tệ trước và sau số, dấu trước tiền tệ, `%`/`‰`, ngoặc kế toán với space/NBSP. Guard vẫn so literal, không sửa số. Có đối chứng qua `FallbackEngine._safe_replacement`. |
| AG-QA-004/005/006 | [numeric_metric](../benchmark/scientific_evaluation/numeric_metric.py) từ chối record không phải dict hoặc thiếu/null/rỗng/sai kiểu/không có chữ số ở `value`; không chấm dữ liệu thiếu thành TP. F1 tính từ TP/FP/FN trước làm tròn. Matcher và coverage chung định nghĩa ID vị trí, fallback `cell_id` khi `location_id` trống; bbox phải hợp lệ, bbox bảng không thay được cell identity. |
| DC-05 | [reconciliation](../src/ocr_document/resolve_document_layout.py) version `exact-source-occurrence-v2`, ánh xạ một-một theo hàng/ô/token và hình học. List marker được loại khỏi biểu diễn đếm chỉ khi guard số cho phép, có disposition; raw vẫn còn trong frozen evidence. Đối soát lại restored block bằng chữ và cờ bảo vệ hiện hành. [section_tree](../src/ocr_document/section_tree.py) không bỏ nguồn bằng phép tìm chuỗi con để vượt quyết định ownership. |
| DC-03 | [region_tree](../src/ocr_document/region_tree.py) nhận gutter prose bị một số bbox rộng che; giữ block bắc cột nguyên tử, ghi `PROVISIONAL_COLUMN_GUTTER`. Cột suy đoán vẫn cần review. |
| DC-04 | Nối dòng cùng loại block/cột/article khi bbox baseline chồng nhẹ; giữ ranh giới heading/body và khoảng cách đoạn. Không đổi `literal_v1`, không gộp trắng ở counter. |
| GAP-04 | [recognizer](../src/ocr_recognition/vietnamese_seq2seq_engine.py) giữ nguyên lặp có suffix. Loop cuối dòng là ứng viên cần review; không bỏ ngay dòng nghi noise. Giữ raw, candidate và disposition qua block serialization; numeric cleanup bị từ chối nếu đổi số. |
| DC-02 | [vocabulary review](../src/ocr_text/vietnamese_diacritics.py) thêm `chuyển đổi số`, `đổi mới`, `an ninh mạng`. Chỉ gắn nghi vấn, dùng đường retry có ảnh sẵn có; không thay chữ bằng từ điển hoặc tăng count fuzzy. Chưa đo tỷ lệ sửa đúng/sửa sai. |

Document flow dùng `region-tree-graph-v1.2`; exporter kiểm version trước khi tái dùng flow đã resolve. Thay đổi được nhận dạng trong manifest/provenance mới. Giữ schema layout hiện có với trường bổ sung có điều kiện; trang không chịu tác động phải giữ baseline xuất cũ. Không đổi `config/profiles.yaml`, model hoặc lock; pipeline GPU toàn trang vẫn là đường sản phẩm duy nhất. Quyết định chuẩn cập nhật tại [ARCHITECTURE](../ARCHITECTURE.md).

## 3. Kiểm chứng và giới hạn

Bộ phản ví dụ gốc chạy lại đầu phiên cho **10 thất bại / 5 đạt**: [lượt trước sửa](../scratch/runs/20261103-220535-a40ef6e5/run.json). Sau sửa AG-QA, lượt sát phạm vi đạt **143 test**: [log/JUnit](../scratch/runs/20261103-220803-29d08ecd/run.json). Một lượt sandbox lỗi WinError 5 ở temp mode-0700; chạy ngoài sandbox trong scratch, không sửa ACL.

Lượt hồi quy đầu: **1.471 đạt, 2 thất bại, 1 bỏ qua**; hai lỗi là baseline export mẫu. Đã sửa nguyên nhân: nối chồng bbox không được vượt loại block; metadata ownership chỉ thêm khi có bảng. Giữ nguyên hash baseline. [Lượt thất bại](../scratch/runs/20261103-221530-c8c40854/run.json), [73 ca sát phần sửa đạt](../scratch/runs/20261103-222144-409a7937/run.json).

Lượt rộng kế tiếp đạt 1.489, bỏ qua 1; rà soát thêm biên cờ protected của restored, sửa và kiểm [49 ca sát phần thay đổi](../scratch/runs/20261103-223240-5ccf4a65/run.json) đạt.

Lượt hồi quy **chốt mã cuối: 1.490 đạt, 1 bỏ qua, exit 0**; [run/log/JUnit](../scratch/runs/20261103-223309-ef39b650/run.json). Ca bỏ qua dành cho kiểm venv symlink trên Linux CI; warning gdown/pkg_resources được giữ trong log. [Kiểm triển khai/trace và hash mã cuối](evidence/verification_implementation_final_20261103.json) cũng xác nhận 58 nguồn Test case/test đã có không bị thay đổi. Lệnh:

```powershell
.venv/Scripts/python.exe scripts/run_pytest_scratch.py tests/unit tests/scientific tests/legacy_compat "Test case/antigravity_review_20261103/test_adversarial_review.py" -q --capture=fd --tb=short
```

[Replay năm trang trên mã cuối](../scratch/dev_sessions/20261103-trien-khai-cai-tien/diagnostics_final_verified/report.json) chỉ chạy CPU trên JSON trang lưu trước đó; có hash input, raw/source/bbox frozen và toàn bộ cell giữ nguyên, dispositions đủ mọi source. Không tạo publication/receipt OCR mới.

| Trang diagnostic | Trước → sau, số lần chuỗi liên tục trong Markdown |
| --- | --- |
| AAA 100 — `công nghiệp 4.0` | 2 → 1; source `…:p0100:b000033` có owner bảng và marker `-` được ghi nhận |
| VIC 65 — `ngôn ngữ tự nhiên` | 0 → 1; gutter suy đoán vẫn có review |
| VIC 37 — `Quỹ Đổi Mới Sáng Tạo` | 0 → 1 |
| AGR 40 — `tài chính số` | 0 → 0; không tạo cụm giả qua heading/body |
| VIC 137 — `doanh thu` | 24 → 24; không dedup theo chuỗi toàn trang |

Các số này là chẩn đoán nguồn văn bản ở năm trang, không phải vector keyword toàn batch, CER/WER hoặc kết quả holdout. Chưa chạy OCR GPU mới/smoke/audit batch, tải dài hay A/B model. Accuracy toàn corpus, precision/recall review và chi phí người kiểm: **NOT_EVALUATED**. Không mở lại hoặc sửa batch 4 PDF/511 trang lịch sử.

## 4. Backlog và trace

CSV phục hồi có **18.887 byte**, UTF-8 BOM, SHA-256 `0c3bddab08a77dc5db521daeb0abc1670766f119375a32b739d6e2dc960d551d`, khớp byte bản gốc. Dựng lại bằng phần khai báo dữ liệu của script gốc, kiểm hash lịch sử, 23 ID, schema, references, ưu tiên và dependencies không vòng trước thay bản chuẩn. [Biên bản phục hồi](../scratch/dev_sessions/20261103-trien-khai-cai-tien/backlog_recovery.json); bản hỏng giữ trong `before/backlog_corrupt.csv`. Không sửa verification cũ.

Trace có 44 TC chức năng và 21 TC khoa học: 51 có bằng chứng test liên quan (`VERIFIED_TEST_SUBSET`), 14 chưa xác nhận kiểm riêng (`NOT_EVALUATED`). `test_status` chỉ báo kiểm triển khai liên quan; `acceptance_status` vẫn riêng. Mỗi TC có mệnh đề, loại kiểm, input/GT, test hoặc lý do chưa đánh giá, identity, artifact và giới hạn. Nhiều TC mới có coverage một phần; test evaluator không chứng minh model đạt ngưỡng của ma trận gốc. Ngưỡng phải khóa trước holdout theo đặc tả.

| ID | Trạng thái sau triển khai | Điều kiện còn lại / bước tiếp theo |
| --- | --- | --- |
| AG-QA-001 | ĐÃ SỬA — VERIFIED trong phạm vi CPU/caller | Tiền tệ hai phía và caller fallback; không suy tần suất lỗi corpus |
| AG-QA-002 | ĐÃ SỬA — VERIFIED trong phạm vi CPU | Đối chứng `%`/`‰`/không đơn vị |
| AG-QA-003 | ĐÃ SỬA — VERIFIED trong phạm vi CPU/caller | Ngoặc space/NBSP và dấu trong/ngoài tiền tệ |
| AG-QA-004 | ĐÃ SỬA — VERIFIED trong phạm vi bộ chấm | Invalid schema bị từ chối ở cả hai phía |
| AG-QA-005 | ĐÃ SỬA — VERIFIED trong phạm vi bộ chấm | TP=1/FP=5/FN=0 cho F1=0,2857 |
| AG-QA-006 | ĐÃ SỬA — VERIFIED trong phạm vi bộ chấm | ID/cell/bbox hợp lệ, không match xuyên cell/page |
| DC-01 | MỞ — thiếu thử nghiệm nhận dạng có nhãn | Sáu crop O2O, số 020 thật và GT độc lập; không thay 020 toàn cục |
| DC-02 | MỘT PHẦN — mở rộng review | Đo retry thật, sửa đúng và sửa sai trên GT riêng; chưa chốt accuracy |
| DC-03 | MỘT PHẦN — mã + diagnostic VIC65 | Nghiệm thu order toàn trang, spanning heading/footnote trên GT |
| DC-04 | MỘT PHẦN — mã + VIC37/AGR40 | Ca `trí/tuệ` qua cột vẫn cần continuity có bằng chứng; không nối mù |
| DC-05 | MỘT PHẦN — mã + AAA100/VIC137 | Có ownership versioned; còn cần nghiệm thu occurrence rộng trên GT |
| DC-06 | MỞ — hiệu quả review NOT_EVALUATED | GAP-02 đủ trước nghiệm thu; crop/source/occurrence, missed errors, precision và phút người kiểm |
| GAP-01 | MỞ — thiếu vị trí chuẩn | Annotation độc lập từ ảnh cho các ô chưa rõ; giữ workbook người dùng |
| GAP-02 | MỞ — thiếu GT độc lập | Chốt development/calibration/holdout theo tài liệu/công ty, guideline, phân xử, coverage/protocol |
| GAP-03 | MỞ — mới có hợp đồng/fixture | Bridge 0/90/180/270°, CropBox/Rotate/spread và ownership có GT/GPU |
| GAP-04 | MỘT PHẦN — sửa engine/caller/serialization | Raw, suffix, numeric rejection được kiểm fixture; nghiệm thu ảnh/GPU còn mở |
| GAP-05 | TRACE ĐỦ — nghiệm thu từng TC còn một phần | Trace 65 ID, chỉ công bố theo đúng loại test; bổ sung fixture/GT cho các ô NOT_EVALUATED |
| GAP-06 | MỞ — chưa soak thực | Thử sự cố trên output riêng, đủ resource/process/hash/revision/ack; không gây sự cố batch người dùng |
| GAP-08 | MỘT PHẦN — báo cáo hiện hành có nguồn | Tài liệu 01/04 là mốc lịch sử; không coi số mẫu/PASS là accuracy |
| WF-01 | ÁP DỤNG trong phiên | Snapshot, SESSION, HANDOFF; chưa có kiểm độc lập |
| WF-02 | ÁP DỤNG trong phiên | Tra module/truy vấn dữ liệu; chưa đo hiệu quả năng suất |
| WF-03 | NOT_MEASURED | Thiếu telemetry/mẫu so sánh nhiều phiên; không suy số đo từ byte tài liệu |

Artifact dưới `scratch/` chỉ có trên máy và bị ignore; khi bàn giao sang máy khác phải mang kèm các thư mục lượt chạy/phiên được liên kết. Chưa commit/push.
