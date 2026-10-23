"""The pinned model identity is the files the phases load (F06).

Registry, model store and interpreters are doubles; no engine, preflight or
model runs. Models live outside the checkout through OCR_MODELS_DIR and an
external VIETOCR_MODEL_DIR."""
import ast
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
import yaml

from ocr_contracts.processing import IdentityMismatch
from ocr_pipeline import backend, scheduler
from ocr_runtime import fingerprint, paths

ROOT = Path(__file__).resolve().parents[2]
SUFFIX = "Scripts/python.exe" if os.name == "nt" else "bin/python"
REPOS = {"layout": "docling-project/docling-layout-heron", "table": "docling-project/docling-models",
         "formula": "docling-project/CodeFormulaV2"}
HUBS = {role: "models/docling/huggingface/hub/models--" + repo.replace("/", "--")
        for role, repo in REPOS.items()}
REFS = {role: f"{hub}/refs/" + ("v2.3.0" if role == "table" else "main") for role, hub in HUBS.items()}
LAYOUT = f"{HUBS['layout']}/snapshots/r"
TABLE = f"{HUBS['table']}/snapshots/r/model.bin"
FORMULA = f"{HUBS['formula']}/snapshots/r/model.bin"


@pytest.fixture
def project(tmp_path, monkeypatch):
    for name in ("OCR_MODELS_DIR", "VIETOCR_MODEL_DIR", "HF_HOME", "OCR_BRIDGE_FONT"):
        monkeypatch.delenv(name, raising=False)
    store, vietocr = tmp_path / "model store", tmp_path / "external vietocr"
    monkeypatch.setenv("OCR_MODELS_DIR", str(store))
    monkeypatch.setenv("VIETOCR_MODEL_DIR", str(vietocr))
    files = {f"models/vietocr/{name}": vietocr / name for name in paths.VIETOCR_FILES}
    files.update({"models/v62/det.onnx": store / "v62/det.onnx", f"{LAYOUT}/model.safetensors":
                  store / LAYOUT.removeprefix("models/") / "model.safetensors",
                  TABLE: store / TABLE.removeprefix("models/"),
                  FORMULA: store / FORMULA.removeprefix("models/")})
    files.update({name: store / name.removeprefix("models/") for name in REFS.values()})
    for name, path in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("r" if name in REFS.values() else name, encoding="utf-8")
    registry = tmp_path / "registry.json"

    def write_registry(skip=()):
        registry.write_text(json.dumps({
            "schema_version": "v62-runtime-models-v1",
            "snapshots": {role: {"repo": REPOS[role], "revision": "r"}
                          for role in ("layout", "table", "formula")},
            "text_detector": {"adapter": "onnx-db-map-v1", "model_path": "models/v62/det.onnx"},
            "layout_model": {"adapter": "hf_rtdetr_torch", "model_path": LAYOUT},
            "files": {name: scheduler.sha256(path) for name, path in files.items() if name not in skip}}),
            encoding="utf-8")

    write_registry()
    data = yaml.safe_load((ROOT / "config/profiles.yaml").read_text(encoding="utf-8"))
    data["profiles"]["unified_gpu_full_ocr"]["model_registry"] = str(registry)
    config = tmp_path / "profiles-v63.yaml"
    config.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    envs = tmp_path / "envs"
    for role in ("text", "docling"):
        (envs / role / SUFFIX).parent.mkdir(parents=True)
        (envs / role / SUFFIX).write_text("", encoding="utf-8")
    return SimpleNamespace(files=files, registry=registry, write_registry=write_registry, config=config, envs=envs,
                           prepare=lambda: backend.prepare_backend(config, "unified_gpu_full_ocr", envs, preflight=False))


def text_key(prepared):
    identity = {"pdf": "p" * 64, "pages": None, "python": prepared["text_python"]}
    return scheduler.stage_key("text", {**prepared, "device": "cuda"}, identity, None, "code", "coordinator")


def test_pinned_paths_are_the_files_the_phases_load(project):
    prepared = project.prepare()
    pinned = set(prepared["model_hashes"]) - {str(project.registry.resolve()), prepared["config"]["bridge_font"]}
    assert pinned == {str(path.resolve()) for path in project.files.values()}
    assert paths.vietocr_model_dir().resolve() == project.files["models/vietocr/base.yml"].parent.resolve()
    assert Path(prepared["config"]["text_detector"]["model_path"]) == project.files["models/v62/det.onnx"].resolve()
    assert Path(prepared["config"]["layout_model"]["model_path"]) == \
        project.files[f"{LAYOUT}/model.safetensors"].parent.resolve()


@pytest.mark.parametrize("name", ["models/vietocr/vgg_seq2seq.pth", TABLE])
def test_new_content_at_the_same_path_is_refused(project, name):
    before = project.prepare()
    project.files[name].write_text("other weights", encoding="utf-8")
    with pytest.raises(IdentityMismatch, match="MODEL_LOCK_MISMATCH"):
        project.prepare()
    # A batch snapshot taken before the change refuses the next document.
    with pytest.raises(IdentityMismatch, match="Runtime input changed"):
        backend.verify_runtime(before)


def test_a_valid_registry_update_changes_identity_and_the_phase_keys(project, tmp_path):
    before = project.prepare()
    project.files["models/vietocr/vgg_seq2seq.pth"].write_text("retrained weights", encoding="utf-8")
    project.write_registry()
    after = project.prepare()
    request = {"pdf_sha256": "p" * 64, "assets": "png", "output_mode": "compact"}
    assert backend.ocr_identity({**before, **request}) != backend.ocr_identity({**after, **request})
    assert text_key(before) != text_key(after)
    receipt = tmp_path / "done.json"
    receipt.write_text("{}", encoding="utf-8")
    structure = lambda prepared: scheduler.stage_key("structure", {**prepared, "device": "cuda"},
                                                     {"python": prepared["text_python"]}, receipt, "code", "c")
    # A Docling model update reruns phase B and keeps phase A's key.
    project.files[TABLE].write_text("new table model", encoding="utf-8")
    project.write_registry()
    docling_updated = project.prepare()
    assert structure(docling_updated) != structure(after)
    assert text_key(docling_updated) == text_key(after)


def test_a_missing_model_fails_before_any_model_library_loads(project):
    project.files["models/vietocr/base.yml"].unlink()
    code = ("import sys\nfrom ocr_pipeline.backend import prepare_backend\n"
            f"try:\n    prepare_backend({str(project.config)!r}, 'unified_gpu_full_ocr', {str(project.envs)!r}, preflight=False)\n"
            "except FileNotFoundError as error:\n    print('MISSING', 'MODEL_MISSING' in str(error))\n"
            "print('LOADED', sorted(m for m in ('torch', 'vietocr', 'onnxruntime', 'docling') if m in sys.modules))")
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT), str(ROOT / "src")])}
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr[-2000:]
    assert "MISSING True" in result.stdout and "LOADED []" in result.stdout


def test_the_registry_must_pin_every_file_vietocr_loads(project):
    project.write_registry(skip=("models/vietocr/vgg-seq2seq.yml",))
    with pytest.raises(IdentityMismatch, match="MODEL_REGISTRY_INCOMPLETE"):
        project.prepare()


@pytest.mark.parametrize("name", ["models/v62/det.onnx", f"{LAYOUT}/model.safetensors", TABLE])
def test_the_registry_cannot_omit_an_effective_model_file(project, name):
    project.write_registry(skip=(name,))
    with pytest.raises(IdentityMismatch, match="MODEL_REGISTRY_INCOMPLETE"):
        project.prepare()


@pytest.mark.parametrize("role", ["layout", "table", "formula"])
def test_docling_revision_reference_must_be_pinned(project, role):
    project.write_registry(skip=(REFS[role],))
    with pytest.raises(IdentityMismatch, match="MODEL_REGISTRY_INCOMPLETE"):
        project.prepare()


def test_hashed_reference_cannot_select_another_revision(project):
    project.files[REFS["table"]].write_text("another-revision", encoding="utf-8")
    project.write_registry()  # All listed file hashes agree; the loader selection does not.
    with pytest.raises(IdentityMismatch, match="MODEL_SELECTION_CHANGED"):
        project.prepare()


def test_registry_cannot_declare_a_repo_the_locked_docling_does_not_use(project):
    registry = json.loads(project.registry.read_text(encoding="utf-8"))
    registry["snapshots"]["table"]["repo"] = "x/unused-table-model"
    # Also supply a pinned snapshot to show this is a loader-selection check,
    # not just a missing-directory check.
    unused = paths.models_dir() / "docling/huggingface/hub/models--x--unused-table-model/snapshots/r/model.bin"
    unused.parent.mkdir(parents=True)
    unused.write_bytes(b"unused weights")
    registry["files"]["models/" + unused.relative_to(paths.models_dir()).as_posix()] = scheduler.sha256(unused)
    project.registry.write_text(json.dumps(registry), encoding="utf-8")
    with pytest.raises(IdentityMismatch, match="MODEL_SELECTION_CHANGED"):
        project.prepare()


def test_an_unlisted_processor_config_is_rejected_before_and_after_snapshot(project):
    before = project.prepare()
    processor = project.files[f"{LAYOUT}/model.safetensors"].parent / "preprocessor_config.json"
    processor.write_text('{"size": 640}', encoding="utf-8")
    with pytest.raises(IdentityMismatch, match="MODEL_REGISTRY_INCOMPLETE"):
        project.prepare()
    with pytest.raises(IdentityMismatch, match="MODEL_REGISTRY_INCOMPLETE"):
        backend.verify_runtime(before)
    # Only an explicit registry update legitimizes this new model input.
    project.files[f"{LAYOUT}/preprocessor_config.json"] = processor
    project.write_registry()
    assert text_key(project.prepare()) != text_key(before)


def test_diagnosis_verifies_effective_model_store(project, monkeypatch):
    from ocr_runtime import diagnose
    relative = "models/v62/runtime-models.json"
    root = project.registry.parent / "diagnose-checkout"
    registry = root / relative
    registry.parent.mkdir(parents=True)
    registry.write_bytes(project.registry.read_bytes())
    monkeypatch.setattr(paths, "PROJECT_ROOT", root)
    report = diagnose._registry(verify=True)
    assert report["files_present"] == len(project.files)
    assert report["missing"] == report["hash_mismatch"] == []
    weights = project.files["models/vietocr/vgg_seq2seq.pth"]
    assert report["selected_files"]["models/vietocr/vgg_seq2seq.pth"] == str(weights.resolve())
    weights.write_text("changed weights", encoding="utf-8")
    assert diagnose._registry(verify=True)["hash_mismatch"] == ["models/vietocr/vgg_seq2seq.pth"]


def test_without_overrides_the_pinned_paths_are_the_checkout_paths(monkeypatch):
    for name in ("OCR_MODELS_DIR", "VIETOCR_MODEL_DIR"):
        monkeypatch.delenv(name, raising=False)
    registry = json.loads((ROOT / "models/v62/runtime-models.json").read_text(encoding="utf-8"))
    for name in registry["files"]:
        assert paths.registry_model_path(name) == paths.PROJECT_ROOT / name


def test_the_vietocr_engine_resolves_its_files_with_the_shared_resolver():
    source = (ROOT / "src/ocr_recognition/vietnamese_seq2seq_engine.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                and node.module == "ocr_runtime.paths" for alias in node.names}
    assert {"vietocr_model_dir", "VIETOCR_FILES"} <= imported
    assert "VIETOCR_MODEL_DIR" not in source and "models_dir" not in source


def test_the_worker_refuses_a_model_changed_after_the_snapshot(tmp_path):
    from importlib import metadata
    lock = tmp_path / "windows-text-gpu.lock"
    lock.write_text(f"pydantic=={metadata.version('pydantic')}\n", encoding="utf-8")
    weights = tmp_path / "weights.bin"
    weights.write_text("pinned", encoding="utf-8")
    request = {"lock_hashes": {str(lock): scheduler.sha256(lock)},
               "model_hashes": {str(weights): scheduler.sha256(weights)},
               "identity": {"source": fingerprint.extraction_fingerprint()},
               "config": {"ocr_source_policy": "gpu_ocr_only_v1"}, "finalize_document": False,
               "stages": {"export": {"code": fingerprint.stage_fingerprint("export")}}}
    weights.write_text("replaced", encoding="utf-8")
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT), str(ROOT / "src")])}
    result = subprocess.run([sys.executable, "-m", "ocr_workers.phases", "--request", str(path), "--phase", "export"],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode != 0 and "Runtime input changed during document phases" in result.stderr


def other_models(tmp_path, project):
    """Different model files at other directories; the pinned ones stay intact."""
    other = tmp_path / "other selection"
    for name, path in project.files.items():
        target = other / ("vietocr" if name.startswith("models/vietocr/") else "store") / \
            Path(name).relative_to("models/vietocr" if name.startswith("models/vietocr/") else "models")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("different content " + name, encoding="utf-8")
    return other


@pytest.mark.parametrize("variable,subdirectory", [("VIETOCR_MODEL_DIR", "vietocr"), ("OCR_MODELS_DIR", "store")])
def test_switching_the_model_directory_after_the_snapshot_is_refused(project, tmp_path, monkeypatch, variable,
                                                                    subdirectory):
    before = project.prepare()
    other = other_models(tmp_path, project)
    monkeypatch.setenv(variable, str(other / subdirectory))
    with pytest.raises(IdentityMismatch, match="MODEL_SELECTION_CHANGED"):
        backend.verify_runtime(before)
    # A document owner starts with the snapshot's directories and agrees.
    for name, value in before["model_env"].items():
        monkeypatch.setenv(name, value)
    backend.verify_runtime(before)


def test_children_start_with_the_snapshot_model_directories(project, tmp_path, monkeypatch):
    before = project.prepare()
    monkeypatch.setenv("VIETOCR_MODEL_DIR", str(other_models(tmp_path, project) / "vietocr"))
    seen = {}

    def capture(command, **kwargs):
        seen.update(kwargs["env"])
        raise RuntimeError("captured")

    monkeypatch.setattr(backend, "supervised_run", capture)
    processor = backend.GPUProcessor(before)
    item = {"id": "doc", "path": str(tmp_path / "doc.pdf"), "pdf_sha256": "p" * 64}
    with pytest.raises(RuntimeError, match="captured"):
        processor(item, {}, tmp_path / "out", resume=False, force_ocr=False)
    assert {name: seen[name] for name in before["model_env"]} == before["model_env"]
    # The scheduler gives the phase workers the same directories.
    monkeypatch.setattr(scheduler, "supervised_run", capture)
    monkeypatch.setattr(scheduler, "sys", SimpleNamespace(modules={}))
    monkeypatch.setenv("OCR_GPU_LEASE_DIR", str(tmp_path / "leases"))
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF fixture")
    seen.clear()
    request = {**before, "pdf": str(pdf), "device": "cpu", "allow_cpu_benchmark": True, "output": str(tmp_path / "o"),
               "work_dir": str(tmp_path / "jobs"), "stage_cache_dir": str(tmp_path / "stages"), "finalize_document": False}
    with pytest.raises(RuntimeError, match="captured"):
        scheduler.run_document(request)
    assert {name: seen[name] for name in before["model_env"]} == before["model_env"]
    saved = json.loads(next((tmp_path / "jobs").glob("*/request.json")).read_text(encoding="utf-8"))
    key_env = scheduler.stage_env("text", seen)
    assert key_env == {"OCR_MODELS_DIR": before["model_env"]["OCR_MODELS_DIR"],
                       "VIETOCR_MODEL_DIR": before["model_env"]["VIETOCR_MODEL_DIR"]}
    assert saved["model_selection"] == before["model_selection"]


def test_the_worker_refuses_a_model_selection_that_moved(project, tmp_path):
    from importlib import metadata
    before = project.prepare()
    lock = tmp_path / "windows-text-gpu.lock"
    lock.write_text(f"pydantic=={metadata.version('pydantic')}\n", encoding="utf-8")
    request = {"lock_hashes": {str(lock): scheduler.sha256(lock)}, "model_hashes": before["model_hashes"],
               "model_selection": before["model_selection"],
               "identity": {"source": fingerprint.extraction_fingerprint()},
               "config": {"ocr_source_policy": "gpu_ocr_only_v1"}, "finalize_document": False,
               "stages": {"export": {"code": fingerprint.stage_fingerprint("export")}}}
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    base = {k: v for k, v in os.environ.items() if k not in ("OCR_MODELS_DIR", "VIETOCR_MODEL_DIR")}
    env = {**base, **before["model_env"], "PYTHONPATH": os.pathsep.join([str(ROOT), str(ROOT / "src")])}
    command = [sys.executable, "-m", "ocr_workers.phases", "--request", str(path), "--phase", "export"]
    moved = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=120,
                           env={**env, "VIETOCR_MODEL_DIR": str(other_models(tmp_path, project) / "vietocr")})
    assert moved.returncode != 0 and "MODEL_SELECTION_CHANGED" in moved.stderr
    pinned = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=120, env=env)
    assert "MODEL_SELECTION_CHANGED" not in pinned.stderr
