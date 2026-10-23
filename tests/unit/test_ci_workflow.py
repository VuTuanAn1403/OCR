"""The CI split keeps the whole software regression on push/PR (P13).

Jobs are split by direct dependencies, but no test directory may fall out of
the default runs: model weights and GPU runners stay opt-in, the tests that
need neither still run on every push and pull request. YAML parsing and
command inspection only; this is not a GitHub Actions run.
"""
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/tests.yml"
REGRESSION = ("tests/unit", "tests/scientific", "tests/legacy_compat")


def _jobs():
    workflow = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    return workflow["jobs"]


def _opt_in(job):
    return "workflow_dispatch" in job.get("if", "")


def _commands(job):
    return "\n".join(step.get("run", "") for step in job["steps"])


def test_every_regression_directory_runs_on_push_and_pull_request():
    default = [_commands(job) for job in _jobs().values() if not _opt_in(job)]
    for directory in REGRESSION:
        assert any(f" {directory} " in command.replace("\n", " ") + " " for command in default), directory


def test_default_jobs_download_no_models_and_light_jobs_no_ocr_stack():
    jobs = _jobs()
    for name, job in jobs.items():
        if not _opt_in(job):
            assert "setup_models.py" not in _commands(job) and "setup_vietocr_model.py" not in _commands(job), name
    light = _commands(jobs["light"])
    assert not any(stack in light for stack in ("legacy", "inprocess", "torch]", "download.pytorch.org"))


def test_model_and_gpu_evidence_stay_explicit():
    jobs = _jobs()
    assert _opt_in(jobs["model-integration"]) and _opt_in(jobs["gpu"])
    assert "NOT_RUN" in _commands(jobs["evidence-status"])
