# 9 PDF, bằng chứng vận hành và nhãn pilot

Cập nhật 04/11/2026, Asia/Bangkok. HEAD `a95c806965118b53b3afc28d2ebbff37dec0cfc7`, có sửa đổi chưa commit. Bản này cập nhật trạng thái bằng chứng, không thay backlog/trace lịch sử hoặc mẫu protocol DRAFT.

## Cập nhật vận hành ngày 05/11/2026

Đã kiểm một warm toàn lượt trên 9 PDF/938 trang: 5.130,520 giây, p50 508,037 giây/PDF, p95 nearest-rank 1.045,766 giây/PDF, RSS đỉnh quan sát 3.710,789 MiB, VRAM toàn GPU 2.569 MiB. WPS xuất hiện trong một phần cửa sổ đo; ba file pha AAA thiếu bản gốc đầy đủ trước sao lưu, nên việc so sánh cần giữ giới hạn này.

Warm 2 bị dừng theo người dùng, sau đó được tiếp tục bằng checkpoint cũ theo chỉ đạo “chạy tiếp lượt warm dừng lấy lượt warm cũ”. Khoảng khôi phục 1.071,761 giây đã hoàn thiện publication 9/938, revision 9; đây là recovery, chưa bổ sung một warm toàn lượt độc lập.

Hai cache đã được chạy tuần tự vào output mới, kiểm đủ 18 khóa stage trước từng lượt và kiểm lại publication/trace sau chạy. Thời gian lần lượt 827,817 và 821,743 giây; cả hai đủ 9 PDF/938 trang, tái dùng cả text/structure. Gộp hai cache: p50 101,850 giây/PDF, p95 nearest-rank 161,900 giây/PDF; RSS đỉnh quan sát 1.250,523 MiB, VRAM toàn GPU 111 MiB. Đây là 18 quan sát lặp trên chín tài liệu nguồn khác nhau.

[Số đo và hash nguồn](../scratch/dev_sessions/20261105-v70-resume/operation-measurements.json) · [Ngưỡng đề nghị để duyệt](../scratch/dev_sessions/20261105-v70-resume/SLO_PROPOSAL.md) · [Nhật ký](../scratch/dev_sessions/20261105-v70-resume/session.md).

SLO mới là DRAFT. Margin 20% cho latency/throughput và 25% cho tài nguyên là phương án lập ngân sách, không là CI đã đo. Vẫn thiếu warm lặp đủ, cold, soak/fault GPU, đơn giá, review capacity/drift và duyệt độc lập để đóng BK-08; chi phí mỗi trang giữ null/NOT_EVALUATED. Chưa có GT người A/B/C, protocol/ngưỡng chất lượng và quyết định phát hành, nên nghiệm thu v7.0 vẫn NOT_EVALUATED.

Warm 1 mới có 938 snapshot primary detector CAPTURED với 70.050 detection thô; format, frame và hash trang trong receipt/completion đã kiểm. Chưa replay pixel hoặc chấm P/R/Hmean do thiếu GT độc lập. [Bằng chứng BQ-04(b)](../scratch/dev_sessions/20261105-v70-resume/primary-snapshot-audit.json).

## Phạm vi tại mốc 04/11/2026

Người dùng yêu cầu không khởi động thêm OCR, tận dụng đầu ra 9 PDF đã kiểm và ưu tiên nhãn độc lập cùng các mục Cai Tien còn thiếu. Queue đã kết thúc; script queue cũ được vô hiệu hóa. Chưa có lượt mới được duyệt.

Đã kiểm lại bằng `canonical_predictions.collect_predictions`: **9 PDF/938 trang**, đủ phạm vi CUDA, receipt và hash hợp lệ; ma trận/SQLite revision 9. Đầu ra là `output/operations_4pdf_warm_1_20261104`; tên 4pdf thuộc mốc cũ, nội dung thật gồm 9 PDF. Validation `NEEDS_REVIEW`, chất lượng `NOT_EVALUATED`. Tám completion hash cũ giữ nguyên sau phục hồi; VIC dùng lại checkpoint chữ hợp lệ và chạy lại B/export.

[Inventory đã kiểm lại](../scratch/dev_sessions/20261104-operations-measured/verified-9pdf-inventory.json) · [Phục hồi](../scratch/dev_sessions/20261104-operations-measured/recovery-verified.json) · [Báo cáo tổng hợp có hash nguồn](../scratch/dev_sessions/20261104-operations-measured/existing-evidence-summary.json).

## Số đo được tận dụng và giới hạn

Scheduler đã công bố giữ thời gian lệnh pha A của 8 PDF và B/export của 9 PDF. VIC tái dùng A khi phục hồi, nên thời gian lệnh A mới giữ null. Những số này thuộc danh tính mã lịch sử trong publication, chưa gồm preflight, keyword finalizer, Excel và commit/ack SQLite. Không cộng chúng rồi gọi là latency toàn quy trình của mã cleanup hiện tại. Đường dẫn log trong scheduler có thể trỏ vùng job tạm đã được lượt khác dùng lại; mệnh đề thời gian ở đây dựa trên scheduler snapshot đã được receipt ràng buộc.

Warm-4 có 294 mẫu trong cửa sổ khoảng 628 giây, RSS quan sát 3.079,25 MiB; warm-6 có 276 mẫu trong khoảng 581 giây, RSS quan sát 2.645,73 MiB. VRAM toàn GPU quan sát ở cả hai cửa sổ đạt 1.687 MiB. Đây là đỉnh lấy mẫu trong lượt dở, không phải đỉnh toàn lượt hoặc giới hạn tài nguyên được nghiệm thu.

**Có 0 trace toàn lượt đủ điều kiện chốt SLO.** Warm-1 bị Modern Standby/timeout; warm-2 dừng để sửa scope PID; warm-4 lỗi lưu PDF tạm; warm-6 dừng với WinError 1455. Giữ failure/log/telemetry gốc. p50/p95, throughput toàn quy trình, cold/warm/cache lặp đủ, giới hạn RSS/VRAM và chi phí mỗi trang còn `NOT_EVALUATED`. Người dùng chưa có đơn giá; không thay cost thiếu bằng 0.

BK-08 đã có lượt thử tạo worklist drift từ publication đã lưu. Mẫu gồm 4 PDF, 8 trang, thuộc hai tầng năm báo cáo và có hai phiếu A/B trống. Cổng vận hành giữ `NOT_EVALUATED` khi kế hoạch drift còn nháp. Chưa có kết quả đo drift trên tài liệu mới. [Worklist thử](../scratch/dev_sessions/20261105-drift-sampling/development/worklist.json) · [Hợp đồng](../benchmark/scientific_evaluation/DRIFT_SAMPLING_V7.md).

Sau dừng, máy được ghi nhận committed memory khoảng 26,34 GB trên commit limit 34,49 GB và pagefile tự quản. Đây là ảnh chụp **sau lỗi**, không phải đỉnh trong OCR. [Số liệu máy](../scratch/dev_sessions/20261104-operations-measured/host-after-failure.json). Khi hệ thống không cấp phát thêm committed memory, tiến trình có thể lỗi; tham chiếu [Microsoft về commit/pagefile](https://learn.microsoft.com/en-us/troubleshoot/windows-client/performance/introduction-to-the-page-file).

## Nhãn pilot và việc người dùng đã chốt

Người dùng giữ quy trình **hai người A/B độc lập từ ảnh và người phân xử**. AI chỉ là nhãn sơ bộ. Không thay yêu cầu này bằng đồng thuận AI.

Đã tự tìm trong dự án theo chỉ đạo mới, gồm dữ liệu ẩn, output, scratch và sáu ZIP phiếu. Có bốn GT văn bản CLW cũ, mẫu layout và chuẩn tổng đếm; chưa tìm được bộ nhãn người đủ hồ sơ cho chín PDF hiện tại. Bốn pilot kiểm lại vẫn có 0/12 vùng ghép được nhãn người A/B. Các phiếu khai báo HUMAN đã điền trong test đều dùng hash fixture, không khớp đầu vào thật. [Danh mục nguồn, giới hạn tìm và audit mới](../scratch/dev_sessions/20261104-v70-acceptance-audit/KET_QUA_TIM_NHAN.md).

Đã dùng hai ngữ cảnh AI chỉ được cấp ảnh/vùng đích và vai trò C đọc ảnh sau khi A/B nộp. Seal A/B, hash PDF/ảnh, ba phiếu mỗi tài liệu và lý do phân xử được giữ. Có 12 cặp bản chép, 0 bất đồng AI được ghi nhận, 0 sửa bởi C. Đây là quan sát của các vai trò AI; không chứng minh accuracy, độc lập thống kê hoặc human verification. [Hồ sơ AI](../scratch/dev_sessions/20261104-operations-measured/ai-labels/review-summary.json).

Đã chuẩn bị hai gói nguồn riêng, mỗi gói gồm 12 ảnh và bốn phiếu trắng, không chứa OCR/workbook/bản chép AI. Chưa có bản chép của người thực hiện. Chỉ giao gói nguồn cho A/B, giữ phiếu riêng và hash trước khi chuyển người phân xử. Không cho A/B xem nhãn AI trước khi khóa phiếu. [Gói A](../scratch/dev_sessions/20261104-operations-measured/ai-labels/human-A-source-only.zip) · [Gói B](../scratch/dev_sessions/20261104-operations-measured/ai-labels/human-B-source-only.zip) · [Hướng dẫn điều phối](../scratch/dev_sessions/20261104-operations-measured/ai-labels/README.md).

12 vùng hiện có thuộc VIC/AAA/ABT/AGR và là mẫu phát triển chọn có chủ đích. Không suy ra coverage hay chất lượng cho 9 PDF/938 trang. Đã xác minh hậu tố số `020` trong mã ASM 2022 trang vật lý 100, với hai phiếu trắng riêng. Đối chứng `020` đứng riêng vẫn thiếu. [Ảnh nguồn](../scratch/dev_sessions/20261105-numeric-020/control/source.png) · [Kiểm chứng DC-01](../scratch/dev_sessions/20261105-numeric-020/session.md).

Đã thêm luồng tiếp nhận phiếu người có kiểm hash nguồn, khóa phiếu A/B trước khi tạo phiếu C, kiểm khai báo độc lập và xuất occurrence literal cho `development`. Scorecard holdout từ chối đầu ra pilot này. Đã chạy công cụ trên 4 bộ phiếu trắng và 4 bộ AI của VIC/AAA/ABT/AGR. Cả tám bộ ở trạng thái `NOT_EVALUATED`, với 0/12 vùng có hai bản chép người đủ khai báo. [Cách nhận và khóa phiếu](../benchmark/ground_truth_tools/ANNOTATION_V6.md#tiếp-nhận-và-khóa-phiếu-người-cho-pilot-keyword) · [Audit từng bộ](../scratch/dev_sessions/20261104-human-annotation-ingestion/).

## Thứ tự hoàn thiện tiếp

1. **GAP-01, DC-01/02, BK-01/03/04:** nhận phiếu người A/B, phân xử trên ảnh, kiểm nguồn/vị trí và thống nhất corpus khó. Chốt guideline, sampling, critical scope, normalization và phân xử trước khi khóa protocol. Giữ mẫu đã dùng phát triển ngoài holdout.
2. **BK-02:** bổ sung company/template/near-duplicate đã xác minh, khóa train/development/calibration/holdout; không đoán template hoặc công ty để ép đủ split.
3. **BK-05/06/07:** dùng extraction đã kiểm để làm alignment/count và đánh giá CPU sau khi có GT. Cần nhãn đúng/sai, thời gian review thật, calibration khóa, paired scorecard/CI và đối chuẩn đã định danh.
4. **GAP-06, BK-08:** hoàn thiện giám sát committed memory/đĩa và chuẩn bị kế hoạch tài nguyên. Nhánh dọn cây tiến trình khi chính bộ quan sát lỗi đã sửa, có kiểm CPU; chưa nghiệm thu fault/soak thật. Chưa chạy thêm GPU. Khi người dùng duyệt và máy sẵn sàng, đề nghị trước hết hai warm mới và hai cache trên cùng snapshot 9 PDF, output riêng. Định nghĩa cold, hai cold, soak/fault/drift và ngưỡng chi phí cần hồ sơ bổ sung để đóng BK-08 đầy đủ.

Bộ đo hiện ghi dung lượng đĩa output/evidence/temp và bộ nhớ cam kết Windows trước lệnh, trong từng mẫu và sau lỗi. Đã đọc được API Windows và ba vị trí filesystem trong một phép kiểm chỉ đọc. Lượt kiểm này không có OCR, không bổ sung latency hay SLO cho chín PDF. [Kết quả probe máy](../scratch/dev_sessions/20261104-human-annotation-ingestion/host-resources-probe.json).

Đã bổ sung phép chấm thứ tự đọc có căn span đã rà, gồm tách/gộp và cặp liền nhau. Kiểm lại hash extraction của 9 PDF và lập inventory phát triển cho điều phối viên. Inventory chỉ gồm dữ liệu đầu ra và vị trí, chưa có nhãn nguồn độc lập. [Hướng dẫn căn span](../benchmark/ground_truth_tools/ANNOTATION_V6.md#căn-thứ-tự-đọc-khi-khối-bị-tách-hoặc-gộp) · [Bằng chứng](../scratch/dev_sessions/20261104-reading-order-alignment/session.md).

BK-05 đã có đường đọc quan sát trước review từ extraction có receipt. Cổng phát hành tính lại calibration và holdout theo dữ liệu đã ghim. Đã kiểm đọc một dòng ở VIC và một ô ở AAA bằng output hiện có. Phép kiểm dùng tọa độ từ prediction để kiểm phần mềm, chưa có nhãn nguồn hay số đo hiệu quả review. [Quy trình](07_BO_TIEU_CHI_BENCHMARK_OCR.md#ghim-bản-ghi-review-vào-extraction-đã-công-bố) · [Bằng chứng](../scratch/dev_sessions/20261104-review-canonical-binding/session.md).

DC-06 có chế độ `--review-from` trong CLI sản phẩm. Đã tạo gói 40 mục trên chín PDF, gồm đủ sáu ứng viên O2O/020 ở VIC, cùng hàng đợi 42.696 mục cần rà. Số mục là tín hiệu từ prediction và quy tắc review. Phiếu bản chép/thời gian còn trống, hiệu quả review và GT vẫn `NOT_EVALUATED`. [Gói ảnh, hướng dẫn và kiểm phần mềm](../scratch/dev_sessions/20261104-review-packet/session.md).

BK-02 có inventory mới khớp 9/9 PDF và 938 trang với batch đã kiểm. Đã ghi tên đơn vị và năm trên trang nguồn, giữ `company_id` chưa xác minh. Bốn PDF có bằng chứng dùng cho pilot được đánh dấu development-only trong draft. Hai báo cáo AGR có cùng tên đơn vị và mã trên trang 3, cần chốt cùng nhóm trước khi chia tập. Chưa có quyền sử dụng, rà template/gần trùng hoặc quyền truy cập đã duyệt. [Hồ sơ và bằng chứng](../scratch/dev_sessions/20261104-benchmark-source-inventory/session.md).

BK-02 đã có công cụ tạo worklist đủ 36 cặp của chín PDF. Trên nguồn đã lưu, 927 trang đủ tín hiệu ảnh sau khi loại tám trang có cảnh báo render và ba trang phẳng. Có 895 trang đủ cụm chữ để so nội dung. Đã xem ảnh bốn cặp ưu tiên, gồm phần lịch sử dùng lại giữa hai bản AGR và các trang mục lục/báo cáo kiểm toán chung. Các nhóm và quyết định split vẫn chờ người phụ trách rà toàn bộ worklist, quyền dùng và quyền truy cập. [Lệnh, vị trí trang và ảnh nguồn](../scratch/dev_sessions/20261104-benchmark-overlap/session.md).

Phiên bản mã hiện tại là **v7.0**, gói `7.0.0`. BK-03 có adapter bố cục từ extraction, giữ vùng khớp/thừa/thiếu và tách COCO AP chẩn đoán khỏi số đếm paired. Đã kiểm phép chiếu dữ liệu trên batch 9 PDF. Điểm bố cục còn chờ GT và ngưỡng đã khóa. [Kiểm chứng v7.0 và BK-03](../scratch/dev_sessions/20261104-canonical-layout-scoreboard/session.md).

Đã đóng lại wheel v7.0 sau GAP-03, GAP-04 và công cụ BK-02. Byte các module trong wheel khớp snapshot mã hiện tại. CLI `--version` và trợ giúp công cụ rà cặp chạy được từ bản giải nén ngoài source checkout. [Wheel và hồ sơ đóng gói](../scratch/dev_sessions/20261104-benchmark-overlap/session.md).

Lượt tiếp nhận v7.0 đã chuyển kiểm giới hạn XLSX lên trước băm/đọc nội dung và từ chối định dạng khác đổi đuôi `.pdf`. Có fixture riêng cho tên trùng, PDF mã hóa/hỏng và thư mục con, cùng preflight tensor CUDA trong hai runtime. Trace bổ sung đưa số ca có kiểm kỹ thuật lên 57/65. Kiểm pilot hiện hành vẫn thiếu phiếu người đã điền. [Mã, fixture, probe và wheel mới](../scratch/dev_sessions/20261104-input-contracts/session.md).

`TC_SCI_LAY_04` đã có liên kết chú thích trực tiếp trong `document.json` của v7.0. Fixture kiểm trường hợp “Biểu đồ 3” ở sát bảng, dòng đơn vị và các tình huống có nhiều cách ghép. Replay CPU trên chín PDF tìm được hai liên kết, ở AGR 2020 trang 13 và AGR 2022 trang 16. Cả hai đã được đối chiếu với ảnh nguồn trong phạm vi phát triển. Trace kỹ thuật đạt 58/65 ca có bằng chứng riêng. F1 trên tập gán nhãn giữ `NOT_EVALUATED`. [Kiểm chứng và wheel v7.0](../scratch/dev_sessions/20261104-table-caption-binding/session.md).

`TC_SCI_TAB_05` đã có kết quả kiểm ảnh của 13 cặp ứng viên từ đầu ra lưu. Quy tắc mới lọc năm cảnh báo sai do trùng đầu trang, đơn vị hoặc kết thúc bằng dòng cộng. Tám cặp còn trong hàng rà, gồm bảy cặp tiếp nối quan sát trên ảnh và một cặp chuyển phần cần phân xử. Có hai gói ảnh và phiếu trống riêng cho A/B. Điều kiện ghép Markdown/HTML còn chờ L5, nhất là các hàng bị cắt qua trang. [Bằng chứng và phiếu](../scratch/dev_sessions/20261104-table-continuation/session.md).

Ngày 05/11 có CLI ghép thử dùng đầu ra đã kiểm hash. AAA 115–116 ghép được một ô cắt qua trang trong preview, giữ bốn ô tiêu đề in lại dưới dạng nguồn. Hai cặp AGR 37–38 và ASM 110–111 xuất mỗi cặp thành một bảng. AAA 125–126 bị chặn vì nhiều ô OCR dùng một bbox. Ba bản ghép giữ đủ 312 ô nguồn và đánh dấu 43 vị trí lưới chưa quan sát. `TC_SCI_TAB_05` vẫn `NOT_EVALUATED` cho chất lượng ghép trên ảnh và đầu ra chính thức. [Cách chạy](../src/ocr_document/TABLE_STITCH_V7.md) · [Kiểm chứng](../scratch/dev_sessions/20261105-table-stitch/delivery-replay/preview-verification.json).

Đã có gói L5 v2 chỉ chứa ảnh cho mỗi người và CLI khóa phiếu A/B trước phân xử. Mỗi gói có 13 cặp ngắt và 36 ảnh cắt nguồn, hỗ trợ ghi bbox và nguyên văn cho ô nối. Audit thực tế ghi 0/13 cặp có đủ hai phiếu. Bộ nhãn vùng ngắt này dùng cho development. [Tiếp nhận](../benchmark/ground_truth_tools/TABLE_BOUNDARY_INTAKE_V7.md) · [Audit](../scratch/dev_sessions/20261105-table-l5-custody/packet-v2/audit-final.json).

`TC_SCI_TXT_05` đã có guard chống đổi mã và đơn vị đứng riêng trong retry, cùng bộ chấm từng token đã căn nguồn. Kiểm bằng bốn biến thể chủ động từ dòng OCR đã lưu, bản mới giữ đủ bốn dòng nguồn và ghi review. Năm crop được ghim hash để hai người đọc ảnh độc lập. Trace kỹ thuật đạt 59/65 ca. Ngưỡng accuracy 99,5% vẫn `NOT_EVALUATED`. [Bằng chứng, hướng dẫn chấm và wheel](../scratch/dev_sessions/20261104-financial-token-fidelity/session.md).

`TC_SCI_TAB_04` xuất cây dòng một phần trong `document.json`, gồm cha, độ sâu và tọa độ có thể truy qua ô nguồn. Replay CPU cho 45 quan hệ ở 15 bảng trong tổng số 969 bảng. Ba cụm ở AAA, AGR 2022 và BHN được đối chiếu với ảnh nguồn. Bộ chấm tách độ sâu đúng và cha trực tiếp đúng. Trace kỹ thuật đạt 60/65 ca. Ngưỡng accuracy 90% chờ nhãn độc lập. [Kiểm chứng, phiếu và wheel](../scratch/dev_sessions/20261104-table-row-hierarchy/session.md).

`TC_SCI_LAY_02` đã có đường tách ô trích dẫn ở giữa hai cột khi đủ tín hiệu hình học và nhãn. Fixture qua lệnh export giữ thân bài theo luồng hai cột, đặt trích dẫn sau nhóm và đếm đủ nội dung. So cũ/mới trên 938 trang đã lưu cho cùng thứ tự nguồn ở từng trang, với 0 ô đủ điều kiện tách. Bộ dữ liệu cần bổ sung mẫu dương tính có nhãn độc lập để nghiệm thu. Trace kỹ thuật đạt 61/65 ca. [Kết quả, giới hạn và wheel](../scratch/dev_sessions/20261104-pull-quote-flow/session.md).

Đợt rà development ngày 05/11 lọc 852 trang thuộc 7 PDF và xem ảnh thu nhỏ của 67 trang ưu tiên. Chưa xác nhận được mẫu dương tính. Bộ đo chạy trên ba đối chứng âm quan sát từ ảnh (VIC trang 90/102, ASM trang 14) và ghi 0 chunk tách nhầm. Tỷ lệ chèn và CER trên trang thật còn `null` vì thiếu mẫu dương tính và bản chép thân bài độc lập. [Bộ đo](../benchmark/scientific_evaluation/CALLOUT_V7.md) · [Phạm vi và bằng chứng](../scratch/dev_sessions/20261105-pull-quote-source/session.md).

Ở mốc 04/11, ba ca `TC_SCI_DEG_01/02/03` đã có bộ chấm paired từ các file chữ được ghim hash. Có phép tính CER theo góc/tương phản và insertion ở điều kiện nhiễu, giữ thiếu GT khác với nguồn xác nhận rỗng. Trace giữ 61/65, chưa có kết quả đo ảnh thật. [Hướng dẫn](../benchmark/scientific_evaluation/DEGRADATION_V7.md) · [Bằng chứng phần mềm](../scratch/dev_sessions/20261104-degradation-scoring/session.md).

Adapter DEG đã kiểm 27 PDF dẫn xuất và ghép theo điều kiện, hash PDF và publication canonical. Báo cáo hiện ghi 0/27 publication được cung cấp. Batch 9 PDF gốc bị từ chối khi dùng làm control, vì control là PDF ảnh mới có hash riêng. Chưa sinh đầu vào chấm và chưa có điểm DEG. [Audit intake](../scratch/dev_sessions/20261105-degradation-predictions/actual-pending-final/intake.json) · [Cách chạy](../benchmark/scientific_evaluation/DEGRADATION_V7.md#ghép-publication-canonical).

Ngày 05/11 đã tạo bộ ảnh phát triển cho cả ba ca. Ba trang scan và chín điều kiện cho 27 cặp ảnh/PDF có thể tái tạo. Mẫu chấm vẫn null vì chưa có GT người hoặc prediction cho các ảnh dẫn xuất. Hai gói nháp A/B chỉ chứa ảnh thẳng, dùng riêng để chuẩn bị nhãn. Chất lượng ba ca vẫn `NOT_EVALUATED`. [Manifest corpus](../scratch/dev_sessions/20261105-degradation-corpus/final-corpus/manifest.json) · [Kiểm chứng](../scratch/dev_sessions/20261105-degradation-corpus/final-corpus-verification.json).

BQ-04(b) đã có đường lưu toàn bộ detector primary trước lọc dòng/retry và chấm bbox vào `structured_scoreboard`. Kiểm lại chín PDF đã công bố xác nhận **938/938 trang thiếu snapshot detector gốc**. Số detection không được suy từ dòng sau nhận dạng; precision/recall/Hmean giữ `NOT_EVALUATED`. Mã mới có hash pixel input, polygon/bbox/score và phép đổi frame, sẵn sàng ghi bằng chứng trong lượt OCR mới khi được duyệt. Recognizer GT crop, spotting và scoreboard đủ các tầng còn mở. [Hợp đồng dữ liệu/metric](../benchmark/scientific_evaluation/TEXT_DETECTION_V7.md) · [Kiểm kê](../scratch/dev_sessions/20261104-primary-detection-evidence/saved-inventory.json).

GAP-03 đã có bridge đặt chữ ẩn theo hướng crop và chặn gán nhầm toàn bộ dòng dọc vào ô theo tâm bbox. Ba block có sẵn được replay CPU ở AAA và ABT, không gọi model. Kết quả kiểm hướng và bbox được lưu cùng ID nguồn. Còn thiếu GT độc lập để kết luận độ đúng của quyền sở hữu ô. [Bằng chứng GAP-03](../scratch/dev_sessions/20261104-oriented-ocr-bridge/session.md).

GAP-04 giữ chữ thô và đưa đề xuất rút gọn đoạn lặp vào diện review. Kiểm 9 PDF đã lưu thấy ba dòng từng bị rút gọn trong frozen evidence. Replay CPU xác nhận cả ba giữ toàn bộ dòng trong mã mới. Đã chuẩn bị phiếu ảnh riêng A/B cho AAA trang 180, 202 và AGR 2020 trang 84, tách khỏi pilot keyword. [Bằng chứng GAP-04 và gói ảnh](../scratch/dev_sessions/20261104-repetition-source-review/session.md).

GAP-06 có ba lượt dừng cưỡng bức cây tiến trình analysis CPU tại ranh giới SQLite/Excel của tài liệu thứ tư. Cả ba resume đến revision 9 với số đếm chín PDF khớp nguồn, các hàng chờ trống và hash completion của phần đã prepared được giữ. Đây là bằng chứng phục hồi publication. SLO, soak và sự cố worker GPU còn chờ lượt đo được duyệt. [Nhật ký phục hồi](../scratch/dev_sessions/20261104-publication-hardkill/session.md).

Chưa có baseline toàn lượt hợp lệ để đề nghị con số SLO cuối. Bản tổng hợp là cơ sở duyệt phạm vi đo thêm, không phải ngưỡng đã được thông qua. Nhãn người, protocol khóa và các bằng chứng trên vẫn là điều kiện nghiệm thu toàn bộ Cai Tien.

Người dùng đã chốt **nghiệm thu cả công thức** trong v7.0. Kiểm kê đầu ra chín PDF có 0 item formula được model phân loại. Số công thức thật từ GT còn thiếu. Gate bắt buộc phạm vi `IN_SCOPE` và có đường dựng lại điểm định vị, TEXT, CDM và lỗi ký hiệu quan trọng. CDM Unicode v2 chấm được 25/25 ca kiểm soát. Cần nhãn người A/B và phân xử, đối chứng đầy đủ cho renderer v2, protocol và ngưỡng đã duyệt trước khi đo nghiệm thu. [Quyết định, kiểm kê và phần còn thiếu](11_NGHIEM_THU_CONG_THUC_V70.md).

Rà lịch sử dùng nguồn mới xác định thêm AGR 2022, ASM và BHN đã được xem để phát triển các quy tắc caption/tiếp bảng/phân cấp dòng. Hồ sơ đề nghị hiện ghi bảy PDF `development_only`; ACL/BCE vẫn cần curator rà, không tự coi đủ điều kiện holdout. Bản đề nghị chưa duyệt quyền, nhóm hay phân tập, không sửa draft/receipt cũ. [Nguồn chứng cứ](../scratch/dev_sessions/20261104-formula-scope-and-audit/source-use-proposal.json).

## Kiểm chứng phần mềm của lượt sửa

Rà theo quy trình Bugbot bằng tác nhân tổng quát đã phát hiện bốn lỗi ở gate/collector/preflight và đã sửa. Hồi quy tại mốc sửa vòng đời PDF tạm: **1.576 pass, 1 skip Linux**, `scratch/runs/20261104-docling-lifecycle-full`. Sau chốt nhánh cleanup: **101 pass**, `scratch/runs/20261104-docling-cleanup-context`. Smoke CUDA cuối trước chỉ đạo dừng exit 0, PDF tạm được dọn và log giữ; [bằng chứng](../scratch/dev_sessions/20261104-operations-measured/smoke-lifecycle_2.json). Không chạy thêm OCR sau chỉ đạo mới. Test và smoke không thay phép đo accuracy.

Sau chỉ đạo dừng, đã sửa `ProcessTree` để lỗi ở lần quan sát ban đầu/cuối vẫn thực hiện dọn job/group, đợi root và kiểm survivor rồi báo lỗi. **86 test CPU đạt**, `scratch/runs/20261104-process-cleanup-resource-fixed`. Hai ca của lượt đầu lỗi fixture mô phỏng POSIX thiếu SIGKILL trên Windows; đã sửa fixture. Hồi quy cuối **1.584 pass, 1 skip Linux**, exit 0, `scratch/runs/20261104-process-cleanup-full`. Không chạy smoke/GPU cho sửa đổi cuối này theo chỉ đạo người dùng.

Các artifact dưới scratch/output chỉ có trên máy này; phải lưu kèm khi chuyển máy hoặc bàn giao. Nhật ký chi tiết: [phiên đo](../scratch/dev_sessions/20261104-operations-measured/session.md).
