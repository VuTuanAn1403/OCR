# VLM fallback challenger (V8-090)

Adapter chỉ cho VLM xem các trang có chẩn đoán lỗi (`selection.py`). Nó ghi chuỗi của VLM nguyên văn thành bản ghi `page_text` riêng, gắn `review_required`, và không ghi đè chữ của production (`adapter.py`). Model chỉ được nạp từ thư mục cục bộ, sau khi qua cổng catalog và mọi file khớp pin (`backends.py`, `pins/`).

Chất lượng: `NOT_EVALUATED`. Kết quả chạy chỉ là giả thuyết để người duyệt xem; muốn biết đúng sai phải có GT.

## Vintern-1B-v3.5 (đã ghim ngày 10/11/2026)

- **Nguồn:** `5CD-AI/Vintern-1B-v3_5`, revision `b98f263eab246eb5269ade64edbdca8a887dc44d`, licence MIT.
- **Kích thước:** 15 file, tổng 3.757.989.488 B. `model.safetensors` (fp32) có sha256 `296a16a6…be05`. Đủ hash từng file nằm trong [`pins/vintern-1b-v3.5.json`](pins/vintern-1b-v3.5.json).
- **Mã tùy biến:** model cần `trust_remote_code`, tức là chạy 5 file Python của repo (`configuration_intern_vit.py`, `configuration_internvl_chat.py`, `conversation.py`, `modeling_intern_vit.py`, `modeling_internvl_chat.py`). Backend kiểm git oid của từng file trước khi nạp, nên mã chạy đúng là mã của revision đã ghim. Tác nhân AI không tự thực thi mã này; người dùng tự tải và tự chạy lần đầu.
- **VRAM:** chưa đo trên RTX 2050 4 GB. Backend dùng bf16, tối đa 6 ô 448 px, giải mã tham lam, không phạt lặp (để không làm méo chữ số lặp).

## Lệnh cho người dùng

Chạy từ gốc repo, khi không có batch OCR nào đang dùng GPU.

1. Tạo venv riêng (không cài vào `.venv` hay `.venv-v62/*`):

   ```powershell
   py -3.11 -m venv .venv-v8-vintern
   .venv-v8-vintern/Scripts/python.exe -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
   .venv-v8-vintern/Scripts/python.exe -m pip install "transformers==4.46.3" accelerate timm einops pillow pymupdf "huggingface_hub[cli]"
   ```

2. Tải đúng revision (khoảng 3,76 GB; `models/v8/` đã nằm trong `.gitignore`):

   ```powershell
   .venv-v8-vintern/Scripts/hf.exe download 5CD-AI/Vintern-1B-v3_5 --revision b98f263eab246eb5269ade64edbdca8a887dc44d --local-dir models/v8/vintern-1b-v3_5
   ```

3. Xem qua 5 file `.py` trong `models/v8/vintern-1b-v3_5/` trước khi cho chạy.

4. Chạy thử 2 trang để kiểm VRAM:

   ```powershell
   .venv-v8-vintern/Scripts/python.exe scripts/run_vlm_challenger.py --output output/v8_003_baseline_20261109 --candidate vintern-1b-v3.5 --weights models/v8/vintern-1b-v3_5 --pdf-root inputs --experiment-id EXP-V8-VLM-20261110-001 --max-pages 2 --report scratch/v8/v8_090_vlm_smoke_20261110.json
   ```

5. Nếu ổn, chạy đủ 137 trang với experiment mới (`EXP-V8-VLM-20261110-002`) và bỏ `--max-pages`.

Bản ghi nằm ở `scratch/benchmarks/<experiment>/predictions/<tài liệu>.jsonl`, manifest ở `manifests/vlm_run.json`. Trang lỗi (ví dụ hết VRAM) thành `MISSING_OUTPUT` và vẫn ở trong mẫu số. Lệnh từ chối với exit 3 nếu thiếu file, sai hash, hoặc catalog và pin không khớp.
