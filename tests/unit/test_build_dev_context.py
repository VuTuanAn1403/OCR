"""Evidence snapshots must not imply a clean tree or overwrite source data."""
import json
import subprocess

import pytest

from scripts import build_dev_context as context


def init_repo(root):
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for name in context.DOC_BUDGETS:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("guidance\n", encoding="utf-8")
    context.git(root, "add", ".")
    context.git(root, "-c", "user.name=Snapshot Test", "-c", "user.email=test@example.invalid",
                "-c", "commit.gpgsign=false", "commit", "-qm", "fixture")
    return root


def test_dirty_bytes_change_identity_without_changing_head(tmp_path):
    root = init_repo(tmp_path / "repo with spaces")
    name = "số liệu có khoảng trắng.py"
    (root / name).write_text("before", encoding="utf-8")
    first = context.build_context(root, [name])
    (root / name).write_text("after", encoding="utf-8")
    second = context.build_context(root, [name])
    assert first["git"]["head"] == second["git"]["head"]
    assert first["git"]["dirty"] and second["git"]["dirty"]
    assert first["focus_files"][0]["sha256"] != second["focus_files"][0]["sha256"]
    assert second["focus_files"][0]["path"] == name
    assert second["documentation"]["token_usage"] == "NOT_MEASURED"
    assert second["verification"].startswith("NOT_EVALUATED")


def test_clean_tree_and_truncation_are_explicit(tmp_path):
    root = init_repo(tmp_path / "repo")
    clean = context.build_context(root, [])
    assert not clean["git"]["dirty"]
    for name in ("one.py", "two.py", "three.py"):
        (root / name).write_text("x", encoding="utf-8")
    limited = context.build_context(root, [], max_changes=1)["git"]
    assert limited["dirty"] and len(limited["changes"]) == 1
    assert limited["change_records_total"] == 3 and limited["change_records_omitted"] == 2


def test_rename_paths_survive_git_and_spaces(tmp_path):
    root = init_repo(tmp_path / "repo")
    context.git(root, "mv", "AGENTS.md", "renamed instructions.md")
    changes = context.build_context(root, ["renamed instructions.md"])["git"]["changes"]
    assert changes == [{"status": "R ", "path": "renamed instructions.md", "source_path": "AGENTS.md"}]
    with pytest.raises(ValueError, match="Incomplete"):
        context.parse_status("R  renamed.md\0")


@pytest.mark.parametrize("name", ["../outside.txt", ".git/config", "docs", "missing.py"])
def test_focus_rejects_escape_metadata_directories_and_missing_files(tmp_path, name):
    root = init_repo(tmp_path / "repo")
    (tmp_path / "outside.txt").write_text("outside", encoding="utf-8")
    with pytest.raises(ValueError):
        context.build_context(root, [name])


def test_focus_limits_do_not_hash_large_data(tmp_path):
    root = init_repo(tmp_path / "repo")
    large = root / "large.bin"
    large.write_bytes(b"x" * (context.MAX_FILE_BYTES + 1))
    with pytest.raises(ValueError, match="manifest"):
        context.build_context(root, ["large.bin"])
    with pytest.raises(ValueError, match="at most"):
        context.build_context(root, ["AGENTS.md"] * (context.MAX_FOCUS_FILES + 1))
    with pytest.raises(ValueError, match="max-changes"):
        context.build_context(root, [], max_changes=0)


def test_output_is_new_scratch_file_and_source_is_preserved(tmp_path):
    root = init_repo(tmp_path / "repo")
    payload = json.dumps(context.build_context(root, []))
    target = context.write_snapshot(root, "scratch/session/start.json", payload)
    assert json.loads(target.read_text(encoding="utf-8"))["schema_version"] == "development-context-v1"
    with pytest.raises(FileExistsError):
        context.write_snapshot(root, "scratch/session/start.json", "overwrite")
    for unsafe in ("AGENTS.md", "scratch/../README.md", "../outside.json", "scratch"):
        with pytest.raises(ValueError, match="scratch"):
            context.write_snapshot(root, unsafe, "overwrite")
    assert (root / "AGENTS.md").read_text(encoding="utf-8") == "guidance\n"
    assert target.read_text(encoding="utf-8") == payload


def test_missing_or_oversized_docs_fail_budget_and_cli_reports_errors(tmp_path, monkeypatch, capsys):
    root = init_repo(tmp_path / "repo")
    monkeypatch.setattr(context, "ROOT", root)
    assert context.main([]) == 0
    initial = json.loads(capsys.readouterr().out)
    assert initial["documentation"]["budget_pass"]
    # UTF-8 bytes differ from character counts; do not estimate actual tokens.
    (root / "AGENTS.md").write_text("ệ" * 3000, encoding="utf-8")
    assert context.main([]) == 1
    oversized = json.loads(capsys.readouterr().out)
    record = oversized["documentation"]["files"][0]
    assert record["bytes"] == 9000 and not record["within_budget"]
    (root / "CLAUDE.md").unlink()
    missing = context.build_context(root, [])["documentation"]
    assert not missing["budget_pass"] and missing["suggested_startup_bytes"] is None
    assert context.main(["--focus", "missing.py"]) == 2
    assert "Cannot build" in capsys.readouterr().err


def test_git_failure_is_an_error_not_a_clean_snapshot(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(context, "ROOT", tmp_path)
    assert context.main([]) == 2
    captured = capsys.readouterr()
    assert not captured.out and "Cannot build" in captured.err
