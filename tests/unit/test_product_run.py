"""benchmark/product_run.py (V8-042): runners launch ocr_pipeline.cli.main in a child
process on a fresh output, with a derived config the product itself accepts."""
import json
from pathlib import Path

import pytest

from benchmark import product_run
from ocr_runtime.config import declared_pipeline, load_profiles
from ocr_runtime.pipeline_policy import PROFILE, validate_profile

ROOT = Path(__file__).resolve().parents[2]


def test_command_is_the_product_cli_without_resume(tmp_path):
    command = product_run.product_command(tmp_path / "A.pdf", tmp_path / "out", config=tmp_path / "p.yaml",
                                          assets="none", python="python")
    assert command[:3] == ["python", "-B", "-c"]
    assert "from ocr_pipeline.cli import main" in command[3] and "main(False)" in command[3]
    assert command[4] == str((tmp_path / "A.pdf").resolve())
    assert command[command.index("--config") + 1] == str((tmp_path / "p.yaml").resolve())
    for flag in ("--resume", "--retry-failed", "--force-ocr", "--profile", "--device"):
        assert flag not in command
    with pytest.raises(ValueError):
        product_run.product_command("A.pdf", "out", assets="tiff")


def test_derived_config_keeps_declarations_and_passes_product_validation(tmp_path):
    base_path, profile = product_run.base_profile(ROOT / "config/profiles.yaml")
    profile["docling"] = {**profile["docling"], "table_mode": "accurate"}
    derived = product_run.write_config(base_path, profile, tmp_path / "profiles.yaml")
    assert declared_pipeline(derived) == declared_pipeline(base_path)
    _, profiles = load_profiles(derived)
    assert set(profiles) == {PROFILE}
    validate_profile(profiles[PROFILE])
    assert profiles[PROFILE]["docling"]["table_mode"] == "accurate"


class FakeProcess:
    pid = None

    def __init__(self, returncode):
        self.returncode = returncode

    def wait(self):
        return self.returncode


def _launcher(write_output, returncode=0):
    def launch(command, log):
        log.write(b"product log\n")
        output = Path(command[command.index("--output") + 1])
        if write_output:
            document = output / Path(command[4]).stem
            document.mkdir(parents=True)
            (document / "ocr_receipt.json").write_text(json.dumps({"ocr_identity": "abc"}), encoding="utf-8")
            (document / "COMPLETED.json").write_text("{}", encoding="utf-8")
        return FakeProcess(returncode)
    return launch


def test_run_product_records_identity_and_status(tmp_path):
    pdf = tmp_path / "DOC_report.pdf"
    pdf.write_bytes(b"%PDF fake")
    done = product_run.run_product(pdf, tmp_path / "out", launch=_launcher(True))
    assert done["status"] == "COMPLETED" and done["ocr_identity"] == "abc" and done["returncode"] == 0
    assert done["entry_point"] == "ocr_pipeline.cli.main" and done["pdf_sha256"]
    assert Path(done["log"]).read_bytes() == b"product log\n" and Path(done["log"]).parent == tmp_path
    failed = product_run.run_product(pdf, tmp_path / "out2", launch=_launcher(True, returncode=1))
    assert failed["status"] == "FAILED"  # a non-zero exit is a failure even with a marker
    missing = product_run.run_product(pdf, tmp_path / "out3", launch=_launcher(False))
    assert missing["status"] == "FAILED" and missing["ocr_identity"] is None


def test_run_product_refuses_an_output_that_is_not_fresh(tmp_path):
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "old.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="fresh"):
        product_run.run_product(tmp_path / "A.pdf", tmp_path / "out", launch=_launcher(True))


def test_peak_vram_reads_scheduler_samples_and_events():
    scheduler = {"phases": {"text": {"samples": [{"used_mib": 900}, {"used_mib": 2100}]},
                            "export": {"samples": []}},
                 "events": [{"vram": {"used_mib": 2500}}, {"vram": {}}]}
    assert product_run.peak_device_vram_mib(scheduler) == 2500
    assert product_run.peak_device_vram_mib({"phases": {}}) is None
    assert product_run.peak_device_vram_mib(None) is None


def test_memory_sampler_without_a_process_reports_unknown():
    with product_run.TreeMemorySampler(None) as memory:
        pass
    assert memory.peak_mb is None
