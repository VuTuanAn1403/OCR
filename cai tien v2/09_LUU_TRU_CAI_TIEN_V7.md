# Lưu trữ thư mục `Cai Tien/` (v7.0)

Thư mục `Cai Tien/` đã bị xóa khỏi working tree. Nội dung nguyên byte vẫn còn trong commit `08f7602`. Muốn đọc lại file nào thì dùng lệnh `git show` ở cột "Đọc lại". Không khôi phục cả thư mục; mọi tài liệu mới viết ở bộ v8 này.

Bằng chứng và số liệu trong các file cũ chỉ đúng tại thời điểm ghi. Trước khi dùng lại phải kiểm lại trên HEAD hiện tại, nếu không thì gắn nhãn `STALE` ([07](07_PHUONG_PHAP_DU_AN_LON_AI.md)).

| ID | File cũ | Đọc lại | Kế thừa ở v8 |
| --- | --- | --- | --- |
| <a id="ct-00"></a>CT-00 | README | `git show 08f7602:"Cai Tien/README.md"` | [00](00_README.md) |
| <a id="ct-01"></a>CT-01 | Tổng hợp điểm yếu, lộ trình | `git show 08f7602:"Cai Tien/01_TONG_HOP_DIEM_YEU_VA_LO_TRINH.md"` | [02](02_KIEM_TOAN_KHOANG_TRONG.md), [03](03_LO_TRINH_V8_THEO_TANG.md) |
| <a id="ct-02"></a>CT-02 | Phương pháp dự án lớn | `git show 08f7602:"Cai Tien/02_PHUONG_PHAP_LAM_VIEC_DU_AN_LON.md"` | [07](07_PHUONG_PHAP_DU_AN_LON_AI.md), [08](08_TOI_UU_TOKEN.md) |
| <a id="ct-03"></a>CT-03 | Backlog 23 ID | `git show 08f7602:"Cai Tien/03_BACKLOG_CAI_TIEN.csv"` | [06](06_BACKLOG_V8.csv), cột `legacy_ref` |
| <a id="ct-04"></a>CT-04 | Kế hoạch triển khai | `git show 08f7602:"Cai Tien/04_HOAN_THIEN_KE_HOACH_TRIEN_KHAI.md"` | [03](03_LO_TRINH_V8_THEO_TANG.md) |
| <a id="ct-05"></a>CT-05 | Trace 65 ca kiểm | `git show 08f7602:"Cai Tien/05_TRACE_KIEM_THU.csv"` | [06](06_BACKLOG_V8.csv) |
| <a id="ct-06"></a>CT-06 | Kết quả triển khai 03/11 | `git show 08f7602:"Cai Tien/06_KET_QUA_TRIEN_KHAI.md"` | Chỉ lưu trữ |
| <a id="ct-07"></a>CT-07 | 14 tiêu chí benchmark | `git show 08f7602:"Cai Tien/07_BO_TIEU_CHI_BENCHMARK_OCR.md"` | [05](05_HOP_DONG_BENCHMARK_ADAPTER.md), [BENCHMARK_PLAN](../docs/quality_assurance/BENCHMARK_PLAN.md) |
| <a id="ct-08"></a>CT-08 | Markdown theo keyword | `git show 08f7602:"Cai Tien/08_CAI_TIEN_MARKDOWN_KEYWORD.md"` | [04](04_DAC_TA_DO_DAU_9999.md) §5 |
| <a id="ct-09"></a>CT-09 | Đặc tả dấu 99,99% | `git show 08f7602:"Cai Tien/09_DAC_TA_BAO_TOAN_DAU_9999.md"` | [04](04_DAC_TA_DO_DAU_9999.md) |
| <a id="ct-10"></a>CT-10 | 9 PDF và nhãn pilot | `git show 08f7602:"Cai Tien/10_TONG_HOP_9PDF_VA_NHAN_PILOT.md"` | Chỉ lưu trữ; số nhãn 0/12 và 0/13 lấy từ đây |
| <a id="ct-11"></a>CT-11 | Nghiệm thu công thức v7.0 | `git show 08f7602:"Cai Tien/11_NGHIEM_THU_CONG_THUC_V70.md"` | Các file `FORMULA_*_V7.md` trong `benchmark/scientific_evaluation/` |
| <a id="ct-12"></a>CT-12 | GAP-03, DC-01, DC-02, TAB_05 | `git show 08f7602:"Cai Tien/12_GAP03_DC01_DC02_TAB05_V70.md"` | Chỉ lưu trữ; ID giữ ở `legacy_ref` |
| <a id="ct-13"></a>CT-13 | Đếm keyword hai tầng | `git show 08f7602:"Cai Tien/13_kien_truc_dem_keyword_va_quy_trinh_tu_dong_hoa_V2.md"` | [README ocr_keywords](../src/ocr_keywords/README.md) |
| <a id="ct-14"></a>CT-14 | Global Alias Rules, Kaggle | `git show 08f7602:"Cai Tien/14_QUY_TRINH_TU_DONG_HOA_ALIAS_RULES_VA_KIEM_THU_KAGGLE.md"` | [README ocr_keywords](../src/ocr_keywords/README.md) |
| <a id="ct-15"></a>CT-15 | `15_DOI_CHIEU_KIEN_TRUC_OCR_20261107.md` | Không có: file này chưa từng xuất hiện trong lịch sử Git | Nội dung tương ứng: [CURRENT_ARCHITECTURE](../docs/quality_assurance/CURRENT_ARCHITECTURE.md) và [01](01_RADAR_CONG_NGHE_THEO_TANG.md) |
| <a id="ct-tpl"></a>CT-TPL | 3 template | `git show 08f7602:"Cai Tien/templates/benchmark_acceptance_protocol.example.yaml"` | Đã khôi phục nguyên byte vào [docs/quality_assurance/templates](../docs/quality_assurance/templates/benchmark_acceptance_protocol.example.yaml) |
| <a id="ct-ev"></a>CT-EV | 17 file `evidence/` | `git ls-tree 08f7602 "Cai Tien/evidence/"`; ví dụ `git show 08f7602:"Cai Tien/evidence/verification.json"` | Chỉ lưu trữ; là bằng chứng lịch sử, không phải phép đo hiện tại |

## Template đã khôi phục

Ba file dưới đây được ghi lại bằng `git cat-file blob`. Sau khi ghi, `git hash-object` cho đúng sha blob gốc:

| File | Blob |
| --- | --- |
| `benchmark_acceptance_protocol.example.yaml` | `4497bade` |
| `diacritic_annotation.example.json` | `efc9f237` |
| `formula_acceptance_policy.example.json` | `674cdf9a` |

Ba test đọc chúng là `test_protocol_preflight.py`, `test_release_gate.py` và `test_qa_paired_effects.py`; test thứ tư `test_qa_report.py` dùng chung qua `DRAFT`. Cả bốn đã trỏ sang `docs/quality_assurance/templates/`.

## Liên kết cũ

`scripts/check_knowledge_map.py` báo lỗi khi bất kỳ tài liệu Markdown nào còn liên kết vào `Cai Tien/`. Có ba ngoại lệ:
- `CLEANUP_REPORT.md` (báo cáo lịch sử);
- `docs/development/HUONG_DAN_COMMIT_VA_PUSH_GITHUB.md` (checklist phát hành v7.0, chứa lệnh `git add` cũ; không chạy lại các lệnh này);
- chính file này.
