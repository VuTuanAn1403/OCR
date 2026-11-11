# Thang bằng chứng và vị trí dữ liệu

## Bốn nhãn

| Nhãn | Nghĩa | Ví dụ |
| --- | --- | --- |
| `VERIFIED` | Đã kiểm trên mã hoặc artifact hiện tại, có lệnh hoặc đường dẫn | Ký hiệu tồn tại; test vừa chạy pass |
| `HYPOTHESIS` | Có dấu hiệu nhưng chưa chứng minh | Regex có thể không khớp; kết quả của subagent chưa tự kiểm |
| `NOT_EVALUATED` | Chưa đo, hoặc thiếu GT/identity | Mọi mục chất lượng OCR hiện nay |
| `STALE` | Bằng chứng thuộc mốc cũ, input hoặc mã đã đổi | Số test hay số liệu trong báo cáo trước ngày `verified_head` |

## Ba lớp bằng chứng, đừng trộn

1. **Test pass** chứng minh hành vi trong ca kiểm, không chứng minh accuracy.
2. **Hash và receipt** chứng minh identity của artifact.
3. **Chất lượng** cần GT độc lập, quy tắc chấm, mẫu số và run tương ứng.

PASS artifact, `SUCCEEDED`, confidence và số test đạt không phải accuracy.

## Thế nào là GT

- **Hợp lệ:** người gán nhãn theo protocol đã khóa; GT tổng hợp theo cấu tạo (chỉ cho stress test); text layer born-digital đã xác minh. Mỗi loại có giới hạn riêng ([04 §5](../../../../cai%20tien%20v2/04_DAC_TA_DO_DAU_9999.md)).
- **Không hợp lệ:** output model, đồng thuận giữa engine, output của chính pipeline, nhãn AI sơ bộ.
- Người dùng đã xác nhận **không có người gán nhãn A/B**. Đừng hỏi lại về phân công.

## Dữ liệu có thật và nơi đặt

| Vị trí | Git theo dõi? | Ghi chú |
| --- | --- | --- |
| `benchmark/ground_truth/clw_page_*.txt` | Có | 4 trang CLW, custody chưa rõ, không thuộc 9 PDF |
| `docs/quality_assurance/templates/` | Có | Template protocol DRAFT, không phải protocol đã khóa |
| `scratch/runs/<run_id>/` | Không | `run.json`, log, JUnit của mỗi lượt pytest |
| `scratch/dev_sessions/<phiên>/` | Không | SESSION, snapshot, bằng chứng phiên |
| `output/` | Không | Kết quả OCR và analysis; chỉ đọc qua script |
| `Doi_Chieu/`, `research_notes/` | Không | Đối chiếu (có bản PaddleOCR-VL-1.6); clone sạch không có. `Test case/` đã bị người dùng xóa ngày 08/11/2026 |

Evidence nằm ở thư mục bị Git bỏ qua phải đánh dấu `local_only` trong registry. Máy khác có thể không có các file đó.

## Nguồn của các con số hay được nhắc

Các số nhãn 0/38, 0/12, 0/13 và 0/3 lấy từ HANDOFF. Nguồn gốc của chúng:
- 0/12 và 0/13: [CT-10](../../../../cai%20tien%20v2/09_LUU_TRU_CAI_TIEN_V7.md#ct-10);
- 0/38: [CT-12](../../../../cai%20tien%20v2/09_LUU_TRU_CAI_TIEN_V7.md#ct-12) và `benchmark/scientific_evaluation/RECOGNITION_RETRY_V7.md`.

Trước khi dùng các số này làm kết luận, phải kiểm lại.
