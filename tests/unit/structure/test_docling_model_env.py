"""Capture the actual Docling launch boundary; no server or model is run."""
import os

import pytest

from ocr_structure import docling_client


@pytest.mark.parametrize("artifact_variable", ["DOCLING_ARTIFACTS_PATH", "docling_artifacts_path"])
def test_worker_cannot_select_an_inherited_model_store(tmp_path, monkeypatch, artifact_variable):
    outside = str(tmp_path / "unregistered model store")
    cache_aliases = ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE", "TRANSFORMERS_CACHE",
                     "PYTORCH_TRANSFORMERS_CACHE", "PYTORCH_PRETRAINED_BERT_CACHE")
    for name in ("HF_HOME", "EASYOCR_MODULE_PATH", *cache_aliases, artifact_variable):
        monkeypatch.setenv(name, outside)
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    store = tmp_path / "pinned models"
    monkeypatch.setattr(docling_client, "models_dir", lambda: store)
    monkeypatch.setattr(docling_client, "cache_dir", lambda: tmp_path / "jobs")
    python = tmp_path / "python double.exe"
    python.write_bytes(b"not an executable")
    monkeypatch.setenv("OCR_DOCLING_PYTHON", str(python))
    captured = {}

    class LaunchCaptured(Exception):
        pass

    def capture(command, **kwargs):
        captured.update(command=command, **kwargs)
        raise LaunchCaptured

    # Patch where the client looks up Popen; this cannot start a real model.
    monkeypatch.setattr(docling_client.subprocess, "Popen", capture)
    extractor = docling_client.DoclingStructureExtractor({"enabled": True, "num_threads": 2})
    try:
        with pytest.raises(LaunchCaptured):
            extractor._start()
    finally:
        extractor.close()

    env = captured["env"]
    home = store.resolve() / "docling/huggingface"
    assert captured["command"][0] == str(python)
    assert env["HF_HOME"] == str(home)
    assert all(env[name] == str(home / "hub") for name in cache_aliases)
    assert env["EASYOCR_MODULE_PATH"] == str(store.resolve() / "docling/easyocr")
    assert not any(name.casefold() == "docling_artifacts_path" for name in env)
    assert env["HF_HUB_OFFLINE"] == env["TRANSFORMERS_OFFLINE"] == "1"
    assert os.environ[artifact_variable] == outside
    assert os.environ["HF_HUB_CACHE"] == outside


@pytest.mark.parametrize("flag", ["HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"])
def test_client_preserves_scheduler_offline_policy(monkeypatch, flag):
    monkeypatch.delenv(flag, raising=False)
    assert flag not in docling_client._worker_environment({})
    monkeypatch.setenv(flag, "1")
    assert docling_client._worker_environment({})[flag] == "1"
