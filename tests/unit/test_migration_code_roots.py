"""Source fingerprint and worker PYTHONPATH share one list of code roots (P02)."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

from src.ocr.runtime import fingerprint
from src.ocr.runtime.paths import PROJECT_ROOT, code_roots, worker_pythonpath


def test_fingerprint_covers_every_package_module_and_runtime_script():
    hashed = {path.resolve() for path in fingerprint.source_files()}
    for path in (PROJECT_ROOT / "src").rglob("*.py"):
        assert path.resolve() in hashed, path
    for script in fingerprint.RUNTIME_SCRIPTS:
        assert (PROJECT_ROOT / script).resolve() in hashed


def test_editing_a_new_package_changes_the_fingerprint(tmp_path, monkeypatch):
    module = tmp_path / "src" / "ocr_example" / "m.py"
    module.parent.mkdir(parents=True)
    module.write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.setattr(fingerprint, "LEGACY_ROOT", tmp_path)
    before = fingerprint.source_fingerprint()
    module.write_text("VALUE = 2\n", encoding="utf-8")
    assert fingerprint.source_fingerprint() != before


def run_worker_probe(cwd, pythonpath):
    code = ("import ocr_contracts.page, ocr_artifacts.digest, src.ocr.runtime.fingerprint as f\n"
            "f.assert_loaded_code_fingerprinted()\nprint('OK')")
    env = {**os.environ, "PYTHONPATH": pythonpath}
    return subprocess.run([sys.executable, "-c", code], cwd=cwd, env=env, capture_output=True,
                          text=True, timeout=120)


def test_worker_pythonpath_works_from_another_directory(tmp_path):
    assert code_roots() == [PROJECT_ROOT, PROJECT_ROOT / "src"]
    result = run_worker_probe(tmp_path, worker_pythonpath())
    assert result.returncode == 0 and "OK" in result.stdout, result.stderr


def test_shadowing_copy_outside_code_roots_is_refused(tmp_path):
    shadow = tmp_path / "shadow" / "ocr_contracts"
    shadow.mkdir(parents=True)
    (shadow / "__init__.py").write_text("", encoding="utf-8")
    (shadow / "page.py").write_text("", encoding="utf-8")
    result = run_worker_probe(tmp_path, os.pathsep.join([str(tmp_path / "shadow"), worker_pythonpath()]))
    assert result.returncode != 0 and "UNFINGERPRINTED_CODE" in result.stderr
