# Kế hoạch làm gọn workspace OCR_pdf

Ngày lập: 23/10/2026. Workspace: `C:\kk_2\OCR_pdf`.

Trạng thái: **đã thực hiện lượt đầu ngày 23/10/2026**. Kết quả và các mục còn mở ở [mục 8](#8-kết-quả-thực-hiện-23102026).

## 1. Mục tiêu và phạm vi

Làm rõ môi trường còn sử dụng, tập trung nơi sinh file tạm và giúp cây Explorer dễ đọc. Mọi kết quả OCR, ledger, model, nguồn PDF và bằng chứng nghiệm thu cần thiết phải được bảo toàn.

Thực hiện theo ba phần riêng:

1. **Kiểm kê:** xác định vai trò, nơi tham chiếu và trạng thái sử dụng của từng thư mục.
2. **Ngăn phát sinh lộn xộn:** thống nhất nơi ghi file mới, sau đó cấu hình cách hiển thị.
3. **Dọn trên ổ đĩa:** xử lý từng mục đã được phân loại và có bằng chứng đủ điều kiện.

Ẩn trong Explorer chỉ thay đổi cách hiển thị; dung lượng và dữ liệu trên ổ đĩa vẫn giữ nguyên. `.gitignore` kiểm soát việc Git theo dõi file, không phải cơ chế sao lưu hoặc dọn dữ liệu.

Giữ kiến trúc một repository, một distribution và các package `ocr_*` trong `src/`. Chưa đổi vị trí `src`, `tests`, `config`, `requirements`, `scripts`, `assets`, `benchmark`, `docs`, `docker`, `kaggle`, `examples` hoặc các lệnh tương thích đang dùng.

## 2. Kiểm kê môi trường Python

Bảng dưới mô tả vai trò cần đối chiếu, không khẳng định mọi môi trường đang hoạt động.

| Đường dẫn | Vai trò cần xác minh | Hướng xử lý ban đầu |
| --- | --- | --- |
| `.venv` | Supervisor/app CPU theo thiết kế; dependency thực tế có thể rộng hơn | Giữ, ghi rõ bộ dependency hiện có |
| `.venv-v62/text` | Worker chữ/layout V6.3 và một số luồng V6.2 | Giữ khi backend còn chọn qua `--env-root` |
| `.venv-v62/docling` | Worker Docling cách ly | Giữ cùng bộ runtime đã khóa |
| `.venv-docling` | Worker của luồng legacy/setup cũ, có thể được `OCR_DOCLING_PYTHON` chọn | Kiểm profile, biến môi trường, Docker/setup và consumer |
| `.venv-v62-clean` | Môi trường phụ; chưa xác nhận còn được dùng | Đánh dấu `UNKNOWN` tới khi kiểm xong |
| Các venv ngoài checkout | Môi trường wheel/kiểm thử hoặc runtime cấu hình bên ngoài | Kiểm cả đường dẫn từ cấu hình và log, không chỉ thư mục gốc |

Với từng interpreter, ghi lại:

- Đường dẫn executable, `sys.prefix`, `sys.base_prefix`, phiên bản Python và danh sách/phiên bản dependency.
- Vai trò CPU/text/Docling/legacy/test, lock tương ứng và kết quả kiểm dependency.
- Nơi tham chiếu: CLI, profile, biến môi trường, IDE, script, notebook, CI, manifest và request của batch.
- Process/job còn dùng, batch cần resume và ngày kiểm kê. Không đọc được trạng thái process thì ghi `UNKNOWN`.
- Phân loại `KEEP_ACTIVE`, `KEEP_COMPAT`, `ARCHIVE_CANDIDATE` hoặc `UNKNOWN`, kèm lý do và bằng chứng.

Chỉ đọc metadata khi kiểm kê, không import Torch/Docling/VietOCR để đoán vai trò, không tải model hay sync venv. Giữ đường dẫn lexical của interpreter Linux; không thay executable venv bằng đích symlink của Python hệ thống.

**Điều kiện kết thúc:** mọi môi trường được tìm thấy có một hàng kiểm kê; môi trường đề nghị ngừng dùng đã được kiểm consumer, process và nghĩa vụ resume. Tên có chữ `clean`, tuổi thư mục hoặc không có tham chiếu trong Git chưa đủ để kết luận bỏ được.

## 3. Thống nhất nơi sinh file mới

Bố cục đề xuất cho các lượt phát triển/kiểm thử mới:

```text
scratch/
  runs/<run_id>/
    tmp/         # file tạm của lượt chạy
    pytest/      # pytest basetemp
    logs/        # stdout, stderr, nhật ký
    reports/     # báo cáo trung gian
    build/       # bản sao source và staging đóng gói
    evidence/    # JUnit, hash, manifest, kết luận cần giữ
  codex-review-*/       # bằng chứng giám sát hiện hữu, giữ đường dẫn
  codex-development-*/ # bằng chứng triển khai hiện hữu, giữ đường dẫn
.cache/                # cache runtime theo cấu hình hiện hành
output/                # kết quả OCR/batch cần lưu
```

`run_id` phải duy nhất, gồm thời điểm và mã ngắn; không tái sử dụng basetemp của một lượt trước vì pytest có thể dọn nội dung của nó.

| Nguồn phát sinh | Cách gom cho lượt mới |
| --- | --- |
| `.pytest_tmp`, các basetemp rải rác | Truyền `--basetemp=scratch/runs/<run_id>/pytest` |
| `.pytest_cache`, `pytest-cache-files-*` | Các lượt kiểm bằng chứng dùng `-p no:cacheprovider`; nếu cần cache thì cấu hình `cache_dir` vào vùng của lượt chạy |
| File tạm từ script/OS | Thêm tham số thư mục tạm hoặc truyền env cho riêng process con; không đổi `TEMP`/`TMP` toàn máy |
| Log/JUnit/báo cáo kiểm thử | Ghi vào `logs/` và `evidence/` của cùng `run_id` |
| Build thử | Dùng bản sao source/staging trong `build/`, giữ wheel và báo cáo cần kiểm chứng |
| Cài wheel để nghiệm thu | Venv mới và CWD nằm **ngoài checkout**, chạy kiểm theo P10/P13; lưu báo cáo về vùng evidence |
| Cache pipeline thử nghiệm | Chọn `OCR_CACHE_DIR` tuyệt đối cho lượt mới khi cần cách ly; kiểm consumer nào còn ghi cứng đường dẫn |
| Báo cáo PDF/Word/Excel mới | Producer ghi vào thư mục báo cáo có tên, không mặc định tạo thêm file ở gốc |

**GPU lease phải dùng chung giữa mọi process cạnh tranh cùng GPU.** Giữ vị trí lease đang được sử dụng; không đặt `OCR_GPU_LEASE_DIR` theo từng `run_id` hoặc cache riêng. Không đổi đường dẫn lưu trữ trong lúc batch đang chạy.

Ví dụ tổ chức một lượt pytest nhẹ, chạy từ gốc dự án:

```powershell
$runId = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
$runRoot = Join-Path (Get-Location).Path ('scratch/runs/' + $runId)
New-Item -ItemType Directory -Path "$runRoot/logs", "$runRoot/evidence" -Force | Out-Null
$oldBytecode = $env:PYTHONDONTWRITEBYTECODE
try {
    $env:PYTHONDONTWRITEBYTECODE = '1'
    & .venv/Scripts/python.exe -B -m pytest tests/unit/contracts tests/unit/artifacts -q -p no:cacheprovider --basetemp="$runRoot/pytest" --junitxml="$runRoot/evidence/junit.xml" *> "$runRoot/logs/pytest.log"
    $testExit = $LASTEXITCODE
    Write-Output "pytest exit code: $testExit; evidence: $runRoot"
} finally {
    $env:PYTHONDONTWRITEBYTECODE = $oldBytecode
}
```

Ví dụ trên tạo output mới, không phải lệnh dọn. Không chạy lại test chỉ để làm đẹp thư mục. Wrapper CI phải truyền tiếp đúng exit code thay vì biến lượt kiểm lỗi thành thành công.

`scripts/run_pytest_scratch.py` làm đúng các bước trên và chạy được trên cả Windows lẫn Linux. Mỗi lần gọi, script tạo một `run_id` mới và từ chối thư mục lượt đã có. Pytest luôn chạy từ gốc checkout, bất kể CWD của người gọi. `TMP`/`TEMP`/`TMPDIR` của process con trỏ vào `tmp/`. Script ghi thêm `run.json` (lệnh, HEAD, exit code) và trả đúng exit code của pytest:

```powershell
.venv/Scripts/python.exe scripts/run_pytest_scratch.py tests/unit/contracts tests/unit/artifacts -q
```

Lượt chạy tay hoặc từ IDE còn bật cache vẫn tạo `.pytest_cache` ở gốc; Explorer ẩn thư mục này. Lượt cần cache truyền `-o cache_dir=scratch/runs/<run_id>/pytest-cache`. Không đặt `cache_dir` trong `pytest.ini`: khi `-p no:cacheprovider` tắt plugin, khóa đó thành khóa lạ và mọi lượt bằng chứng, CI hay README đều sinh `PytestConfigWarning`. Khóa này đã được thêm rồi gỡ ngày 23/10.

**Điều kiện kết thúc:** các producer trong phạm vi đã có đường dẫn ghi rõ ràng; một lượt kiểm có liên quan không tạo thêm thư mục pytest/log tùy ý ở gốc. Không đổi tên các thư mục evidence cũ để ép chúng vào bố cục mới.

## 4. Làm gọn Explorer trong VS Code

Đề xuất gộp các khóa sau vào `.vscode/settings.json` hiện có, giữ các thiết lập khác. Đây là cấu hình workspace theo [tài liệu VS Code](https://code.visualstudio.com/docs/configure/settings#workspace-settingsjson-location).

```json
{
  "files.exclude": {
    "**/__pycache__": true,
    "**/*.egg-info": true,
    "**/.venv*": true,
    "**/.pytest_cache": true,
    "**/.pytest_tmp": true,
    "**/pytest-cache-files-*": true,
    ".cache": true,
    "scratch": true,
    "tmp": true,
    "build": true,
    "dist": true
  },
  "search.exclude": {
    "**/__pycache__/**": true,
    "**/*.egg-info/**": true,
    "**/.venv*/**": true,
    "**/.pytest_cache/**": true,
    "**/.pytest_tmp/**": true,
    "**/pytest-cache-files-*/**": true,
    ".cache/**": true,
    "scratch/**": true,
    "tmp/**": true,
    "build/**": true,
    "dist/**": true
  }
}
```

`files.exclude` và `search.exclude` ảnh hưởng hiển thị/tìm kiếm. Khi cần tra log/evidence, mở đường dẫn trực tiếp hoặc tạm tắt các bộ lọc loại trừ trong Search; xem [hướng dẫn tìm kiếm của VS Code](https://code.visualstudio.com/docs/editing/codebasics#advanced-search-options). Việc ẩn không thu hồi dung lượng hoặc bảo vệ dữ liệu khỏi bị xóa.

Giữ hiển thị các thư mục mã/cấu hình/tài liệu và `inputs`, `models`, `output`, `reports`, `research_notes` trong cấu hình mặc định này. Nếu dùng Antigravity hoặc IDE khác, kiểm thiết lập tương ứng của phiên bản đó trước khi áp dụng; không tự sửa User Settings toàn máy.

**Điều kiện kết thúc:** Explorer gọn hơn, các đường dẫn vẫn tồn tại; có thể mở lại evidence và khôi phục cách hiển thị bằng cách bỏ đúng các khóa vừa thêm.

## 5. Phân loại trước khi dọn trên ổ đĩa

| Nhóm | Ví dụ | Điều kiện xử lý |
| --- | --- | --- |
| Giữ dữ liệu nguồn/kết quả | `inputs`, `models`, `output`, GT có provenance, PDF/XLSX người dùng | Không thuộc nhóm xóa cache; có kế hoạch sao lưu riêng nếu chuyển nơi lưu |
| Giữ bằng chứng | JUnit, log được dẫn trong nghiệm thu, hash, manifest, baseline, patch review | Giữ nội dung và đường dẫn tham chiếu; nếu lưu trữ lại phải có mapping và kiểm hash |
| Giữ runtime/compatibility | Các venv, `requirements-*.txt`, `setup.py`, `run_*.py` | Kiểm consumer trước; không tự gom hoặc bỏ vì giống tên |
| Có thể xem xét dọn | Bytecode, pytest temp, build staging tái tạo được | Xác nhận không có job dùng, không chứa dữ liệu người dùng và không còn nghĩa vụ bằng chứng |
| Cache runtime | Stage cache, job Docling, log worker | Xác định khả năng resume và các đường dẫn output đang tham chiếu trước khi xử lý |
| Chưa rõ | `tmp`, thư mục cũ, file ở gốc chưa xác định producer | Giữ nguyên, truy nguồn trước khi phân loại tiếp |

Không coi toàn bộ `scratch`, `tmp` hoặc `.cache` là rác. Chẳng hạn, báo cáo dọn trước ghi `tmp/word_keyword_report` có ảnh được script tạo tài liệu dùng lại; worker log có thể được manifest/output tham chiếu.

Mỗi đợt dọn cần manifest gồm đường dẫn tuyệt đối, nhóm dữ liệu, lý do, nơi tham chiếu, trạng thái process, hash khi cần, hành động dự kiến và cách khôi phục. Kiểm target đã resolve nằm trong phạm vi workspace được chỉ định; không đi theo junction/symlink ra ngoài khi tính dung lượng hoặc xử lý đệ quy. Đường dẫn không rõ hoặc không đủ quyền kiểm tra giữ trạng thái `UNKNOWN`.

Với batch cần lưu, sao lưu cả đơn vị batch, gồm ledger SQLite, WAL/SHM nếu còn, snapshot, receipt, artifact và workbook. Kiểm bản sao theo [quy trình P12](CAU_HINH_VA_DU_LIEU.md#sao-lưu-và-khôi-phục-kết-quả-batch). Không sửa hash/receipt/ledger để làm output cũ hợp lệ sau khi dọn.

Chuyển checkout, venv hoặc đường dẫn model có thể ảnh hưởng identity và resume. Nếu cần chuyển, lập thay đổi riêng có kiểm tương thích; không di chuyển chúng trong đợt dọn cache thông thường.

## 6. Thứ tự thực hiện và sản phẩm bàn giao

| Bước | Việc thực hiện | Sản phẩm cần có |
| --- | --- | --- |
| 1 | Chụp trạng thái trước, ghi nhận công việc đang chạy, kiểm kê consumer và môi trường | `inventory.json`, bảng môi trường, danh sách `UNKNOWN` |
| 2 | Chốt quy ước `run_id`, nơi ghi và danh sách producer cần chỉnh | Bản đồ producer → đường dẫn, phạm vi thay đổi cụ thể |
| 3 | Chỉnh producer cho các lượt mới, kiểm đường dẫn liên quan | Diff, log/JUnit và đối chiếu vị trí file phát sinh |
| 4 | Gộp cấu hình Explorer ở workspace | Diff settings, cách mở lại evidence và hoàn tác |
| 5 | Lập manifest ứng viên dọn; thực hiện từng mục đủ điều kiện | Manifest trước/sau, số file/dung lượng thực tế, kết quả kiểm |
| 6 | Kiểm kết quả và ghi báo cáo | Phần giữ lại, phần đã xử lý, mục còn chưa rõ và đường dẫn bằng chứng |

Lưu bộ hồ sơ thực hiện mới dưới `scratch/workspace-audit-<run_id>/`. Trong lúc Claude hoặc công cụ khác đang sửa source, tách phạm vi để tránh ghi đè; người giám sát tiếp tục chỉ đọc source và ghi bằng chứng của mình.

Tiêu chí nghiệm thu:

- Mọi venv được phân loại dựa trên dữ liệu kiểm kê, không chỉ tên thư mục.
- File mới của producer đã chỉnh đi đúng nơi; không tạo thêm thư mục tạm tùy ý ở gốc.
- Các tham chiếu CLI/setup/Docker/Kaggle/wheel chịu ảnh hưởng vẫn hợp lệ.
- Không thay nội dung PDF nguồn, model, output, baseline và evidence cần giữ.
- Thay đường dẫn chạy phải kiểm CWD khác, Unicode/khoảng trắng, child-process env và GPU lease dùng chung; chỉ chạy test liên quan.
- Cấu hình hiển thị có thể hoàn tác; kết quả ẩn và dung lượng dọn thực tế được báo cáo riêng.
- Phần chưa kiểm chứng ghi rõ; thiếu GT tiếp tục giữ `NOT_EVALUATED`.

## 7. Tài liệu liên quan

- [Thiết kế kiến trúc và P12/P13](PROMPTS_TAI_CAU_TRUC_MODULE_OCR_PDF.md).
- [Cấu hình, identity, dữ liệu và sao lưu](CAU_HINH_VA_DU_LIEU.md).
- [Trạng thái và consumer migration](MIGRATION_PLAN.md), [module_map.json](module_map.json).
- [Hướng dẫn phát triển module](HUONG_DAN_PHAT_TRIEN_MODULE.md).
- Báo cáo dọn [22/10/2026](../CLEANUP_REPORT_20261022.md) và [23/10/2026](../../CLEANUP_REPORT.md) (`reports/cleanup_audit_20261023/`): bằng chứng lịch sử, cần kiểm lại trạng thái trước khi xử lý thêm.

## 8. Kết quả thực hiện 23/10/2026

Phiên Claude `ocr-pdf-1d` thực hiện từ 01:16. Hồ sơ nằm tại `scratch/workspace-audit-20261023-011630-f0edf8e9/` và chỉ có trên máy này. Bộ hồ sơ gồm `REPORT.md`, cùng các file trong `evidence/`: `inventory.json`, `environments.json`, `interpreter_references.json`, `producer_map.md`, `cleanup_manifest.json`. Cùng lúc đó, phiên `ocr-pdf-9b` chạy lượt dọn `cleanup_audit_20261023`. Hai phiên đã tách phạm vi: phiên này không xóa file nào và chỉ sửa file được Git theo dõi sau lần `verify` cuối của lượt kia.

| Bước | Kết quả |
| --- | --- |
| 1. Kiểm kê | Kiểm kê được tạo lại sau review WS01/WS02. Bộ dò xét `pyvenv.cfg` ở mọi thư mục được liệt kê, kể cả gốc mỗi lượt walk; không theo reparse; thư mục không đọc được ghi `UNKNOWN`. Consumer được đọc theo cấu trúc JSON/YAML/TOML/INI, cộng với đường dẫn có ngoặc, không ngoặc và có khoảng trắng trong text, SQLite và zip; nguồn không đọc được ghi `UNKNOWN`. Kết quả: 7 venv thật, cùng 80 fixture/probe chỉ có `pyvenv.cfg`. `KEEP_ACTIVE`: `.venv`, `.venv-docling`, `.venv-v62/{text,docling}`; 27 job trong `.cache/v62-jobs` và 52 file trong `output/v63.zip` ghi cứng interpreter `.venv-v62`. `ARCHIVE_CANDIDATE`: `.venv-v62-clean/{text,docling}`; không có tham chiếu runtime trong phạm vi quét, ngoài phạm vi là `UNKNOWN`. `KEEP_COMPAT`: `scratch/migration/venv-reporting`. Không có process Python nào đang chạy. |
| 2–3. Producer | Thêm `scripts/run_pytest_scratch.py` cùng test. Fixture `test_v42_artifact_validator.py` gỡ các thư mục cha rỗng. Test CLW đặt `OCR_CACHE_DIR=tmp_path/cache`. Khóa `cache_dir` trong `pytest.ini` đã được thêm rồi gỡ, vì nó sinh `PytestConfigWarning` khi tắt cacheprovider. Các producer khác giữ nguyên, lý do ghi trong `producer_map.md`. |
| 4. Explorer | Tạo `.vscode/settings.json` (bị gitignore) đúng các khóa ở mục 4; User Settings của VS Code/Antigravity không đổi. Ở cấp gốc có 26,68 GiB / 235.338 file bị ẩn, dung lượng trên đĩa giữ nguyên. Hoàn tác bằng cách xóa file này. |
| 5. Dọn | Lượt này xóa 0 file. Các mục đủ điều kiện đã được lượt `cleanup_audit_20261023` xử lý: 228.094 file, 5,23 GiB. Các mục còn lại ở trạng thái `KEEP`, `UNKNOWN` hoặc `USER_DECISION`. |
| 6. Kiểm | Lượt đầu: 153 passed, 1 skipped (CLW thiếu PDF), chạy qua helper từ một CWD ngoài checkout, có tham số Unicode và khoảng trắng; gốc repo, `.cache/` và `output/` không có file mới. Sau review: test của bộ kiểm kê 29 passed; helper, v42 và kiểm kê 34 passed, 0 warning. Reviewer đã độc lập kiểm lại 13 test của helper/v42. |

Còn mở:
- `.venv-v62-clean` (9,48 GiB): người dùng quyết định có lưu trữ hay không. Nếu lưu trữ, giữ `installation.json` và mapping cho `benchmark/evidence/v62_clean_gpu_capability_20261015.json`. Consumer ngoài phạm vi quét (Thùng rác, CI runner, máy khác) vẫn là `UNKNOWN`.
- Có 156 nguồn chưa quét được: 102 xlsx lồng trong `output/v63.zip`, wheel bên thứ ba, fixture `.xlsx` hỏng, trọng số model lớn. Tất cả giữ `UNKNOWN`, danh sách ở `evidence/interpreter_references.json`.
- Docling client không xóa `.cache/docling-structure/<uuid>/page-*.pdf` sau mỗi request; hai lượt dọn đã gỡ tổng cộng 6,3 GiB loại file này. Cần một thay đổi riêng có test, giữ `worker.log`.
- Chưa rõ producer (`UNKNOWN`): `MA_TRAN_DEM_TU_KHOA_50_FILES.xlsx` ở gốc và `tmp/pdfs/keyword_count_report/`.
- Trước lượt này (00:42–00:53), 101 mục của `inputs/` cùng `output/{pdf,v63,word}` đã bị chuyển vào Thùng rác Windows; lượt này không khôi phục. Test CLW vẫn skip, nên bản sửa `OCR_CACHE_DIR` của nó chưa được chạy thật.
- Độ chính xác OCR: `NOT_EVALUATED`, vì chưa có GT.
