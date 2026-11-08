# QA offline và Error Registry v1

Đây là công cụ CPU ngoài pipeline sản phẩm, theo [đặc tả QA](../../docs/quality_assurance/CURRENT_ARCHITECTURE.md).
Không import production/model, không chạy OCR, không sửa packet, extraction, receipt, GT hoặc publication.
Chỉ đọc artifact hiện có và ghi **file mới**. Dùng Python supervisor của dự án.

## Nhập tín hiệu từ gói review

```powershell
.\.venv\Scripts\python.exe -B -m benchmark.qa import-review `
  --packet scratch/<goi_review>/ `
  --evidence-root . `
  --output scratch/<phien_qa>/registry.json `
  --creator <nguoi_hoac_cong_cu>

.\.venv\Scripts\python.exe -B -m benchmark.qa validate `
  --registry scratch/<phien_qa>/registry.json --evidence-root .
```

Thêm `--historical` khi nguồn là phát hiện lịch sử. Không nhận nó là lỗi hiện tại đã tái hiện.
Importer chỉ đọc `operator-review-packet-v1`, không suy hồ sơ mới từ mọi dòng backlog.
Mỗi selected review item thành một finding; queue chưa chọn không được báo đã rà.
Hai ô cùng source ID nhưng khác locator vẫn giữ riêng. Các reason đã biết chỉ **gợi ý taxonomy**;
reason chưa map giữ nguyên trong observation và có thể có `error_codes: []`.

Importer giữ nguyên toàn bộ review row trong `observation`, kể cả raw null, Unicode chưa NFC, số,
source ID, bbox, transforms, numeric guard và provenance. `actual.normalized` là null vì adapter
không chuẩn hóa. Bbox thiếu được biểu diễn null kèm reason; row gốc giữ `[]` nếu ban đầu như vậy.
Crop thiếu có reason; crop khai có nhưng không tồn tại/hash sai là lỗi input.

Tất cả nguồn phải nằm trong `--evidence-root` rõ ràng. Ref dùng path POSIX tương đối và SHA-256;
từ chối `..`, drive/UNC, backslash, symlink ra ngoài root, hash bất đồng và JSON trùng key/NaN/Infinity.
PDF được hash theo chunk, không chạy render/OCR. Mỗi lượt kiểm đọc hash lúc đầu/cuối; đây không
phải khóa chống nguồn khác đang ghi, nên chỉ dùng artifact đã ngừng ghi. Nếu file thay đổi, dùng
output mới sau khi kiểm lại nguồn; không sửa hash trong registry để ép qua.

`VALID_METADATA_AND_HASHES` chỉ chứng minh metadata và byte tham chiếu nhất quán.
`evidence_files` đếm các file được kiểm trong lượt gọi; CLI validate bao gồm cả file snapshot
registry, còn API nhận dict chưa đọc snapshot chỉ đếm file nguồn. Không dùng số này làm coverage trang.
Adapter không chạy lại publication verifier, không xác minh sự độc lập thật của người gán nhãn,
không tái hiện lỗi OCR hoặc chứng minh cause chỉ từ hash. Code/config/model/runtime của run gốc
được tham chiếu qua manifest/receipt, không lấy HEAD hiện tại gắn vào inference cũ.

## Snapshot và revision

Wire schema ở [`error_registry.py`](error_registry.py); giải path/hash/JSON ở [`evidence.py`](evidence.py),
adapter ở [`review_registry.py`](review_registry.py), CLI ở [`__main__.py`](__main__.py).

- `ocr-error-registry-v1`: thời điểm có timezone, creator, snapshot digest, evidence và records.
- `ocr-error-taxonomy-v1`: 10 họ/14 mã theo [taxonomy](../../docs/quality_assurance/ERROR_TAXONOMY.md).
- `error_id` được hash từ origin và source bất biến, không phụ thuộc lúc import hoặc người import.
- Revision bắt đầu 1, tăng liên tiếp. Snapshot kế tiếp giữ nguyên prefix mọi revision cũ và ghim
  `previous_registry` bằng file hash. Không xóa/viết lại lịch sử. Depth chain tối đa 32.
- `root_cause` cần evidence và bước cô lập; unknown vẫn null. Hypothesis để riêng trong
  `suspected_modules`, không có tên module tự suy từ confidence/review reason.
- Observation, actual và origin evidence giữ bất biến khi revision. Các run baseline/candidate
  có thể tham chiếu phép so trước/sau mới; chúng không thay artifact của sự cố gốc. Impact chưa
  có oracle giữ `UNASSESSED`; cause chỉ ghi ở trạng thái đã có chứng cứ cô lập.
- Các trạng thái kỹ thuật cần oracle và reproduction; `FIX_VERIFIED_TECHNICAL` cần before/after,
  preservation và hai run references khác nhau. Validator kiểm khai báo và hash, không đọc hiểu chứng cứ để
  quyết định nguyên nhân hay sửa đúng. Người điều tra vẫn chịu trách nhiệm về nội dung các khai báo.
- Chất lượng luôn `NOT_EVALUATED`. `QUALITY_ACCEPTED` bị từ chối ở v1; nghiệm thu dùng workflow
  release/GT độc lập hiện hữu. Chưa có adapter nhập quyết định release đã duyệt vào lifecycle này.

Để thêm phát hiện/revision, chuẩn bị JSON `ocr-error-registry-records-v1` có `records` là array
record đầy đủ theo wire schema. Record sửa có cùng identity/ID, revision kế tiếp; giữ row gốc,
thêm oracle/evidence/điều tra ở field tương ứng. CLI kiểm toàn bộ parent/child trước ghi:

```powershell
.\.venv\Scripts\python.exe -B -m benchmark.qa append `
  --registry scratch/<phien_qa>/registry.json `
  --records scratch/<phien_qa>/revisions.json `
  --evidence-root . --output scratch/<phien_qa>/registry-v2.json `
  --creator <nguoi_dieu_tra>
```

Không ghi vào packet hoặc thư mục publication gốc. Exit 0 nghĩa lệnh kiểm metadata/hash thành công;
exit 2 là input/output không hợp lệ, luôn giữ chất lượng chưa đánh giá. File đích phải chưa tồn tại;
ghi độc quyền, không overwrite. Nếu bị ngắt khi ghi, file chưa được xác nhận hợp lệ phải được giữ
làm bằng chứng và chọn tên output mới. Registry chứa prediction; hiện chỉ adapter development,
không tự xuất nội dung holdout ra UI/bên ngoài.

## Phạm vi triển khai

Đã có registry/version/validation, adapter operator packet và append CLI. Chưa có adapter mọi
evaluator/backlog, dashboard hợp nhất, paired fix/harm tổng quát, annotation độc lập hoặc nghiệm thu
chất lượng. Không cộng finding hoặc số test thành số lỗi đã xác nhận. Các bước tiếp theo ở
[roadmap](../../docs/quality_assurance/IMPLEMENTATION_ROADMAP.md).

Kiểm hợp đồng bằng [`test_error_registry.py`](../../tests/scientific/test_error_registry.py).
Fixture chỉ là contract oracle, không là GT chất lượng OCR.
