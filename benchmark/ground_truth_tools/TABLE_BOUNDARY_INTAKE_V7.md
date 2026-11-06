# Tiếp nhận phiếu L5 bảng qua trang

Giao cho A và B hai gói riêng. Mỗi gói dùng 36 ảnh cắt từ 13 cặp trang vật lý, cùng manifest và bản hướng dẫn đã ghim. Gói chỉ chứa ảnh nguồn và phiếu trắng. Giữ lại nguyên bản đã phát. Không dùng bản ghép thử hoặc nhận xét AI để điền phiếu. [Hướng dẫn người gán nhãn](TABLE_BOUNDARY_LABELING_V7.md).

Điều phối viên giữ manifest và ảnh từ gói đã phát trong thư mục `source`. Sau khi nhận phiếu, lưu byte gốc ở thư mục riêng. Tự đối chiếu người nộp và việc hai người làm độc lập. Công cụ kiểm khai báo, thứ tự thời gian, hash PDF/ảnh/phiếu và hình học. Danh tính người thật và chữ chép trên ảnh cần được người phụ trách xác nhận.

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
$tool = @('-B', '-m', 'benchmark.ground_truth_tools.table_boundary_annotations')
$common = @('--source', 'scratch/l5/source/source_manifest.json', '--pdf-root', 'inputs',
  '--guideline', 'scratch/l5/source/HUONG_DAN.md', '--annotation-a', 'scratch/l5/received/annotation_A.json',
  '--annotation-b', 'scratch/l5/received/annotation_B.json')
& .venv/Scripts/python.exe @tool audit @common --output scratch/l5/custody/audit.json
& .venv/Scripts/python.exe @tool seal @common --received-by 'coordinator-id' --output scratch/l5/custody/seal.json
& .venv/Scripts/python.exe @tool adjudication-template @common --seal scratch/l5/custody/seal.json `
  --output scratch/l5/custody/adjudication.blank.json
```

Chỉ chạy `seal` khi audit trả `READY_TO_SEAL` và điều phối viên đã kiểm trực tiếp. C là người khác A/B. C nhận hai bản đã khóa và cùng bộ ảnh, phân xử từng cặp rồi nộp ở đường dẫn mới. Phiếu C phải ghim đúng seal và có thời điểm nộp sau khi khóa. Với bản cập nhật phiếu A/B cần tạo seal mới sau khi điều phối viên xác minh quy trình lại từ đầu. Không sửa seal hoặc hash cũ.

```powershell
& .venv/Scripts/python.exe @tool export @common --seal scratch/l5/custody/seal.json `
  --adjudication scratch/l5/received/adjudication.json --output scratch/l5/custody/labels-development.json
```

Lệnh trả 0 khi thao tác hợp lệ. `audit` trả 1 nếu còn phiếu trắng và vẫn ghi báo cáo. Mã 2 báo dữ liệu sai hoặc chưa đủ cho thao tác, ví dụ nguồn/phiếu thay byte, người A/B trùng, C nộp trước seal, bbox lệch ảnh hoặc ô nối chồng nhau. Mỗi output cần đường dẫn chưa tồn tại, ngoài thư mục ảnh nguồn và PDF.

Bản xuất giữ SHA-256 của cả ba phiếu, điểm bất đồng, quyết định từng cặp, bbox theo pixel ảnh và nguyên văn mảnh ô. Kết quả thuộc `development`, có trạng thái `DECLARED_HUMAN_ADJUDICATED` sau khi đủ hồ sơ khai báo. `UNCERTAIN` vẫn được lưu. Phạm vi là quan hệ bảng, vùng ngắt, số cột, tiêu đề in lại và các ô có mảnh ở hai bên. Nghiệm thu L5 còn cần lưới GT đầy đủ theo phạm vi đo, ánh xạ vị trí qua hệ tọa độ, đối chiếu bản ghép và protocol độc lập. [Ghép thử](../../src/ocr_document/TABLE_STITCH_V7.md).
