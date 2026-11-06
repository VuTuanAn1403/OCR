"""Exercise the shipped notebook on local source archives and frozen JSON outputs."""
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from test_kaggle_v63_notebook import namespace, functions_only, ROOT


def source_archive(tmp_path, *, unsafe=None, wrong_hash=False):
    files = {"pyproject.toml": b"project", "config/profiles.yaml": b"profile", "config/alias_rules.json": b"{}",
             "src/ocr_runtime/paths.py": b"pass\n"}
    if unsafe: files[unsafe] = b"unsafe"
    manifest = {"schema_version": "kaggle-source-v1", "git_head": "a"*40,
                "files": {n: hashlib.sha256(v).hexdigest() for n, v in files.items()}}
    if wrong_hash: manifest["files"]["pyproject.toml"] = "0"*64
    path = tmp_path / "source.zip"
    with ZipFile(path, "x") as archive:
        for name, value in files.items(): archive.writestr(name, value)
        archive.writestr("kaggle-source-manifest.json", json.dumps(manifest))
    return path


def test_source_archive_is_verified_before_extraction_and_reused_read_only(tmp_path):
    scope, _ = namespace()
    source = source_archive(tmp_path)
    checksum = scope["sha256_file"](source)
    target, manifest, actual = scope["prepare_source_archive"](source, tmp_path / "runtime", checksum)
    assert actual == checksum
    before = {p: p.read_bytes() for p in target.rglob("*") if p.is_file()}
    assert scope["prepare_source_archive"](source, tmp_path / "runtime", checksum)[0] == target
    assert before == {p: p.read_bytes() for p in before}
    (target / "pyproject.toml").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="snapshot changed"):
        scope["prepare_source_archive"](source, tmp_path / "runtime", checksum)


@pytest.mark.parametrize("unsafe", ["../escape.py", "/absolute.py", "C:/escape.py", "src/../../escape.py", "src\\escape.py"])
def test_source_archive_paths_cannot_escape_runtime(tmp_path, unsafe):
    scope, _ = namespace()
    source = source_archive(tmp_path, unsafe=unsafe)
    with pytest.raises(ValueError, match="Unsafe|members differ"):
        scope["prepare_source_archive"](source, tmp_path / "runtime")
    assert not (tmp_path / "runtime").exists()


def test_source_archive_checksum_failures_write_nothing(tmp_path):
    scope, _ = namespace()
    source = source_archive(tmp_path, wrong_hash=True)
    with pytest.raises(ValueError, match="checksum mismatch"):
        scope["prepare_source_archive"](source, tmp_path / "runtime")
    with pytest.raises(ValueError, match="SHA-256"):
        scope["prepare_source_archive"](source, tmp_path / "runtime", "f"*64)
    assert not (tmp_path / "runtime").exists()


def test_previous_results_restore_complete_directory_without_merge(tmp_path):
    scope, _ = namespace()
    source, target = tmp_path / "previous", tmp_path / "current"
    (source / "documents").mkdir(parents=True)
    for name in ("selected_inputs.json", "run_settings.json", "documents/batch_state.sqlite", "documents/batch_config.json"):
        (source / name).write_text('{"commit":"old"}', encoding="utf-8")
    restored = scope["restore_previous_results"](source, target)
    assert restored == {"commit": "old"}
    assert (target / "documents/batch_state.sqlite").read_bytes() == (source / "documents/batch_state.sqlite").read_bytes()
    with pytest.raises(ValueError, match="already exists"):
        scope["restore_previous_results"](source, target)


def test_notebook_batch_command_carries_explicit_frozen_rules(tmp_path):
    scope, cells = namespace()
    functions_only(cells["batch"], scope)
    scope.update(SUPERVISOR_PYTHON=Path("python"), REPO_DIR=ROOT, STAGED_INPUT=tmp_path / "inputs", BATCH_DIR=tmp_path / "batch",
                 GPU_ENV_ROOT=tmp_path / "gpu", KEYWORDS_PATH=ROOT / "config/keywords.txt", RULES_PATH=tmp_path / "frozen.json")
    command = scope["build_batch_command"]()
    assert command[command.index("--alias-rules")+1] == str(tmp_path / "frozen.json")
    scope["GLOBAL_ALIASES"] = False
    command = scope["build_batch_command"]()
    assert "--no-alias-rules" in command and "--alias-rules" not in command


@pytest.mark.parametrize("commit", ["--upload-pack=unexpected", "main", None, "a"*39])
def test_restored_commit_must_be_an_exact_git_sha(commit):
    scope, _ = namespace()
    with pytest.raises(ValueError, match="commit"):
        scope["validated_previous_commit"]({"commit": commit})
    assert scope["validated_previous_commit"]({"commit": "a"*40}) == "a"*40
