"""Stage cache of the V6.3 document phases (P11b).

A fake phase worker runs as a real subprocess and writes stage files and
receipts through the real `ocr_workers.stage_io`; its call log proves which
phases ran. Code identities are set per test; the real closures are checked
separately below.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

from ocr_pipeline import scheduler
from ocr_runtime import fingerprint
from ocr_runtime.process_tree import PhaseExitError, supervised_run

ROOT = Path(__file__).resolve().parents[2]
FAKE_PHASE = r'''
import json, sys
from pathlib import Path
from ocr_artifacts.atomic_io import atomic_write_json
from ocr_workers.stage_io import read, stage_dir, write_receipt
request = read(sys.argv[sys.argv.index("--request") + 1])
phase = sys.argv[sys.argv.index("--phase") + 1]
with open(request["call_log"], "a", encoding="utf-8") as log:
    log.write(phase + "\n")
if phase in request.get("fail_phases", ()):
    sys.exit(3)
root = stage_dir(request, phase)
code = request["stages"][phase]["code"]
if phase == "text":
    path = root / "text" / "page-0001.json"
    atomic_write_json(path, {"text": request["identity"]["pdf"][:12], "a": code})
    write_receipt(request, "text", [path], total_pages=1, selected_pages=[1], init_seconds=1.0, seconds=2.0, placement={})
elif phase == "structure":
    page = read(stage_dir(request, "text") / "text" / "page-0001.json")
    path = root / "structure" / "page-0001.json"
    atomic_write_json(path, {**page, "b": code})
    write_receipt(request, "structure", [path], seconds=3.0, placement=[])
else:
    page = read(stage_dir(request, "structure") / "structure" / "page-0001.json")
    output = Path(request["output"]) / Path(request["pdf"]).stem
    atomic_write_json(output / "document.json", {**page, "e": code,
                      "stages": {p: request["stages"][p]["reused"] for p in ("text", "structure")}})
    path = root / "export.json"
    atomic_write_json(path, {"output": str(output), "validation": "PASS"})
    write_receipt(request, "export", [path])
'''


@pytest.fixture
def harness(tmp_path, monkeypatch):
    worker = tmp_path / "fake_phase.py"
    worker.write_text(FAKE_PHASE, encoding="utf-8")
    code = {"text": "a1", "structure": "b1", "export": "e1"}
    monkeypatch.setattr(fingerprint, "stage_fingerprint",
                        lambda stage, legacy=False: code[stage] + ("-legacy" if legacy else ""))
    monkeypatch.setattr(scheduler, "sys", SimpleNamespace(modules={}))
    monkeypatch.setenv("OCR_GPU_LEASE_DIR", str(tmp_path / "leases"))
    for name in ("OCR_MODELS_DIR", "VIETOCR_MODEL_DIR", "HF_HOME"):
        monkeypatch.delenv(name, raising=False)

    def fake_supervised_run(command, **kwargs):
        tail = command[command.index("--request"):]
        return supervised_run([sys.executable, str(worker), *tail], **kwargs)

    monkeypatch.setattr(scheduler, "supervised_run", fake_supervised_run)
    files = {}
    for name, content in (("models/vietocr/weights.pth", "recognizer"), ("models/docling/table/model.bin", "table"),
                          ("requirements/windows-text-gpu.lock", "text lock"),
                          ("requirements/windows-docling-gpu.lock", "docling lock")):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        files[name] = path
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.7 fake")
    calls = tmp_path / "calls.txt"

    def request(**changes):
        base = {"pdf": str(pdf), "device": "cpu", "allow_cpu_benchmark": True,
                "config": {"profile": "p", "ocr_source_policy": "gpu_ocr_only_v1", "render_dpi": 300,
                           "docling": {"enabled": True}},
                "text_python": sys.executable, "docling_python": sys.executable,
                "model_hashes": {str(files[n]): scheduler.sha256(files[n])
                                 for n in ("models/vietocr/weights.pth", "models/docling/table/model.bin")},
                "lock_hashes": {str(files[n]): scheduler.sha256(files[n])
                                for n in ("requirements/windows-text-gpu.lock", "requirements/windows-docling-gpu.lock")},
                "output": str(tmp_path / "out"), "work_dir": str(tmp_path / "jobs"),
                "stage_cache_dir": str(tmp_path / "stages"), "finalize_document": False,
                "call_log": str(calls), "lease_timeout": 5, "phase_timeout": 120}
        return {**base, **changes}

    def run(resume=True, **changes):
        calls.unlink(missing_ok=True)
        result = scheduler.run_document(request(**changes), resume=resume)
        return calls.read_text(encoding="utf-8").split(), result

    return SimpleNamespace(run=run, request=request, code=code, files=files, pdf=pdf, calls=calls, tmp=tmp_path)


def stage_dir(harness, phase, result):
    return harness.tmp / "stages" / phase / result["stages"][phase]["key"]


def test_first_run_runs_every_phase_and_commits_both_stages(harness):
    calls, result = harness.run(resume=False)
    assert calls == ["text", "structure", "export"]
    for phase in ("text", "structure"):
        directory = stage_dir(harness, phase, result)
        assert scheduler.committed_stage(directory, phase, result["stages"][phase]["key"])
    assert not list((harness.tmp / "stages" / "text").glob("*.tmp-*"))


def test_resume_reuses_committed_stages_and_records_it(harness):
    harness.run(resume=False)
    calls, result = harness.run()
    assert calls == ["export"]
    assert result["stages"]["text"]["reused"] and result["stages"]["structure"]["reused"]
    document = json.loads((harness.tmp / "out/doc/document.json").read_text(encoding="utf-8"))
    assert document["stages"] == {"text": True, "structure": True}


def test_without_resume_every_phase_runs_again(harness):
    harness.run(resume=False)
    calls, result = harness.run(resume=False)
    assert calls == ["text", "structure", "export"]
    assert not result["stages"]["text"]["reused"]


@pytest.mark.parametrize("phase,expected", [
    ("export", ["export"]),                                  # Markdown/JSON renderers, validator
    ("structure", ["structure", "export"]),                  # code only phase B loads: phase A reused
    ("text", ["text", "structure", "export"]),               # VietOCR/detector/layout code
])
def test_code_change_reruns_its_phase_and_everything_downstream(harness, phase, expected):
    harness.run(resume=False)
    harness.code[phase] += "-edited"
    calls, _ = harness.run()
    assert calls == expected


@pytest.mark.parametrize("name,expected", [
    ("requirements/windows-docling-gpu.lock", ["structure", "export"]),       # Docling runtime
    ("requirements/windows-text-gpu.lock", ["text", "structure", "export"]),  # shared runtime
    ("models/docling/table/model.bin", ["structure", "export"]),              # Docling model
    ("models/vietocr/weights.pth", ["text", "structure", "export"]),          # VietOCR model
])
def test_model_or_lock_change_reruns_the_phases_that_load_it(harness, name, expected):
    harness.run(resume=False)
    harness.files[name].write_text("changed", encoding="utf-8")
    calls, _ = harness.run()
    assert calls == expected


@pytest.mark.parametrize("name", fingerprint.COORDINATOR_CODE)
def test_editing_coordinator_code_invalidates_every_stage(harness, monkeypatch, name):
    """F05: the scheduler, backend, document owner and request builders run
    outside the phase processes; an edit to any of them reruns every phase."""
    tree = harness.tmp / "tree"
    shutil.copytree(ROOT / "src", tree / "src", ignore=shutil.ignore_patterns("__pycache__"))
    (tree / "scripts").mkdir()
    shutil.copy2(ROOT / "scripts/docling_structure_worker.py", tree / "scripts")
    monkeypatch.setattr(fingerprint, "LEGACY_ROOT", tree)
    _, first = harness.run(resume=False)
    assert harness.run()[0] == ["export"]
    before = fingerprint.coordinator_fingerprint()
    target = tree / name
    target.write_text(target.read_text(encoding="utf-8") + "\n# coordinator edit\n", encoding="utf-8")
    assert fingerprint.coordinator_fingerprint() != before
    calls, second = harness.run()
    assert calls == ["text", "structure", "export"]
    assert all(second["stages"][p]["key"] != first["stages"][p]["key"] for p in scheduler.PHASES)
    assert not second["stages"]["text"]["reused"] and not second["stages"]["structure"]["reused"]


@pytest.mark.parametrize("name,expected", [
    ("VIETOCR_MODEL_DIR", ["text", "structure", "export"]),  # VietOCR weights of phase A
    ("HF_HOME", ["export"]),  # never read: the Docling client sets it from OCR_MODELS_DIR
    ("OCR_MODELS_DIR", ["text", "structure", "export"]),     # both
])
def test_model_location_variables_are_stage_inputs(harness, monkeypatch, name, expected):
    harness.run(resume=False)
    monkeypatch.setenv(name, str(harness.tmp / "other models"))
    assert harness.run()[0] == expected


def test_stage_env_resolves_like_the_worker_does(monkeypatch):
    monkeypatch.setenv("OCR_MODELS_DIR", "models elsewhere")
    monkeypatch.delenv("VIETOCR_MODEL_DIR", raising=False)
    expected = str((scheduler.ROOT / "models elsewhere").resolve())
    assert scheduler.stage_env("text") == {"OCR_MODELS_DIR": expected, "VIETOCR_MODEL_DIR": None}
    assert scheduler.stage_env("structure") == {"OCR_MODELS_DIR": expected}
    assert scheduler.stage_env("export") == {}


def test_coordinator_code_is_extraction_code():
    extraction = {name for name, _ in fingerprint.closure_entries("extraction")}
    assert set(fingerprint.COORDINATOR_CODE) <= extraction
    assert len(fingerprint.coordinator_entries()) == len(fingerprint.COORDINATOR_CODE)


def test_config_pdf_and_page_changes_rerun_everything(harness):
    harness.run(resume=False)
    request = harness.request()
    assert harness.run(config={**request["config"], "render_dpi": 200})[0] == ["text", "structure", "export"]
    assert harness.run(pages=[1])[0] == ["text", "structure", "export"]
    harness.pdf.write_bytes(b"%PDF-1.7 another document")
    assert harness.run()[0] == ["text", "structure", "export"]


def test_legacy_route_has_its_own_stage_identity(harness):
    harness.run(resume=False)
    request = harness.request()
    calls, _ = harness.run(config={**request["config"], "ocr_source_policy": "native_first_v62"})
    assert calls == ["text", "structure", "export"]


def test_tampered_stage_output_is_never_reused(harness):
    _, first = harness.run(resume=False)
    page = stage_dir(harness, "structure", first) / "structure/page-0001.json"
    page.write_text('{"forged": true}', encoding="utf-8")
    calls, second = harness.run()
    assert calls == ["structure", "export"]
    assert json.loads((stage_dir(harness, "structure", second) / "structure/page-0001.json").read_text(
        encoding="utf-8")) != {"forged": True}


def test_regenerated_identical_upstream_keeps_downstream_valid(harness):
    """Stage keys address content: a phase A rerun that reproduces the same
    receipt byte for byte leaves phase B valid (real receipts carry timings)."""
    _, first = harness.run(resume=False)
    (stage_dir(harness, "text", first) / "text/page-0001.json").write_text("{}", encoding="utf-8")
    calls, _ = harness.run()
    assert calls == ["text", "export"]


def test_uncommitted_or_temporary_stage_directories_are_never_reused(harness):
    """Phase A runs again; the fake reproduces its receipt byte for byte, so
    phase B stays valid (see the test above)."""
    _, first = harness.run(resume=False)
    text = stage_dir(harness, "text", first)
    (text / "exited.json").unlink()
    assert harness.run()[0] == ["text", "export"]
    # A leftover attempt directory next to a missing committed one.
    os.replace(text, text.with_name(text.name + ".tmp-crashed"))
    assert harness.run()[0] == ["text", "export"]


def test_failed_phase_commits_nothing_downstream_and_resume_restarts_there(harness):
    with pytest.raises(PhaseExitError):
        harness.run(resume=False, fail_phases=["text"])
    assert harness.calls.read_text(encoding="utf-8").split() == ["text"]
    assert not [p for p in (harness.tmp / "stages" / "text").iterdir() if ".tmp-" not in p.name]
    assert not (harness.tmp / "stages" / "structure").exists()
    assert not (harness.tmp / "out/doc/document.json").exists()
    with pytest.raises(PhaseExitError):
        harness.run(resume=False, fail_phases=["structure"])
    calls, result = harness.run()
    assert calls == ["structure", "export"]
    assert result["stages"]["text"]["reused"]


def test_stage_models_and_locks_are_partitioned_by_role(tmp_path):
    layout = tmp_path / "models/docling/hub/heron"
    config = {"text_detector": {"model_path": str(tmp_path / "models/v62/det.onnx")},
              "layout_model": {"model_path": str(layout)}, "bridge_font": str(tmp_path / "assets/font.ttf")}
    models = {str(tmp_path / "models/v62/det.onnx"): "d", str(layout / "model.safetensors"): "l",
              str(tmp_path / "models/vietocr/w.pth"): "v", str(tmp_path / "models/docling/table/t.bin"): "t",
              str(tmp_path / "assets/font.ttf"): "f", str(tmp_path / "elsewhere/unknown.bin"): "u"}
    owned = {phase: set(scheduler.stage_models(phase, models, config).values()) for phase in scheduler.PHASES}
    assert owned == {"text": {"d", "l", "v", "u"}, "structure": {"l", "t", "f", "u"}, "export": {"u"}}
    locks = {"r/windows-text-gpu.lock": "x", "r/windows-docling-gpu.lock": "y"}
    assert scheduler.stage_locks("text", locks) == {"r/windows-text-gpu.lock": "x"}
    assert scheduler.stage_locks("structure", locks) == locks


# Real closures of the current code.

def names(stage, legacy=False):
    return {name for name, _ in fingerprint.stage_entries(stage, legacy=legacy)}


def test_each_phase_closure_holds_its_own_code_only():
    text, structure, export = names("text"), names("structure"), names("export")
    # Shared schema and artifact code: a change reruns every phase.
    common = {"src/ocr_workers/phases.py", "src/ocr_workers/stage_io.py", "src/ocr_runtime/fingerprint.py",
              "src/ocr_contracts/page.py", "src/ocr_artifacts/atomic_io.py"}
    assert common <= text & structure & export
    assert "src/ocr_workers/phase_text.py" in text - structure - export
    assert {"src/ocr_workers/phase_structure.py", "src/ocr_workers/docling_server.py",
            "scripts/docling_structure_worker.py"} <= structure - text - export
    assert "src/ocr_workers/phase_export.py" in export - text - structure
    assert not {n for n in structure if n.startswith(("src/ocr_recognition/", "src/ocr_layout/", "src/ocr_document/"))}
    assert not {n for n in export if n.startswith(("src/ocr_recognition/", "src/ocr_layout/", "src/ocr_structure/"))}
    assert "src/ocr_document/validation.py" in export - text  # export-only document code
    assert not {n for n in text | structure | export if n.startswith(("src/ocr_keywords/", "src/ocr_reporting/"))}
    assert names("structure") <= {n for n, _ in fingerprint.closure_entries("extraction")}


def test_no_phase_can_restore_a_legacy_route():
    for phase in fingerprint.STAGES:
        with pytest.raises(ValueError, match="retired"):
            names(phase, legacy=True)
        assert not any(name.startswith("src/ocr/") for name in names(phase))


@pytest.mark.parametrize("extra,ok", [("", True), ("import ocr_recognition.blocks\n", False)])
def test_loading_code_outside_the_phase_closure_is_refused(extra, ok):
    code = ("import ocr_workers.phases, ocr_workers.phase_structure\n" + extra +
            "from ocr_runtime import fingerprint\nfingerprint.assert_loaded_code_in_stage('structure')\nprint('OK')")
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT), str(ROOT / "src")])}
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert (result.returncode == 0 and "OK" in result.stdout) == ok, result.stderr[-2000:]
    if not ok:
        assert "STAGE_CLOSURE_VIOLATION" in result.stderr


def test_phase_worker_refuses_code_that_differs_from_its_stage_key(tmp_path):
    from importlib import metadata
    lock = tmp_path / "windows-text-gpu.lock"
    lock.write_text(f"pydantic=={metadata.version('pydantic')}\n", encoding="utf-8")
    request = {"lock_hashes": {str(lock): scheduler.sha256(lock)}, "model_hashes": {},
               "identity": {"source": fingerprint.extraction_fingerprint()},
               "config": {"ocr_source_policy": "gpu_ocr_only_v1"}, "finalize_document": False,
               "stages": {"export": {"code": "not-this-code"}}}
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT), str(ROOT / "src")])}
    result = subprocess.run([sys.executable, "-m", "ocr_workers.phases", "--request", str(path), "--phase", "export"],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode != 0 and "differs from its stage key" in result.stderr
