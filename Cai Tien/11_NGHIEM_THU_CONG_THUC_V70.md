# Công thức là phạm vi nghiệm thu bắt buộc của v7.0

Ngày 04/11/2026, người dùng chọn **“Nghiệm thu cả công thức”**. Quyết định này xác định phạm vi BQ-10, không phê duyệt GT, protocol, ngưỡng hoặc phát hành. [Bản ghi quyết định](../scratch/dev_sessions/20261104-formula-scope-and-audit/user-scope-decision.json).

## Trạng thái hiện tại

Profile canonical vẫn bật Docling `formulas: true`. Kiểm kê `extraction.json` của chín PDF/938 trang đã công bố có **0 item `kind=f` và 0 text block được gán role công thức**. Đây là số đầu ra được model phân loại, không phải số công thức thật trên ảnh. Số công thức GT, recall và CDM hiện chưa đo. Không thể coi đầu ra rỗng là bằng chứng không có công thức. [Inventory có hash](../scratch/dev_sessions/20261104-formula-scope-and-audit/formula-output-inventory.json).

## Chặn bỏ sót phạm vi trong protocol và gate

`scope.formula_scope_decision` dùng object có đúng hai trường:

```yaml
formula_scope_decision:
  decision: IN_SCOPE
  reason: User requires formula correctness in v7.0 acceptance.
```

`formulas` phải có trong `declared_modalities` khi quyết định là `IN_SCOPE`. Protocol câu chữ cũ như “include all formulas” hoặc “scope pending” không được tự suy thành một quyết định; preflight trả `NOT_READY_FOR_ACCEPTANCE_MEASUREMENT` và yêu cầu chuyển đổi rõ ràng. Giữ nguyên các protocol cũ, tạo bản mới khi người phụ trách đã chốt nội dung; không sửa approval/hash để vượt gate.

Thư viện có thể kiểm một bộ đo thành phần khai báo `EXCLUDED` kèm lý do, trả `scope_context=COMPONENT_MEASUREMENT`. CLI preflight và cổng phát hành luôn kiểm `V70_RELEASE`: phát hành v7.0 bắt buộc `IN_SCOPE`, không chấp nhận dùng bộ đo thành phần không có công thức để cấp nghiệm thu toàn dự án. Các bản ghi này vẫn không chứng minh độc lập của nhãn.

Mẫu protocol giữ **DRAFT**, `approved_by` và `locked_at` vẫn null. Gate còn `NOT_EVALUATED` vì thiếu nhãn độc lập, rà critical trên dữ liệu thật và ngưỡng. Preflight đã chặn hai protocol fixture có câu chữ mơ hồ trên cùng byte input. [Bằng chứng trước](../scratch/dev_sessions/20261104-formula-scope-and-audit/baseline-scope-proof.json) · [Sau](../scratch/dev_sessions/20261104-formula-scope-and-audit/candidate-final-scope-proof.json).

## Bộ chấm cặp công thức

Adapter CDM chạy bằng CPU, giữ đầu vào, lưu bằng chứng render và báo số đếm chưa làm tròn. Lượt thử 12 cặp có 10 cặp đo được, 1 tham chiếu LaTeX lỗi và 1 prediction TEXT chưa hỗ trợ. Hai ca sau giữ trung bình toàn bộ ở `null`. Dấu âm bị mất được tính một FN. Ca đổi số mũ thành chỉ số vẫn có CDM 1, kèm cờ rà cấu trúc. [Hướng dẫn](../benchmark/scientific_evaluation/FORMULA_CDM_V7.md) · [Kết quả có thể kiểm lại](../scratch/dev_sessions/20261104-formula-cdm-adapter/render-final-v2/comparison.json).

Ở đối chứng lịch sử, upstream có điểm 1 dù thiếu glyph Greek và tiếng Việt. Preflight kiểm nguồn cặp và độ phủ ký tự để chặn điểm tuyệt đối giả. Lượt LuaLaTeX Unicode v2 chấm được đủ 25 cặp đã ghim và giữ nguyên 23 F1 đã đo ở v1. Nhánh đối chứng mới dùng upstream, template Unicode và biên dịch riêng từ nguồn thô, rồi raster bằng ImageMagick/Ghostscript. Cả 25 F1 khớp sau làm tròn ba chữ số và đủ glyph tham chiếu. Preflight yêu cầu khai báo phạm vi toàn chuỗi và compiler rõ ràng. Ngày 05/11, người dùng chấp thuận dung sai đối chứng tối đa **0,0005**. Cần người rà kiểm harness/template và lập hồ sơ mới trước holdout; quyết định dung sai chưa cấp nghiệm thu renderer hay quality. [Quyết định](../scratch/dev_sessions/20261105-v70-release-readiness/user-tolerance-decision.json) · [Toàn chuỗi v2](../scratch/dev_sessions/20261105-formula-full-chain/comparison-summary.json).

## Cách đo cần hoàn thiện

Đề xuất dùng **CDM** cho độ đúng nội dung biểu thức, cùng coverage/detection và lỗi ký hiệu critical. CDM chấm dựa trên biểu thức được render và vị trí ký tự, thay vì chỉ so chuỗi LaTeX; hai chuỗi LaTeX có thể biểu diễn cùng hình thức. Nguồn phương pháp: [bài báo CDM](https://arxiv.org/abs/2409.03643), [triển khai của tác giả](https://github.com/opendatalab/UniMERNet/tree/main/cdm). Đây là đề xuất phương pháp, chưa phải metric hoặc ngưỡng đã được khóa trong protocol dự án.

Tiến độ và điều kiện còn thiếu:

1. Đã có luồng kiểm nguồn, phát phiếu, niêm phong A/B và phân xử C cho development và holdout. Holdout kiểm lại mẫu trang, split, audit quyền nguồn và người giữ tập, rồi dựng tham chiếu từ phiếu và seal đã ghim trong manifest phân xử. Cần phiếu người thật và tập độc lập có cả inline và display. [Pilot development](../benchmark/ground_truth_tools/FORMULA_ANNOTATION_V7.md) · [Quy trình holdout](../benchmark/ground_truth_tools/FORMULA_HOLDOUT_V7.md).
2. Đã căn theo trang và vị trí cho item công thức và text block gắn role công thức. Adapter giữ missing, spurious, duplicate, ignore. Với biểu thức chưa có role, hồ sơ span truy xuất đoạn raw theo ID block/ô và offset. Replay AGR 2022 giữ ba đoạn trong ô và một đoạn trong block. Liên kết thủ công chỉ phục vụ đối chiếu nội dung. Điểm định vị dùng output công thức tự động. [Adapter, replay và gói A/B](../benchmark/scientific_evaluation/FORMULA_ALIGNMENT_V7.md).
3. Đã chạy đối chứng CDM Unicode toàn chuỗi trên 25 control với nguồn UniMERNet được ghim và runtime CPU riêng. Dung sai 0,0005 đã được người dùng chấp thuận. Cần người rà duyệt hồ sơ DRAFT, rồi kiểm phạm vi biểu diễn thực tế, gồm công thức inline trên ảnh nguồn.
4. Bao phủ lỗi renderer: GT render lỗi cần phân xử và giữ chưa đánh giá; prediction render lỗi hoặc thiếu prediction phải chịu lỗi trong mẫu số GT theo protocol. Không bỏ các ca lỗi khỏi trung bình. Chưa có GT thì không tạo điểm 0 hoặc 1.
5. Báo detection, CDM và TEXT riêng. Bộ đo TEXT giữ số đếm lỗi ký tự, ghi nhận prediction thiếu và lưu ca khác định dạng. Hồ sơ critical ghim hash cặp và căn, yêu cầu quyết định cho dấu, quan hệ, tử/mẫu, chỉ số/số mũ, số, đơn vị và nhãn. Cần chạy với người rà và GT thật trước khi chốt ngưỡng. [Hợp đồng và cách chạy](../benchmark/scientific_evaluation/FORMULA_CONTENT_V7.md).
6. Gate replay nhãn A/B/C và hai publication, đo định vị, TEXT, CDM và critical rồi ghép count vào họ kiểm định chung. Mẫu phải phủ đúng trang âm tính và từng tham chiếu GT, giữ placement và mẫu số. Holm tính trên toàn họ. Cần đối chứng renderer được rà, GT thật, ngưỡng/cỡ mẫu được duyệt và số đo đạt trước khi nghiệm thu. [Mẫu và họ kiểm định](../benchmark/scientific_evaluation/FORMULA_FAMILY_V7.md) · [Chính sách preflight](../benchmark/scientific_evaluation/FORMULA_ACCEPTANCE_POLICY_V7.md).

Đã kiểm adapter bằng bộ mẫu kiểm soát và dùng lại kiểm kê 9 PDF. Độ đúng trên dữ liệu nguồn vẫn `NOT_EVALUATED`. Mục tiêu nâng cấp toàn bộ Cai Tien tiếp tục còn mở.
