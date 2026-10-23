"""One supported execution policy, including former entry points."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ocr_runtime.config import ConfigError, load_profiles, resolve_config_path
from ocr_runtime.pipeline_policy import validate_phase_request, validate_profile

ROOT = Path(__file__).resolve().parents[2]


def profile():
    return copy.deepcopy(load_profiles(ROOT / "config/profiles.yaml")[1]["unified_gpu_full_ocr"])


@pytest.mark.parametrize("body,message", [
    ("profiles_file: loop.yaml\n", "cycle"),
    ("profiles_file: missing.yaml\n", "Cannot read"),
    ("profiles_file: profiles.yaml\nprofiles: {}\n", "overrides"),
    ("profiles_file: profiles.yaml\npipeline: legacy\n", "conflicting"),
    ("profiles_file: ''\n", "non-empty"),
])
def test_aliases_cannot_introduce_another_config(tmp_path, body, message):
    (tmp_path / "profiles.yaml").write_bytes((ROOT / "config/profiles.yaml").read_bytes())
    alias = tmp_path / "loop.yaml"
    alias.write_text(body, encoding="utf-8")
    with pytest.raises(ConfigError, match=message):
        resolve_config_path(alias)


@pytest.mark.parametrize("key,value", [("device", "cpu"), ("native_first", True),
    ("native_first", 0), ("ocr_scope", "selected_pages"), ("ocr_source_policy", "native"),
    ("bridge_policy", "native"), ("primary_engine", "rapidocr"), ("runtime", None),
    ("docling", None), ("document_layout", {"method": "legacy"})])
def test_profile_cannot_enable_a_retired_route(key, value):
    config = profile()
    validate_profile(config)
    config[key] = value
    with pytest.raises(ConfigError):
        validate_profile(config)


@pytest.mark.parametrize("phase", ["text", "structure", "export"])
@pytest.mark.parametrize("changes", [{"device": "cpu"}, {"pages": [1]}, {"finalize_document": True}])
def test_worker_rejects_legacy_requests_before_model_imports(phase, changes):
    import importlib
    module = importlib.import_module("ocr_workers.phase_" + phase)
    request = {"device": "cuda", "config": profile(), **changes}
    with pytest.raises(ConfigError):
        getattr(module, "run_" + phase)(request)


@pytest.mark.parametrize("module,batch", [("src.ocr.cli.run_ocr", False),
    ("src.ocr.cli.batch_runner", True), ("src.ocr.cli.gpu_runner", False),
    ("scripts.run_batch_test_with_monitoring", True), ("scripts.test_new_input_files", True)])
def test_old_supported_entry_points_are_light_and_use_the_same_cli(module, batch):
    code = """import importlib,json,sys
m=importlib.import_module(sys.argv[1])
calls=[]
m._main=lambda *a,**kw:calls.append([a,kw])
m.main()
print(json.dumps({'calls':calls,'heavy':[n for n in ('torch','onnxruntime','docling') if n in sys.modules],
 'historical':[n for n in sys.modules if n.startswith('benchmark.baselines.legacy_cli')]}))
"""
    result = subprocess.run([sys.executable, "-c", code, module], cwd=ROOT, capture_output=True,
        text=True, encoding="utf-8", env={**os.environ, "PYTHONPATH": str(ROOT / "src")}, timeout=60)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout.strip())
    assert data["calls"][0][0] == [batch]
    assert data["heavy"] == data["historical"] == []


@pytest.mark.parametrize("arguments", [["--backend", "legacy"], ["--profile", "fast"],
    ["--device", "cpu"], ["--pages", "1"]])
def test_retired_cli_options_fail_with_no_extraction(tmp_path, arguments):
    from ocr_pipeline.cli import main
    with pytest.raises(SystemExit) as error:
        main(True, ["--input", str(tmp_path), *arguments])
    assert error.value.code == 2
    assert list(tmp_path.iterdir()) == []


def test_retired_notebook_has_no_executable_pipeline():
    notebook = json.loads((ROOT / "kaggle/ocr_pdf_v63_kaggle.ipynb").read_text(encoding="utf-8"))
    assert all(cell["cell_type"] == "markdown" for cell in notebook["cells"])
