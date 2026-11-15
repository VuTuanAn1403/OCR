# Báo cáo khóa baseline (V8-001)

Mã khóa `BASELINE-V8-20261108-001`, chụp lúc 2026-11-08 13:51:55 UTC. Trạng thái **LOCKED**.

Manifest đầy đủ nằm ở `scratch/benchmarks/BASELINE-V8-20261108-001/baseline_lock.json` (chỉ có ở máy local; sha256 `d3276479c549ece023ce13e5dfa491a8324928814c5d485b9d6fd8247d2b28bc`). Lệnh tạo: `.venv/Scripts/python.exe -B scripts/lock_baseline.py`.

## Các khóa baseline và ứng viên hiện hành (`V8-001`)

| Lock ID | Mốc mã / cấu hình | Thời gian UTC | `portable_identity` / sha manifest | Output đã `MATCH` |
| --- | --- | --- | --- | --- |
| `BASELINE-V8-20261113-001` (baseline Q1) | `c681e87`, `config/profiles.yaml` (`4d867edbd1b55c23…`), extraction `a58d78d21ad45c97` | 2026-11-12 17:33:03 | `fa44665e0f7df3fb…` / `e2a048b11323b8ff…` | Dev `006` (9/9, `938`p); holdout `v8_h01_baseline_pairs6_20261113` (6/6, `468`p) |
| `BASELINE-V8-20261113-002` (ứng viên `×2`) | `c681e87`, `config/candidates/v8_050_line_upscale2.yaml` (`09008d18a0f9c718…`) | 2026-11-12 17:33:25 | `00c327d6a44684a1…` / `73c03802a6466df6…` | Dev `007` (9/9, `938`p); holdout `v8_h02_upscale2_pairs6_20261113` (6/6, `468`p) |
| `BASELINE-V8-20261115-002` (ứng viên `V8-065`) | `480285b` (merge `1a6864c`), `config/candidates/v8_065_vgg_transformer.yaml` (`15a7612f02f53e62…`), extraction `8d87703c93149dbe` | 2026-11-14 17:43:06 | `414243ec6ab373b0…` / `2f9e71d302be1dc2…` | Dev `v8_065_vgg_transformer_dev_20261114` (9/9, `938`p); holdout `v8_h03_vgg_transformer_pairs6_20261115` (6/6, `468`p) |

Khóa `20261115-002` dùng `--env-root .venv-v62`, registry `models/v62/runtime-models-v8-065-vgg-transformer.json` (sha `db43ebfa5dc74354…`) và trọng số `vgg_transformer.pth` (sha `380512193a8b6cbf…`). `check_baseline_identity.py --new-inputs --root` xác minh holdout `h03` khớp trọn bộ runtime của khóa.

## Lịch sử khóa ban đầu (`001`–`003`, 08–09/11)

- `BASELINE-V8-20261108-001` (HEAD `08f7602`, `PIPELINE_VERSION 7.0.0`, `portable_identity` `77c03ad9104287c5…`, diff sạch chỉ `README`): `NOT_RUN` / `NOT_EVALUATED`.
- `BASELINE-V8-20261109-002` (`24a5558`) & `BASELINE-V8-20261109-003` (`20207a2`, sha `fbd278b8b5bcc525…`, `portable_identity` `9ca57543016d9c68…`, extraction `ccdbe84a3691d645`): bật PP-OCRv6 det + retry dấu `V8-030`; `output/v8_baseline_20261109_r2` `SUCCEEDED` 9/9 (`938`p, 3 trang fallback Docling).
- `LOCKED` chỉ xác nhận preflight `ocr_pipeline.backend.prepare_backend`, lock cài trong từng venv worker và snapshot 9 PDF đầu vào; mọi chất lượng giữ `NOT_EVALUATED` khi chưa có GT độc lập.

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

- `portable_identity` gồm fingerprint mã, sha profile, sha model và sha lock (không chứa đường dẫn tuyệt đối) để đối chiếu khóa giữa các môi trường.
- `ocr_identity` của từng PDF chứa đường dẫn tuyệt đối của model và interpreter (`OCR_IDENTITY_KEYS`), dùng trong `ocr_receipt.json` để quyết định có OCR lại hay không.
- Các output đã `MATCH` hiện có ở máy local: dev `006`, `007`, `v8_065_vgg_transformer_dev_20261114` (`9/9`); holdout `h01`, `h02`, `v8_h03_vgg_transformer_pairs6_20261115` (`6/6`).

## Giới hạn

- Prediction baseline V8-006 ở `output/v8_006_arena1536_20261112` (dev) và `output/v8_h01_baseline_pairs6_20261113` (holdout `pairs6`).
- Khóa mất hiệu lực khi đổi `src/**/*.py`, `config/profiles.yaml` (hoặc config candidate), registry/model, lock, gói venv worker hoặc PDF đầu vào. Khi đó chạy lại `scripts/lock_baseline.py` để tạo khóa mới; không sửa khóa cũ.
- GPU RTX 2050 có 4 GB VRAM; VLM/candidate vượt arena bị từ chối ở preflight/runtime (`KEEP BASELINE` ở P7).
- Driver CUDA và cấu hình phần cứng được ghi lại trong lock, nhưng không nằm trong `ocr_identity`.
