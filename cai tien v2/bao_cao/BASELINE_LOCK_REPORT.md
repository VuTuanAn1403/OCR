# Báo cáo khóa baseline (V8-001)

Mã khóa `BASELINE-V8-20261108-001`, chụp lúc 2026-11-08 13:51:55 UTC. Trạng thái **LOCKED**.

Manifest đầy đủ nằm ở `scratch/benchmarks/BASELINE-V8-20261108-001/baseline_lock.json` (chỉ có ở máy local; sha256 `d3276479c549ece023ce13e5dfa491a8324928814c5d485b9d6fd8247d2b28bc`). Lệnh tạo: `.venv/Scripts/python.exe -B scripts/lock_baseline.py`.

## Khóa hiện hành: `BASELINE-V8-20261109-002` (09/11, HEAD `24a5558`)

Khóa 001 bên dưới chụp trước một lần sửa `src/ocr_keywords/alias_map.py` lúc 01:58. Lần sửa đó làm analysis đổi thành `556a9a221118acfe`, nên khóa 001 không còn khớp HEAD về analysis/publication. `ocr_identity` vẫn đúng.

| Mục | Giá trị |
| --- | --- |
| Trạng thái | **LOCKED**, `problems` rỗng; chụp lúc 2026-11-08 19:16:11 UTC; working tree sạch |
| Manifest | `scratch/benchmarks/BASELINE-V8-20261109-002/baseline_lock.json`, sha256 `750a20e64e9010d3403fd909f9591c4267387b066f787286d69bc59e7e21d5f9` |
| Fingerprint extraction / analysis / publication | `20e15efae22917bd` / `556a9a221118acfe` / `cb48f3d161a82019` |
| `portable_identity` | `465518dab5b48d11644a79c00d8989c1cc70af4dc5d8f2c711b357eb37ff1240` |
| `ocr_identity` 9 PDF | Trùng từng giá trị với khóa 20261108-001 |

Từ V8-033 (09/11, sửa `src/ocr_text/unicode_normalizer.py`), mã làm việc có OCR identity khác khóa này. Prediction V8-006 vẫn gắn với `24a5558`. Lần chạy dự đoán kế tiếp cần commit rồi khóa mới.

## Prediction baseline V8-006

| Mục | Kết quả |
| --- | --- |
| Output | `output/v8_baseline_20261109_r2`: 9/9 PDF `SUCCEEDED`, 938/938 trang CUDA, exit 0 |
| Audit `--validate` | exit 0, `scratch/v8/v8_006_audit_r2_20261109.json`; validation `NEEDS_REVIEW` 0 lỗi |
| Identity | `check_baseline_identity.py` **MATCH** 9/9 với khóa 002, `scratch/v8/v8_006_identity_r2_20261109.json` |
| Keyword `literal_v1` | 164 lượt, trùng `keyword_counts.json`; quality `NOT_EVALUATED` |
| Docling fallback | 3/938 trang `FAILED_FALLBACK` (AAA, ACL, ASM: worker exited). Trang ACL 22 thành công ở 5 lần chạy sau; log pha bị ghi đè nên chưa rõ nguyên nhân |

Lần 1 (`output/v8_baseline_20261109`) dừng với `IdentityMismatch` vì `src/` bị sửa khi batch chạy; giữ làm bằng chứng.

Khóa trung gian `BASELINE-V8-20261109-001` (analysis `3c33830f271e1c29`, manifest sha256 `80a68553…`) đã cũ về analysis; chi tiết ở bản tại `24a5558`.

## LOCKED nghĩa là gì

- `ocr_pipeline.backend.prepare_backend`, đúng bước preflight mà CLI chạy trước mỗi batch, đã chấp nhận cấu hình: profile hợp lệ, mọi file model khớp sha trong registry, hai interpreter worker tồn tại, phép thử CUDA qua được dưới GPU lease.
- Hai dependency lock được kiểm **bên trong** interpreter tương ứng (`ocr_runtime.dependency_lock.verify_installed_lock`).
- 9 PDF được kiểm kê bằng `ocr_pipeline.batch.input_snapshot`. `ocr_identity` của từng PDF tính bằng `GPUProcessor.request_for` với tham số mặc định của CLI (`assets=png`, `output_mode=compact`).

LOCKED **không** có nghĩa là đã chạy OCR. Inference: `NOT_RUN`. Chất lượng: `NOT_EVALUATED`. Chưa có prediction baseline nào cho P3/P4.

## Mã nguồn

| Mục | Giá trị |
| --- | --- |
| HEAD | `08f7602ea8bd7fa4db0775924f47ac9960306e58` (nhánh `main`) |
| Working tree | Có thay đổi chưa commit (79 bản ghi); sha diff toàn bộ `a7d1dfa416ea615a…` |
| Thay đổi trong phạm vi mã | `M src/ocr_keywords/README.md`; sha diff `52e81568df5b5962…` |
| `PIPELINE_VERSION` | `7.0.0` |
| Fingerprint extraction / analysis / publication | `20e15efae22917bd` / `c4ad6f5589213bf7` / `fddd16ef5acbb002` |
| Profile | `unified_gpu_full_ocr` trong `config/profiles.yaml` (sha256 `4d867edbd1b55c23143cfb336ddbc8bfe9542f0f626ec703a30a81bd9de74505`) |
| Digest profile đã chuẩn hóa | `b9633069c5c173e79f41be734f45f6b557609069703d4cd3713fa7b4d25e4525` |

Phạm vi mã gồm `src`, `config`, `models`, `requirements`, `scripts/docling_structure_worker.py` và `pyproject.toml`. Thay đổi duy nhất trong phạm vi này là một README; fingerprint chỉ băm `src/**/*.py`, nên identity OCR bằng với HEAD.

## Model (36 file đã kiểm sha)

| Thành phần | File | sha256 |
| --- | --- | --- |
| Nhận dạng VietOCR | `models/vietocr/vgg_seq2seq.pth` | `0921503a41375a0584268e23ef3d414ea478a8fe8777865c7745d38f2d0bc5db` |
| Cấu hình VietOCR | `models/vietocr/vgg-seq2seq.yml` | `1aaae4bbd7601ce465ffb7894c0f570cbf687d2d97979e054e2cbb40edd97a9a` |
| Phát hiện PP-OCRv4 ONNX | `models/v62/ch_PP-OCRv4_det_infer.onnx` | `d2a7720d45a54257208b1e13e36a8479894cb74155a5efe29462512d42f49da9` |
| Layout Heron | `8f39ad3c0b4c58e9c2d2c84a38465abf757272d8/model.safetensors` | `00333a43451945aaf89db8ca9c0a17e75d1537c17db60fdb91aa95f4c7929e0c` |
| TableFormer accurate | `fc0f2d45e2218ea24bce5045f58a389aed16dc23/model_artifacts/tableformer/accurate/tableformer_accurate.safetensors` | `2a7d6c924b3cd12fb99a09280ca9c33a89c5d60b93253617d2e088c1a40374d9` |
| CodeFormulaV2 | `ecedbe111d15c2dc60bfd4a823cbe80127b58af4/model.safetensors` | `4b04e77af34c4e682a7ab1617628340d658f3c3dcd12456dd2a7fff805cf79d2` |
| Font OCR bridge | `assets/fonts/NotoSans-Regular.ttf` | `b85c38ecea8a7cfb39c24e395a4007474fa5a4fc864f6ee33309eb4948d232d5` |
| Registry model | `models/v62/runtime-models.json` | `1b50ad30b07c59fb872349f2f05020bfa86adde905be01566a2021971f66630a` |

Danh sách đủ 36 file nằm trong manifest (`models.sha256`). Revision snapshot Docling: Heron `8f39ad3c`, docling-models `v2.3.0` (`fc0f2d45`), CodeFormulaV2 `ecedbe11`.

## Môi trường chạy

| Mục | Giá trị |
| --- | --- |
| GPU | NVIDIA GeForce RTX 2050, 4096 MiB, driver 592.00, CUDA driver 13.1 |
| Interpreter text | `.venv-v62/text/Scripts/python.exe`: torch `2.12.1+cu126`, onnxruntime-gpu `1.23.2`, provider TensorrtExecutionProvider, CUDAExecutionProvider, CPUExecutionProvider |
| Interpreter docling | `.venv-v62/docling/Scripts/python.exe`: torch `2.12.1+cu126`, docling-slim `2.137.0` |
| Phép thử CUDA | text: `cuda:0`; docling: `cuda:0` (trạng thái `CAPABILITY_ONLY`: chỉ xác nhận khả năng, không phải bằng chứng inference) |
| Lock `requirements/v62/windows-text-gpu.lock` | sha256 `af3b1a661537a14174097b6f4adc661de362c0f940ac1191df4dc0e1ca28256c`; VERIFIED trong interpreter text (91 gói) |
| Lock `requirements/v62/windows-docling-gpu.lock` | sha256 `656fa4ec24b95f3a0df38096c4db424a8dccadaee11cd2b0cef9a60c1c278c6f`; VERIFIED trong interpreter docling (83 gói) |

## Đầu vào

9 PDF, tổng 938 trang. Không có lỗi nguồn và không có file trùng.

| PDF | Byte | Trang | sha256 | `ocr_identity` |
| --- | ---: | ---: | --- | --- |
| AAA_Baocaothuongnien_2020.pdf | 4.571.894 | 232 | `5d9a9d62e2c2ba84788a135d7c0e8d58360b6df5d6e6e838769d7a63b51d1a6f` | `8c718bea2ffff462…` |
| ABT_Baocaothuongnien_2020.pdf | 12.836.079 | 43 | `27317a0ee4a9662215141996bac7fbf5c36fa13a304d32d3558d3ccf346e85ce` | `f3e3569dd6316918…` |
| ACL_Baocaothuongnien_2022.pdf | 18.870.870 | 24 | `83d24fc1b36930871e8e7e7972708c1578d37cf6ea76e0e4efd6de7ac2c9c507` | `cab4e0eb6865674d…` |
| AGR_Baocaothuongnien_2020.pdf | 3.219.212 | 84 | `4d9fa11c39bfbdbdaf754b8b5328f84ddbd3307c4cefd12d6381304f4eadd4f2` | `145088353e950880…` |
| AGR_Baocaothuongnien_2022.pdf | 6.190.091 | 102 | `237b6caa085be21a853ac0621ec2c138943a5078744f6e98c311c68bf2d48a80` | `dfc8926927117d57…` |
| ASM_Baocaothuongnien_2022.pdf | 25.389.230 | 164 | `a81fed2d23d95b2c324328d9a6892522afddf95bb2364c3bb02ba0139bed8b75` | `6ee62f0fe02908f4…` |
| BCE_Baocaothuongnien_2022.pdf | 10.280.609 | 62 | `92897158288062a4aa7c1a93c52bfbacd7e77f0927b42d9adc7914fb5ed91c99` | `fa7a232bde6afb13…` |
| BHN_Baocaothuongnien_2022.pdf | 12.820.195 | 75 | `65ff3db7fc1bdb60d3fb30a02f7d8aa0662aa2e0157b3e55869761ba30edea30` | `faa27cd3f01f82c5…` |
| VIC_Baocaothuongnien_2020.pdf | 8.723.631 | 152 | `094a6e4774e410da67810efecd43aa1ef50eff2d117bfc837f737430afd80e77` | `eb4db90a20d74a68…` |

## Identity dùng để so sánh

- `portable_identity` = `77c03ad9104287c57428a8ba4c43d84115666b3f2b0ceee8fe1277d3f57269e7`. Digest này gồm fingerprint mã, sha profile, sha model và sha lock, không gồm đường dẫn tuyệt đối, nên dùng được để so baseline giữa các máy.
- `ocr_identity` của từng PDF thì chứa cả đường dẫn tuyệt đối của model và interpreter (`OCR_IDENTITY_KEYS`), nên chỉ đúng trên máy này. Đây là khóa mà receipt `ocr_receipt.json` dùng để quyết định có OCR lại hay không.
- Output OCR có sẵn: tìm `output/*/*/ocr_receipt.json` không có receipt nào khớp; `output/` đang trống. Vì vậy chưa có extraction baseline nào để tái dùng.

## Giới hạn

- Prediction baseline V8-006 có ở `output/v8_baseline_20261109_r2` (chỉ máy local). Challenger P3/P4 so với output này theo `ocr_identity`.
- Khóa mất hiệu lực khi đổi bất kỳ thứ nào sau: `src/**/*.py`, `config/profiles.yaml`, registry hoặc file model, lock, gói trong venv worker, PDF đầu vào. Khi đó chạy lại `scripts/lock_baseline.py` để tạo khóa mới; không sửa khóa cũ.
- GPU có 4 GB VRAM. Đây là ràng buộc khi chọn challenger: VLM từ vài tỷ tham số trở lên ở [01](../01_RADAR_CONG_NGHE_THEO_TANG.md) có thể không chạy được trên máy này (`HYPOTHESIS`, cần đo ở P7).
- Driver CUDA và cấu hình phần cứng được ghi lại, nhưng không nằm trong `ocr_identity`.
