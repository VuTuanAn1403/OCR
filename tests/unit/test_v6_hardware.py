"""Hardware profiles (proposal V6 ENV-01, review item R-05)."""
from process_test_helpers import historical_profiles
import sys

import pytest

from src.ocr.application.convert_document import ConvertDocumentUseCase
from src.ocr.runtime.config import ConfigError, config_hash
from src.ocr.runtime.hardware import apply_paths, load_hardware, preparse_hardware
from src.ocr.runtime.run_manifest import RunRecorder


def _write(tmp_path, body, name="hw.yaml"):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_bundled_profiles_load_by_name():
    local = load_hardware("cpu_local")
    assert (local.device, local.workers, local.threads_per_worker, local.batch_size) == ("cpu", 1, None, None)
    colab = load_hardware("colab_gpu")
    assert colab.device == "cuda" and colab.paths["output_dir"].startswith("/content/drive/")
    assert len(colab.record()["sha256"]) == 64


@pytest.mark.parametrize("body, message", [
    ("hardware: {name: x, gpu_count: 2}", "unknown hardware keys"),
    ("hardware: {name: x, device: tpu}", "hardware.device"),
    ("hardware: {name: x, workers: 0}", "positive integer"),
    ("hardware: {name: x, threads_per_worker: '4'}", "positive integer"),
    ("hardware: {name: x, paths: {tmp_dir: /tmp}}", "hardware.paths"),
    ("hardware: {device: cpu}", "hardware.name"),
    ("profiles: {}", "no 'hardware' mapping"),
])
def test_invalid_profiles_are_errors(tmp_path, body, message):
    with pytest.raises(ConfigError, match=message):
        load_hardware(_write(tmp_path, body))


def test_missing_profile_is_an_error():
    with pytest.raises(ConfigError, match="not found"):
        load_hardware("no_such_machine")


def test_environment_paths_win_over_the_profile(tmp_path, monkeypatch):
    profile = load_hardware(_write(tmp_path, "hardware:\n  name: x\n  paths:\n"
                                             "    cache_dir: /persist/cache\n    output_dir: /persist/out\n"))
    monkeypatch.setenv("OCR_OUTPUT_DIR", "/explicit/out")
    monkeypatch.setenv("OCR_CACHE_DIR", "")  # unset, restored at teardown
    assert apply_paths(profile) == {"OCR_CACHE_DIR": "/persist/cache"}
    import os
    assert os.environ["OCR_OUTPUT_DIR"] == "/explicit/out"


def test_preparse_reads_only_the_hardware_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("OCR_MODELS_DIR", "")  # unset, restored at teardown
    path = _write(tmp_path, "hardware: {name: lab, paths: {models_dir: /models}}")
    profile = preparse_hardware(["doc.pdf", "--profile", "fast", "--hardware", str(path)])
    assert profile.name == "lab"
    import os
    assert os.environ["OCR_MODELS_DIR"] == "/models"
    assert preparse_hardware(["doc.pdf"]) is None


def test_batch_size_reaches_the_hashed_configuration():
    base = ConvertDocumentUseCase(config_path=historical_profiles()).resolve_profile("balanced", "cpu")
    tuned = ConvertDocumentUseCase(config_path=historical_profiles(), batch_size=4).resolve_profile("balanced", "cpu")
    assert tuned["batch_size"] == 4 and config_hash(tuned) != config_hash(base)
    with pytest.raises(ValueError, match="batch_size"):
        ConvertDocumentUseCase(config_path=historical_profiles(), batch_size=0)


def test_batch_cli_flags_win_over_the_hardware_profile(tmp_path, monkeypatch):
    import benchmark.baselines.legacy_cli.batch_runner as batch_runner
    captured = {}

    class Runner:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def execute_batch(self, limit=None):
            pass

    path = _write(tmp_path, "hardware: {name: box, device: cpu, workers: 3, threads_per_worker: 2, batch_size: 4}")
    monkeypatch.setattr(batch_runner, "BatchOCRRunner", Runner)
    monkeypatch.setattr(sys, "argv", ["ocrpdf-batch", "--hardware", str(path), "--output", str(tmp_path)])
    batch_runner.main()
    assert (captured["device"], captured["workers"], captured["threads_per_worker"], captured["batch_size"]) == \
        ("cpu", 3, 2, 4)
    assert captured["hardware_profile"]["name"] == "box"
    monkeypatch.setattr(sys, "argv", ["ocrpdf-batch", "--hardware", str(path), "--output", str(tmp_path),
                                      "--workers", "1", "--threads-per-worker", "6"])
    batch_runner.main()
    assert (captured["workers"], captured["threads_per_worker"]) == (1, 6)


def test_run_manifest_records_requested_and_measured_hardware(tmp_path):
    profile = load_hardware("cpu_local")
    recorder = RunRecorder("test", config_path=ConvertDocumentUseCase(config_path=historical_profiles()).config_path, profile="fast",
                           profile_config={"device": "cpu"}, device="cpu", cache_dir=tmp_path, resume=False,
                           assets_mode="none", hardware_profile=profile.record())
    assert recorder.data["hardware_profile"]["name"] == "cpu_local"
    assert "cpu_count_logical" in recorder.data["hardware"]
