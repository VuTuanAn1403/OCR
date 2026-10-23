"""Configuration sources, CLI routing and path precedence (P12).

docs/architecture/CAU_HINH_VA_DU_LIEU.md is the table these tests pin."""
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from ocr_runtime import config, paths

ROOT = Path(__file__).resolve().parents[3]
UNICODE_DIR = "thư mục có dấu cách"


@pytest.mark.parametrize("name,pipeline", [("profiles.yaml", "legacy"), ("profiles-v62.yaml", "v6.2"),
                                           ("profiles-v63.yaml", "v6.3")])
def test_each_profile_file_declares_its_pipeline(name, pipeline):
    assert config.read_declaration(ROOT / "config" / name) == {"config_schema": config.CONFIG_SCHEMA,
                                                               "pipeline": pipeline}
    config.load_profiles(ROOT / "config" / name)


def profile_file(directory, name, pipeline=None):
    source = (ROOT / "config/profiles-v63.yaml").read_text(encoding="utf-8")
    body = source[source.index("profiles:"):]
    head = f"config_schema: ocr-profiles-v1\npipeline: {pipeline}\n" if pipeline else ""
    path = Path(directory) / name
    path.write_text(head + body, encoding="utf-8")
    return str(path)


def test_cli_routes_on_the_declared_pipeline_before_the_file_name(tmp_path):
    from src.ocr.cli.unified import use_v63
    assert use_v63([]) is True
    assert use_v63(["--backend", "legacy"]) is False
    assert use_v63(["--profile", "fast"]) is False
    assert use_v63(["--config", str(ROOT / "config/profiles-v63.yaml")]) is True
    assert use_v63(["--config", str(ROOT / "config/profiles.yaml")]) is False
    # The declaration decides, whatever the file is called.
    assert use_v63(["--config", profile_file(tmp_path, "gpu.yaml", "v6.3")]) is True
    assert use_v63(["--config=" + profile_file(tmp_path, "profiles-v63-copy.yaml", "legacy")]) is False
    # Files without a declaration keep the historical file-name rule.
    assert use_v63(["--config", profile_file(tmp_path, "profiles-v63-old.yaml")]) is True
    assert use_v63(["--config", profile_file(tmp_path, "other.yaml")]) is False
    # --backend still wins.
    assert use_v63(["--backend", "gpu_two_phase", "--config", str(ROOT / "config/profiles.yaml")]) is True


@pytest.mark.parametrize("head,message", [("pipeline: v7\n", "pipeline must be one of"),
                                          ("config_schema: other-v9\n", "config_schema")])
def test_an_unknown_declaration_is_an_error(tmp_path, head, message):
    path = tmp_path / "profiles.yaml"
    path.write_text(head + "profiles:\n  p: {}\n", encoding="utf-8")
    with pytest.raises(config.ConfigError, match=message):
        config.load_profiles(path)
    with pytest.raises(config.ConfigError, match=message):
        config.read_declaration(path)


def test_v63_backend_refuses_a_file_declared_for_another_pipeline(tmp_path):
    from ocr_pipeline.backend import prepare_backend
    path = profile_file(tmp_path, "profiles-v63.yaml", "legacy")
    with pytest.raises(ValueError, match="declares pipeline 'legacy'"):
        prepare_backend(path, "unified_gpu_full_ocr", tmp_path / "envs", preflight=False)


def test_legacy_config_precedence(tmp_path, monkeypatch):
    explicit = tmp_path / "explicit.yaml"
    configured = tmp_path / "configured.yaml"
    for path in (explicit, configured):
        path.write_text("profiles:\n  p: {}\n", encoding="utf-8")
    monkeypatch.setenv("OCR_CONFIG_PATH", str(configured))
    assert config.resolve_config_path(explicit) == explicit.resolve()
    assert config.resolve_config_path() == configured.resolve()
    monkeypatch.delenv("OCR_CONFIG_PATH")
    assert config.resolve_config_path() == config.DEFAULT_CONFIG_PATH.resolve()


def test_v63_cli_takes_its_own_config_and_ignores_ocr_config_path(tmp_path, monkeypatch):
    import ocr_pipeline.backend as backend
    from ocr_pipeline.cli import main_v63
    monkeypatch.setenv("OCR_CONFIG_PATH", str(ROOT / "config/profiles.yaml"))
    seen = []

    def stop(config_path, profile, env_root, **kwargs):
        seen.append(Path(config_path))
        raise SystemExit(0)

    monkeypatch.setattr(backend, "prepare_backend", stop)
    with pytest.raises(SystemExit):
        main_v63(argv=["--input", str(tmp_path), "--output", str(tmp_path / "out")])
    assert seen == [paths.PROJECT_ROOT / "config/profiles-v63.yaml"]


def test_storage_variables_and_defaults(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for name in ("OCR_DATA_DIR", "OCR_OUTPUT_DIR", "OCR_CACHE_DIR", "OCR_MODELS_DIR"):
        monkeypatch.delenv(name, raising=False)
    assert (paths.data_dir(), paths.output_dir(), paths.cache_dir()) == (Path("inputs"), Path("output"), Path(".cache"))
    assert paths.models_dir() == paths.PROJECT_ROOT / "models"
    assert paths.v63_cache_root() == paths.PROJECT_ROOT / ".cache"
    monkeypatch.setenv("OCR_DATA_DIR", f"{UNICODE_DIR}/pdf")
    monkeypatch.setenv("OCR_CACHE_DIR", f"{UNICODE_DIR}/cache")
    assert paths.data_dir() == Path(f"{UNICODE_DIR}/pdf")
    assert paths.v63_cache_root() == (tmp_path / UNICODE_DIR / "cache").resolve()


def test_children_receive_absolute_path_variables(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for name in paths.PATH_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OCR_MODELS_DIR", f"{UNICODE_DIR}/models")
    monkeypatch.setenv("OCR_GPU_LEASE_DIR", str(tmp_path / "leases"))
    assert paths.absolute_path_env() == {"OCR_MODELS_DIR": str((tmp_path / UNICODE_DIR / "models").resolve()),
                                         "OCR_GPU_LEASE_DIR": str((tmp_path / "leases").resolve())}


def test_scheduler_uses_the_cache_root_and_hands_workers_absolute_paths(tmp_path, monkeypatch):
    from ocr_pipeline import scheduler
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OCR_CACHE_DIR", f"{UNICODE_DIR}/cache")
    monkeypatch.setenv("OCR_MODELS_DIR", "models here")
    monkeypatch.setenv("OCR_GPU_LEASE_DIR", str(tmp_path / "leases"))
    monkeypatch.setattr(scheduler, "sys", SimpleNamespace(modules={}))
    seen = {}

    def capture(command, **kwargs):
        seen.update(kwargs["env"])
        raise RuntimeError("captured")

    monkeypatch.setattr(scheduler, "supervised_run", capture)
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF fixture")
    request = {"pdf": str(pdf), "config": {"ocr_source_policy": "gpu_ocr_only_v1"}, "device": "cpu",
               "allow_cpu_benchmark": True, "text_python": sys.executable, "docling_python": sys.executable,
               "model_hashes": {}, "lock_hashes": {}, "output": str(tmp_path / "out")}
    with pytest.raises(RuntimeError, match="captured"):
        scheduler.run_document(request)
    cache = (tmp_path / UNICODE_DIR / "cache").resolve()
    assert list((cache / "v62-jobs").glob("*/request.json"))
    assert list((cache / "v63-stages" / "text").glob("*.tmp-*"))
    assert seen["OCR_CACHE_DIR"] == str(cache)
    assert seen["OCR_MODELS_DIR"] == str((tmp_path / "models here").resolve())


def test_diagnosis_is_read_only_and_light(tmp_path):
    code = ("import json, sys\nfrom ocr_runtime import diagnose\nreport = diagnose.collect()\n"
            "heavy = [m for m in ('torch', 'numpy', 'cv2', 'pymupdf', 'fitz', 'onnxruntime') if m in sys.modules]\n"
            "print(json.dumps({'report': report, 'heavy': heavy}, ensure_ascii=False))")
    env = {**{k: v for k, v in os.environ.items() if not k.startswith("OCR_")},
           "PYTHONPATH": os.pathsep.join([str(ROOT), str(ROOT / "src")]), "PYTHONIOENCODING": "utf-8",
           "OCR_CACHE_DIR": str(tmp_path / UNICODE_DIR)}
    before = sorted(tmp_path.rglob("*"))
    result = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env, capture_output=True, text=True,
                            encoding="utf-8", timeout=120)
    assert result.returncode == 0, result.stderr[-2000:]
    data = json.loads(result.stdout.strip().splitlines()[-1])
    assert data["heavy"] == []
    assert sorted(tmp_path.rglob("*")) == before
    report = data["report"]
    assert report["layout"]["is_checkout"] is True and report["layout"]["source_tree"] is True
    rows = {row["name"]: row for row in report["paths"]}
    cache = rows["V6.3 job and stage cache"]
    assert Path(cache["path"]) == (tmp_path / UNICODE_DIR).resolve()
    assert cache["source"] == "OCR_CACHE_DIR" and cache["exists"] is False
    declared = {Path(row["file"]).name: row["declaration"].get("pipeline") for row in report["profile_files"]}
    assert declared["profiles-v63.yaml"] == "v6.3" and declared["profiles.yaml"] == "legacy"
    cli = subprocess.run([sys.executable, "-m", "ocr_runtime.diagnose"], cwd=tmp_path, env=env, capture_output=True,
                         text=True, encoding="utf-8", timeout=120)
    assert cli.returncode == 0 and "[layout]" in cli.stdout
