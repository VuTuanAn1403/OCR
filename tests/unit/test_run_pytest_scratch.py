"""scripts/run_pytest_scratch.py: per-run directories, child-only environment, exit code."""
import json
import os
import re

import pytest

from scripts import run_pytest_scratch as runner


def test_run_ids_are_unique_and_a_run_directory_is_never_reused(tmp_path):
    first, second = runner.new_run_id(), runner.new_run_id()
    assert first != second and re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{8}", first)
    run = runner.prepare_run(tmp_path, "r1")
    assert sorted(p.name for p in run.iterdir()) == ["evidence", "logs", "tmp"]
    with pytest.raises(FileExistsError):
        runner.prepare_run(tmp_path, "r1")


def test_child_environment_is_scoped_to_the_run(tmp_path):
    before = dict(os.environ)
    env = runner.child_env(tmp_path)
    assert os.environ == before
    assert {env[k] for k in ("TMP", "TEMP", "TMPDIR")} == {str(tmp_path / "tmp")}
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    # The GPU lease directory is machine-wide and must reach the child unchanged.
    assert runner.child_env(tmp_path, {"OCR_GPU_LEASE_DIR": "shared"})["OCR_GPU_LEASE_DIR"] == "shared"
    command = runner.pytest_command("python", tmp_path, ["tests/x.py", "-q"])
    assert command[:5] == ["python", "-B", "-m", "pytest", "tests/x.py"]
    assert {"-p", "no:cacheprovider", f"--basetemp={tmp_path / 'pytest'}",
            f"--junitxml={tmp_path / 'evidence' / 'junit.xml'}"} <= set(command)


@pytest.mark.parametrize("body, expected", [("assert True", 0), ("assert False", 1)])
def test_exit_code_and_evidence_of_a_real_run(tmp_path, body, expected):
    cases = tmp_path / "thư mục có dấu cách"
    cases.mkdir()
    # tmp_path makes pytest create --basetemp, which must land inside the run.
    (cases / "test_case.py").write_text(f"def test_case(tmp_path):\n    (tmp_path / 'x').touch()\n    {body}\n",
                                        encoding="utf-8")
    runs = tmp_path / "lượt chạy"
    assert runner.main(["--runs-root", str(runs), "--run-id", "r1", str(cases / "test_case.py"), "-q"]) == expected
    run = runs / "r1"
    record = json.loads((run / "run.json").read_text(encoding="utf-8"))
    assert (record["status"], record["exit_code"]) == ("FINISHED", expected)
    assert (run / "evidence" / "junit.xml").is_file() and list((run / "pytest").rglob("x"))
    assert ("1 passed" if expected == 0 else "1 failed") in (run / "logs" / "pytest.log").read_text(encoding="utf-8")
    assert not [p for pattern in (".pytest_cache", "pytest-cache-files-*", "__pycache__") for p in tmp_path.rglob(pattern)]
