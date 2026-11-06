# Ghép thử bảng qua nhiều trang

## Nối tự động trong pipeline v7.0

Profile chuẩn có `table_stitch: {method: auto_v1}`. Export gọi `auto_table_stitch.build_auto_stitches`, ghi quyết định tại `document.json.table_stitch`. Khi đủ bằng chứng, `result.md` và `document.md` chứa một bảng logic thay các mảnh hiển thị; `structures/tables/logical-NNNN.html` giữ row/col span. Bảng vật lý, bản trang, bbox, chữ thô và từng ô nguồn không bị sửa. Validator tính lại phép chiếu từ extraction.

Điều kiện: trang liền nhau, cùng section/số cột, không có chunk chen giữa, hình học cột khớp, có tín hiệu tiếp nối và tiêu đề lặp xác định được. Hàng bị cắt chỉ nối khi chữ tiếp nối có dấu hiệu rõ, các ô bổ sung nhau và không nhập hai số riêng. Hàng dữ liệu trùng nhau không được tự xem là tiêu đề. Caption mới, bảng đã kết thúc, ô/bbox không duy nhất, khác đơn vị, span mơ hồ hoặc thiếu bằng chứng sẽ giữ tách với lý do. Mọi phép nối tự động mang `AUTOMATIC_REQUIRES_REVIEW`, nghiệm thu L5 vẫn `NOT_EVALUATED`.

Tiêu đề nhiều hàng có rowspan được xét ở prefix phủ trọn ô nguồn; prefix cắt ngang một ô chưa đủ để kết luận cả khối tiêu đề không hợp lệ. Tại prefix đầy đủ, toàn bộ role header, nội dung thô/hiển thị, topology và mọi slot đều phải khớp. Một ô role dữ liệu/không rõ giữa các ô có role header, năm khác, ô thiếu hay span chồng vẫn chặn loại tiêu đề lặp. Counterexample hai hàng có rowspan/colspan đã kiểm qua export nối hàng bị cắt, HTML/MD/TXT và replay validator. Đây là kiểm phần mềm trên fixture; [replay dữ liệu cũ](../../scratch/dev_sessions/20261106-spanned-header/real-boundary-replay.json) vẫn chưa cho bảng thật tự nối.

Nguồn bảng chưa đối soát không được tự tạo section tài liệu hoặc thành bản dịch heading. Guard này giữ chữ/review và không bỏ qua gate nội dung xen giữa. Tái xuất CPU 14 trang: hai heading ASM được giữ thành paragraph cần review; 11 block AGR trước bị suy mục lục từ dòng số trở lại trong MD/TXT. Extraction, ô và source dispositions giữ nguyên; token/dãy chữ số cũ giữ thứ tự, phần tăng khớp đúng các nguồn phục hồi, vector literal 86 key giữ nguyên. Kiểm 9 PDF/938 trang cũ giữ mục lục thật BHN/VIC; chỉ 9 block ABT được phục hồi từ quyết định TOC trước. Cả hai phạm vi vẫn chưa chứng minh bảng thật tự nối đúng. [Hồ sơ và giới hạn](../../scratch/dev_sessions/20261106-table-internal-headings/session.md).

RPC bảo toàn role ô Docling. Nếu nguồn đã có role, mọi ô của hàng header lặp phải có `column_header=true` ở cả hai phía; một hàng chứa số năm nhưng role dữ liệu không được bỏ. Với nguồn legacy không có role, guard chữ/số chặt vẫn áp dụng. Cột nhãn được xác định riêng nên hỗ trợ cột mã đứng trước diễn giải. Hướng bảng được đối chiếu với extraction; hướng khác nhau hoặc thiếu một phía sẽ chặn nối. Enum hướng chỉ là giá trị Docling báo (có thể mặc định), không xác nhận góc thật trên ảnh.

Replay đầu ra cũ 9 PDF/938 trang trong [phiên phát triển](../../scratch/dev_sessions/20261105-recognition-gaps/session.md) hiện chưa tự nối cặp nào. Không lấy test tích hợp thành bằng chứng dữ liệu thật đã nối đúng. CLI preview dưới đây vẫn phục vụ đề xuất thủ công và điều tra trường hợp bị chặn.

Đối soát nguồn bổ sung theo token bridge cho phép một dòng đi qua nhiều ô cùng hàng khi mọi token có bbox quan sát được và khớp chuỗi duy nhất. Giữ nguyên source/raw/bbox và ô vật lý, không tự chia fragment số hoặc bỏ protected. CPU re-export ngày 06/11 trên 14 trang giữ baseline, thêm bốn mapping nguồn thật so với bản glyph trước; review 185→181, vẫn 0 bảng tự nối. Các header thiếu chữ, section khác và đoạn chưa đối soát tiếp tục chặn nối; không coi cải thiện ownership là đã hoàn tất TAB_05. [Bằng chứng token](../../scratch/dev_sessions/20261106-table-continuation/token-ownership-changes.json).

Lượt mới 4 PDF/14 trang có role ô thật và CropBox/spread hỗn hợp đã hoàn tất kỹ thuật, nhưng vẫn 0 bảng tự nối: còn lệch số cột, đoạn nguồn phục hồi chen giữa và section chưa thống nhất. Không bỏ guard nguồn để ép nối. [Audit và giới hạn](../../scratch/dev_sessions/20261105-table-source-ownership/session.md).

Tiếp nối CPU trên chính 14 trang đó: giữ stage/model cũ, dựng lại bridge từ pha A đã kiểm hash rồi đối chiếu bbox chữ ẩn thực. Export baseline khớp Markdown cũ cả bốn tài liệu. Export có proof glyph ánh xạ thêm 148 nguồn vào đúng occurrence ô quan sát được (62 nguồn chứa fragment số); giữ nguyên mọi ô vật lý và evidence chữ/bbox. Còn 790 nguồn cần review và vẫn 0 bảng tự nối. Đây là re-export phát triển không chạy OCR, không có receipt/completion công bố mới và chưa có GT người. [Phép đo và proof](../../scratch/dev_sessions/20261106-table-alignment/ownership-effects.json).

`--table-stitch-from` tạo một bảng HTML và Markdown từ extraction đã kiểm integrity. Dùng bảng này để rà `TC_SCI_TAB_05` và quyền sở hữu ô L5. Mỗi lần chạy tạo thư mục riêng với trạng thái `DRAFT_PREVIEW`. Các file công bố và số đếm theo `result.md` vẫn thuộc lượt extraction gốc.

## Lập đề xuất

Mở `document.json` và ảnh vùng ngắt trang đã xác minh. Chọn ID của hai hoặc nhiều mảnh liền nhau trong thứ tự tài liệu, trên các trang vật lý liên tiếp, cùng section và số cột. Xác nhận quan hệ cùng bảng trên ảnh trước khi đề xuất kiểu nối. Giữ phiếu A/B chỉ đọc ảnh nguồn tách riêng với đề xuất này vì đề xuất dùng ID và ô OCR.

Ví dụ lược đồ đề xuất. Thay ID và hash bằng dữ liệu từ tài liệu cần rà. Trong `publication`, tính SHA-256 của `COMPLETED.json`, `extraction.json` và `document.json`. Dùng mảng `boundaries` theo đúng thứ tự giữa từng cặp ID.

```json
{
  "schema_version": "ocr-table-stitch-plan-v1",
  "status": "DRAFT",
  "document_id": "example",
  "publication": {
    "completion_sha256": "<sha256>",
    "extraction_sha256": "<sha256>",
    "document_sha256": "<sha256>"
  },
  "table_ids": ["<table-id-previous>", "<table-id-next>"],
  "boundaries": [{"kind": "SPLIT_ROW", "repeated_header_rows": 1, "join_columns": [2]}]
}
```

- `BETWEEN_ROWS` nối các hàng tiếp theo. `join_columns` để trống.
- `SPLIT_ROW` dùng cùng hàng logic cho hàng cuối và hàng đầu sau tiêu đề in lại. Ghi cột bắt đầu của từng ô cần nối trong `join_columns`. Chỉ số cột bắt đầu từ 0. Hai ô cần cùng vị trí cột và `col_span`.
- `SPANNING_CELL` giữ hai hàng và kéo dài `rowspan` của các ô có mảnh quan sát ở cả hai trang. Ghi ít nhất một cột trong `join_columns`.

`repeated_header_rows` là số hàng đầu in lại ở mảnh sau. Giá trị lớn hơn 0 yêu cầu các ô của cả hai tiêu đề phủ kín lưới, trùng nội dung thô, nội dung hiển thị và topology. Mảnh in lại được giữ trong `repeated_header_sources` của ô tiêu đề. Khác năm, khác nhãn hoặc khác span sẽ chặn việc bỏ hàng.

## Chạy và kiểm đầu ra

```powershell
.venv/Scripts/python.exe run_batch.py `
  --table-stitch-from output/unified_batch/example `
  --table-stitch-plan scratch/table-stitch-plan.json `
  --output scratch/table-stitch-preview-01
```

Đọc `table.html` hoặc `table.md` để rà một bảng hợp nhất. `table-preview.json` ghi từng ô nguồn, gồm trang, ID mảnh bảng, hàng/cột, bbox, `text_raw` và provenance. Nối mảnh chữ bằng dòng mới hiển thị. Bbox được giữ theo từng trang. Ô lưới chưa quan sát mang `data-state="unobserved"`, khác với ô nguồn rỗng. Caption và dòng đơn vị đã liên kết trong `document.json` được giữ kèm nguồn. Chênh đơn vị đã ghi, bbox dùng chung, chồng span, gộp số riêng với nội dung khác hoặc hash thay đổi sẽ làm lệnh từ chối tạo preview.

Trước khi đưa ghép bảng vào đầu ra nghiệm thu, cần hai người đối chiếu độc lập trên ảnh và C phân xử quan hệ bảng, ranh giới hàng, tiêu đề lặp, span và quyền sở hữu các ô. Cần kiểm riêng nội dung và ký hiệu số, kể cả khi phép chiếu giữ được tất cả ô OCR đã quan sát. [Bằng chứng phát triển và giới hạn](../../scratch/dev_sessions/20261105-table-stitch/session.md) · [Tiếp nhận L5](../../benchmark/ground_truth_tools/TABLE_BOUNDARY_INTAKE_V7.md).
