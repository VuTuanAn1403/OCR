"""The baseline lock must reuse the production identity and never hide a refusal."""
import json
import subprocess

import pytest

from ocr_contracts.processing import IdentityMismatch
from ocr_pipeline import backend as production
from ocr_pipeline import batch
from scripts import build_dev_context as context
from scripts import lock_baseline as lb


def git_repo(root):
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for rel, text in {"src/pkg/mod.py": "X = 1\n", "docs/note.md": "# a\n", "config/profiles.yaml": "pipeline: v7.0\n",
                      "requirements/v62/windows-text-gpu.lock": "a==1\n"}.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    context.git(root, "add", ".")
    context.git(root, "-c", "user.name=Lock Test", "-c", "user.email=test@example.invalid",
                "-c", "commit.gpgsign=false", "commit", "-qm", "fixture")
    return root


def fake_backend(root):
    return {"config": {"pipeline": "v7.0", "primary_engine": "vietocr"},
            "config_path": str(root / "config/profiles.yaml"),
            "model_hashes": {str(root / "models/a.onnx"): "a" * 64},
            "lock_hashes": {str(root / "requirements/v62/windows-text-gpu.lock"): "b" * 64,
                            str(root / "requirements/v62/windows-docling-gpu.lock"): "c" * 64},
            "model_registry_path": str(root / "models/v62/runtime-models.json"),
            "text_python": str(root / ".venv-v62/text/python"), "docling_python": str(root / ".venv-v62/docling/python"),
            "source_fingerprint": "e" * 16, "code_fingerprints": {"extraction": "e" * 16, "analysis": "a" * 16,
                                                                  "publication": "p" * 16}}


RECORDS = [{"id": "AAA", "name": "AAA.pdf", "path": "inputs/AAA.pdf", "size": 10, "pdf_sha256": "d" * 64,
            "total_pages": 3, "source_error": None, "duplicate_of": None}]


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = git_repo(tmp_path / "repo")
    calls = {}

    def prepare(config_path, profile, env_root, *, preflight=True):
        calls.update(profile=profile, env_root=env_root, preflight=preflight)
        return fake_backend(root)

    monkeypatch.setattr(production, "prepare_backend", prepare)
    monkeypatch.setattr(batch, "input_snapshot", lambda path: [dict(r) for r in RECORDS])
    monkeypatch.setattr(lb, "verify_lock", lambda python, path: {"status": "VERIFIED", "packages": 2})
    monkeypatch.setattr(lb, "probe_runtimes", lambda backend: {"text": {"status": "CAPABILITY_ONLY"},
                                                               "docling": {"status": "CAPABILITY_ONLY"}})
    monkeypatch.setattr(lb, "gpu_state", lambda: {"status": "OBSERVED", "gpus": [{"name": "Test GPU"}]})
    return root, calls


def test_lock_reuses_production_identity(env):
    root, calls = env
    lock = lb.build_lock(root, root / "inputs", root / "output")
    assert lock["status"] == "LOCKED" and lock["problems"] == []
    assert calls == {"profile": "unified_gpu_full_ocr", "env_root": root / ".venv-v62", "preflight": True}
    request = {**fake_backend(root), "pdf_sha256": "d" * 64, **lb.REQUEST_DEFAULTS}
    assert lock["inputs"][0]["ocr_identity"] == production.ocr_identity(request)
    assert lock["models"]["sha256"] == {"models/a.onnx": "a" * 64}
    assert lock["quality"] == "NOT_EVALUATED" and lock["inference"] == "NOT_RUN"
    moved = lb.build_lock(root, root / "inputs", root / "output")
    assert moved["portable_identity"] == lock["portable_identity"]


def test_production_refusal_is_recorded_not_hidden(env, monkeypatch, capsys):
    root, _ = env

    def refuse(*args, **kwargs):
        raise IdentityMismatch("MODEL_LOCK_MISMATCH: models/a.onnx")

    monkeypatch.setattr(production, "prepare_backend", refuse)
    monkeypatch.setattr(lb, "ROOT", root)
    assert lb.main([]) == 1
    written = sorted((root / "scratch/benchmarks").glob("BASELINE-V8-*/baseline_lock.json"))
    lock = json.loads(written[0].read_text(encoding="utf-8"))
    assert lock["status"] == "FAILED" and "MODEL_LOCK_MISMATCH" in lock["error"]
    assert "MODEL_LOCK_MISMATCH" in capsys.readouterr().out


@pytest.mark.parametrize("patch, problem", [
    (lambda m: m.setattr(lb, "verify_lock", lambda p, l: {"status": "FAILED", "error": "drift"}), "not verified"),
    (lambda m: m.setattr(lb, "probe_runtimes", lambda b: {"text": {"status": "FAILED"}}), "Runtime probe failed"),
    (lambda m: m.setattr(batch, "input_snapshot", lambda p: [dict(RECORDS[0], source_error="encrypted")]),
     "Input not usable"),
])
def test_any_missing_evidence_keeps_the_lock_incomplete(env, monkeypatch, patch, problem):
    root, _ = env
    patch(monkeypatch)
    lock = lb.build_lock(root, root / "inputs", root / "output")
    assert lock["status"] == "INCOMPLETE" and any(problem in item for item in lock["problems"])


def test_cpu_only_run_cannot_lock(env):
    root, calls = env
    lock = lb.build_lock(root, root / "inputs", root / "output", gpu_preflight=False)
    assert calls["preflight"] is False
    assert lock["status"] == "INCOMPLETE" and lock["runtime_probes"].startswith("NOT_EVALUATED")


def test_existing_receipts_with_the_same_identity_are_listed(env):
    root, _ = env
    identity = lb.build_lock(root, root / "inputs", root / "output")["inputs"][0]["ocr_identity"]
    receipt = root / "output/run1/AAA/ocr_receipt.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(json.dumps({"ocr_identity": identity}), encoding="utf-8")
    (root / "output/run1/OTHER").mkdir()
    (root / "output/run1/OTHER/ocr_receipt.json").write_text('{"ocr_identity": "x"}', encoding="utf-8")
    matches = lb.build_lock(root, root / "inputs", root / "output")["existing_outputs"]["matches"]
    assert matches == [{"document": "AAA", "receipt": "output/run1/AAA/ocr_receipt.json"}]


def test_git_state_separates_code_changes_from_docs(tmp_path):
    root = git_repo(tmp_path / "repo")
    (root / "docs/note.md").write_text("# b\n", encoding="utf-8")
    state = lb.git_state(root)
    assert state["dirty"] and state["code_scope_changes"] == []
    (root / "src/pkg/mod.py").write_text("X = 2\n", encoding="utf-8")
    changed = lb.git_state(root)
    assert any("src/pkg/mod.py" in line for line in changed["code_scope_changes"])
    assert changed["code_scope_diff_sha256"] != state["code_scope_diff_sha256"]


def test_lock_ids_increment_and_files_are_never_overwritten(tmp_path):
    first = lb.next_lock_id(tmp_path, "20261108")
    (tmp_path / "scratch/benchmarks" / first).mkdir(parents=True)
    assert first.endswith("-001") and lb.next_lock_id(tmp_path, "20261108").endswith("-002")
    context.write_snapshot(tmp_path, f"scratch/benchmarks/{first}/baseline_lock.json", "{}")
    with pytest.raises(FileExistsError):
        context.write_snapshot(tmp_path, f"scratch/benchmarks/{first}/baseline_lock.json", "{}")
