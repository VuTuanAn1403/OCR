import json
import os
from types import SimpleNamespace

import pytest

from benchmark.scientific_evaluation import measure_operations


@pytest.mark.parametrize("rate", [None, 0])
def test_measure_uses_canonical_cli_commits_and_preserves_unknown_cost(tmp_path, monkeypatch, rate):
    source = tmp_path / "source"
    source.mkdir()
    output = tmp_path / "batch"
    evidence = tmp_path / "evidence"
    record = {"id": "d", "name": "d.pdf", "source_error": None}
    monkeypatch.setattr(measure_operations, "input_snapshot", lambda path: [record])
    monkeypatch.setattr(measure_operations, "code_fingerprints", lambda: {"extraction": "fixture"})
    monkeypatch.setattr(measure_operations, "gpu_snapshot", lambda device: {"used_mib": 100})
    monkeypatch.setattr(measure_operations, "collect_predictions", lambda roots: {
        "documents": [{"id": "d", "total_pages": 2}], "batches": []})

    def supervised(command, *, cwd, env, log_path, timeout, observe):
        assert command[2].endswith("run_batch.py") and command[-1] == "--resume"
        output.mkdir()
        (output / "batch_report.json").write_text(json.dumps({"documents": [{"attempt": 1}]}), encoding="utf-8")
        log_path.write_text("[1/1] d.pdf: SUCCEEDED\n", encoding="utf-8")
        observe(os.getpid(), [os.getpid()])
        return {"tree_exited": True}

    monkeypatch.setattr(measure_operations, "supervised_run", supervised)
    result = measure_operations.measure(SimpleNamespace(input=source, output=output, evidence=evidence,
                                                        mode="cache", interval=2, max_sample_gap=30, timeout=60, currency="VND",
                                                        cost_per_second=rate))
    assert result["peak_vram_mib"] == 100 and result["peak_rss_mib"] > 0
    assert result["document_seconds"]["d"] > 0
    assert result["cost"] is None if rate is None else result["cost"] == 0
    assert result["timeouts"] == result["oom"] == result["retries"] == 0
    assert result["quality_acceptance"] == "NOT_EVALUATED"
    assert (evidence / "trace.json").is_file() and not (evidence / "failure.json").exists()
    initial = json.loads((evidence / "input.json").read_text(encoding="utf-8"))["host_resources_before_command"]
    sample = json.loads((evidence / "telemetry.jsonl").read_text(encoding="utf-8"))["host_resources"]
    assert initial["disk"]["output"]["probe_directory"] == str(output.parent)
    assert sample["disk"]["output"]["probe_directory"] == str(output)
    assert sample["disk"]["evidence"]["free_bytes"] <= sample["disk"]["evidence"]["total_bytes"]


@pytest.mark.parametrize("position", ["middle", "tail"])
def test_interrupted_measurement_preserves_partial_data_without_publishing_trace(tmp_path, monkeypatch, position):
    monkeypatch.setattr(measure_operations, "input_snapshot", lambda path: [{"id": "d", "name": "d.pdf", "source_error": None}])
    monkeypatch.setattr(measure_operations, "code_fingerprints", lambda: {})
    monkeypatch.setattr(measure_operations, "gpu_snapshot", lambda device: {"used_mib": 100})
    ticks = iter((0, 1, 2, 40, 41))
    monkeypatch.setattr(measure_operations, "time", SimpleNamespace(perf_counter=lambda: next(ticks)))

    def supervised(command, *, cwd, env, log_path, timeout, observe):
        log_path.write_text("[1/1] d.pdf: SUCCEEDED\n", encoding="utf-8")
        observe(os.getpid(), [os.getpid()])
        if position == "middle":
            observe(os.getpid(), [os.getpid()])
        return {"tree_exited": True}

    monkeypatch.setattr(measure_operations, "supervised_run", supervised)
    args = SimpleNamespace(input=tmp_path, output=tmp_path / "out", evidence=tmp_path / "evidence",
                           mode="warm", interval=2, max_sample_gap=30, timeout=60, currency="VND", cost_per_second=None)
    with pytest.raises(ValueError, match="MEASUREMENT_INTERRUPTED"):
        measure_operations.measure(args)
    failure = json.loads((args.evidence / "failure.json").read_text(encoding="utf-8"))
    assert failure["measurement_status"] == "INVALID_FOR_SLO"
    assert failure["document_seconds"] == {"d": 1}
    assert failure["maximum_sample_gap_seconds"] == 38
    assert "system_commit" in failure["host_resources_after_failure"]
    assert not (args.evidence / "trace.json").exists()


def test_host_resource_query_failures_preserve_missing_values(tmp_path, monkeypatch):
    def unavailable(*args):
        raise OSError("diagnostic fixture unavailable")

    monkeypatch.setattr(measure_operations, "_windows_commit", unavailable)
    monkeypatch.setattr(measure_operations.shutil, "disk_usage", unavailable)
    result = measure_operations._host_resources(tmp_path / "output", tmp_path / "evidence")
    assert result["system_commit"] is None
    assert result["disk"] == {"output": None, "evidence": None, "system_temp": None}
    assert set(result["errors"]) == {"system_commit", "output", "evidence", "system_temp"}


@pytest.mark.parametrize("worker_denied", [False, True])
def test_rss_uses_live_descendants_and_missing_worker_rss_stays_unevaluated(tmp_path, monkeypatch, worker_denied):
    access_denied = measure_operations.psutil.AccessDenied
    no_process = measure_operations.psutil.NoSuchProcess

    def worker_memory():
        if worker_denied:
            raise access_denied(2)
        return SimpleNamespace(rss=32 * 1024 ** 2)

    def process(pid):
        if pid != 1:
            return SimpleNamespace(pid=pid, memory_info=lambda: SimpleNamespace(rss=8192 * 1024 ** 2))
        worker = SimpleNamespace(pid=2, memory_info=worker_memory)
        return SimpleNamespace(pid=1, memory_info=lambda: SimpleNamespace(rss=64 * 1024 ** 2),
                               children=lambda recursive: [worker])

    monkeypatch.setattr(measure_operations, "psutil", SimpleNamespace(
        Process=process, AccessDenied=access_denied, NoSuchProcess=no_process))
    monkeypatch.setattr(measure_operations, "input_snapshot", lambda path: [{"id": "d", "name": "d.pdf", "source_error": None}])
    monkeypatch.setattr(measure_operations, "code_fingerprints", lambda: {})
    monkeypatch.setattr(measure_operations, "gpu_snapshot", lambda device: {"used_mib": 100})
    monkeypatch.setattr(measure_operations, "collect_predictions", lambda roots: {
        "documents": [{"id": "d", "total_pages": 1}], "batches": []})
    output = tmp_path / "out"

    def supervised(command, *, cwd, env, log_path, timeout, observe):
        output.mkdir()
        (output / "batch_report.json").write_text(json.dumps({"documents": [{"attempt": 1}]}), encoding="utf-8")
        log_path.write_text("[1/1] d.pdf: SUCCEEDED\n", encoding="utf-8")
        observe(1, [1, 2, 999])  # PID 999 was once a descendant but now belongs outside the tree.
        return {"tree_exited": True}

    monkeypatch.setattr(measure_operations, "supervised_run", supervised)
    args = SimpleNamespace(input=tmp_path, output=output, evidence=tmp_path / "evidence",
                           mode="warm", interval=2, max_sample_gap=30, timeout=60, currency="VND", cost_per_second=None)
    result = measure_operations.measure(args)
    assert result["peak_rss_mib"] == (None if worker_denied else 96)
    assert result["observed_peak_rss_mib"] == (64 if worker_denied else 96)
    assert result["rss_inaccessible_samples"] == int(worker_denied)
    assert result["rss_pid_scope"] == "live_descendants"
    assert result["peak_vram_mib"] == 100
