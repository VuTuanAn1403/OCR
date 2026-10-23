"""ocr_artifacts: hashes, named digests and atomic writes."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys

import pytest

from ocr_artifacts import atomic_io
from ocr_artifacts.digest import sha256_json_ascii, sha256_json_compact, sha256_json_unicode
from ocr_artifacts.hashing import sha256_file

ROOT = Path(__file__).resolve().parents[3]
# Same fixture and frozen values as tests/unit/test_migration_digest_baseline.py.
FIXTURE = {"tên": "Báo cáo thường niên", "z": [3, 1.5, None, True], "a": {"b": "Ủy ban", "a": 2}}


def test_named_digests_keep_baseline_values():
    assert sha256_json_compact(FIXTURE) == "5c347d8d6ef1489f73abf139dbbc47c76183ebbe474f72197e0c828134704758"
    assert sha256_json_ascii(FIXTURE) == "9dd4a95bc0c096b973d693d7fc68a5d3de6a91f566737b238547e6af738159e5"
    assert sha256_json_unicode(FIXTURE) == "bd051aaf9f1bdd7f370f1db3f8b83b81cf948c7afa89520e66e70bb39b45254a"
    with_path = {**FIXTURE, "path": PurePosixPath("models/vietocr/vgg_seq2seq.pth")}
    assert sha256_json_unicode(with_path, default=str)[:16] == "d4f8d7afae8b0a3b"


def test_digest_variants_are_distinct():
    assert len({sha256_json_compact(FIXTURE), sha256_json_ascii(FIXTURE), sha256_json_unicode(FIXTURE)}) == 3


def test_file_hash_streams_large_files(tmp_path):
    path = tmp_path / "big.bin"
    data = os.urandom((1 << 20) * 2 + 17)
    path.write_bytes(data)
    assert sha256_file(path) == hashlib.sha256(data).hexdigest()


def test_atomic_write_keeps_old_file_on_failure(tmp_path, monkeypatch):
    target = tmp_path / "a.json"
    atomic_io.atomic_write_json(target, {"v": "cũ"})
    monkeypatch.setattr(atomic_io.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError):
        atomic_io.atomic_write_json(target, {"v": "mới"})
    assert json.loads(target.read_text(encoding="utf-8")) == {"v": "cũ"}
    assert [p.name for p in tmp_path.iterdir()] == ["a.json"]


def test_import_uses_standard_library_only():
    code = ("import json, sys\nimport ocr_artifacts.atomic_io, ocr_artifacts.digest, ocr_artifacts.hashing\n"
            "print(json.dumps(sorted(m for m in sys.modules if m.split('.')[0] in "
            "{'pydantic','numpy','pymupdf','yaml','psutil','openpyxl','torch'})))")
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT / "src", capture_output=True, text=True,
                            env={**os.environ, "PYTHONPATH": str(ROOT / "src")}, timeout=60)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == []
