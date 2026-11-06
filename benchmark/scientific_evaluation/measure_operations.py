"""Observe the canonical batch command and publish its measured operation trace."""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
import sys

import psutil

from ocr_artifacts.atomic_io import atomic_write_json
from ocr_artifacts.digest import sha256_json_compact
from ocr_artifacts.hashing import sha256_file
from ocr_pipeline.batch import input_snapshot
from ocr_runtime.fingerprint import code_fingerprints
from ocr_runtime.gpu_lease import gpu_snapshot
from ocr_runtime.paths import PROJECT_ROOT
from ocr_runtime.process_tree import supervised_run

from .canonical_predictions import collect_predictions
from .awake import keep_system_awake
from .stratified_scorecard import _finite, _require

_COMMITTED = re.compile(r"^\[\d+/\d+\] (.+\.pdf): (SUCCEEDED|FAILED_DOCUMENT)$", re.IGNORECASE)


class _PerformanceInformation(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD)] + [
        (name, ctypes.c_size_t) for name in (
            "CommitTotal", "CommitLimit", "CommitPeak", "PhysicalTotal", "PhysicalAvailable",
            "SystemCache", "KernelTotal", "KernelPaged", "KernelNonpaged", "PageSize")
    ] + [(name, wintypes.DWORD) for name in ("HandleCount", "ProcessCount", "ThreadCount")]


def _windows_commit():
    if sys.platform != "win32":
        return None
    get_info = ctypes.WinDLL("Psapi.dll", use_last_error=True).GetPerformanceInfo
    get_info.argtypes = (ctypes.POINTER(_PerformanceInformation), wintypes.DWORD)
    get_info.restype = wintypes.BOOL
    info = _PerformanceInformation(cb=ctypes.sizeof(_PerformanceInformation))
    if not get_info(ctypes.byref(info), info.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    if not info.PageSize or not info.CommitLimit:
        raise OSError("Windows reported invalid system commit counters")
    return {"source": "GetPerformanceInfo", "committed_bytes": info.CommitTotal * info.PageSize,
            "limit_bytes": info.CommitLimit * info.PageSize,
            "headroom_bytes": (info.CommitLimit - info.CommitTotal) * info.PageSize}


def _host_resources(output, evidence):
    errors = {}
    paths = {"output": output, "evidence": evidence}
    disk = {"output": None, "evidence": None, "system_temp": None}
    try:
        paths["system_temp"] = Path(tempfile.gettempdir())
    except OSError as error:
        errors["system_temp"] = str(error)
    for key, path in paths.items():
        try:
            probe = path
            while not probe.is_dir() and probe != probe.parent:
                probe = probe.parent
            usage = shutil.disk_usage(probe)
            disk[key] = {"probe_directory": str(probe), "free_bytes": usage.free, "total_bytes": usage.total}
        except OSError as error:
            errors[key] = str(error)
    commit = None
    try:
        commit = _windows_commit()
    except OSError as error:
        errors["system_commit"] = str(error)
    return {"system_commit": commit, "disk": disk, "errors": errors}


def _response_events(output):
    failures = []
    for path in (output / "logs" / "requests").rglob("response.json"):
        response = json.loads(path.read_text(encoding="utf-8"))
        if response.get("result") is None:
            failures.append({"path": str(path), "sha256": sha256_file(path), "error": response.get("error")})
    messages = [str(row["error"]).casefold() for row in failures]
    return {"failures": failures,
            "timeouts": sum(any(term in message for term in ("timeout", "timed out", "phase exceeded")) for message in messages),
            "oom": sum(any(term in message for term in ("out of memory", "cuda_error_out_of_memory")) for message in messages)}


def measure(args, *, power_state=None):
    output = args.output.resolve()
    evidence = args.evidence.resolve()
    _require(not output.exists() and not evidence.exists() and not evidence.is_relative_to(output)
             and not output.is_relative_to(evidence), "Measurement requires separate new output and evidence directories")
    records = input_snapshot(args.input.resolve())
    _require(records and all(row.get("source_error") is None for row in records), "Measurement input PDF is unreadable")
    name_to_id = {row["name"].casefold(): row["id"] for row in records}
    evidence.mkdir(parents=True)
    collector_hash = sha256_file(Path(__file__))
    initial_host_resources = _host_resources(output, evidence)
    atomic_write_json(evidence / "input.json", {"documents": records, "code_fingerprints": code_fingerprints(),
                                              "collector_sha256": collector_hash,
                                              "host_resources_before_command": initial_host_resources})
    log = evidence / "command.log"
    telemetry = evidence / "telemetry.jsonl"
    started = time.perf_counter()
    last_commit = started
    next_sample = 0.0
    offset, pending = 0, b""
    document_seconds = {}
    peak_rss = peak_vram = None
    samples = 0
    last_sample = started
    maximum_gap = 0.0
    rss_inaccessible_samples = 0
    started_at = datetime.now().astimezone().isoformat()

    def read_commits():
        nonlocal offset, pending, last_commit
        if not log.is_file():
            return
        with log.open("rb") as stream:
            stream.seek(offset)
            data = stream.read()
            offset = stream.tell()
        lines = (pending + data).split(b"\n")
        pending = lines.pop()
        for line in lines:
            matched = _COMMITTED.fullmatch(line.decode("utf-8", errors="replace").strip())
            if matched:
                now = time.perf_counter()
                key = name_to_id[matched[1].casefold()]
                _require(key not in document_seconds, f"Duplicate committed document: {key}")
                document_seconds[key] = now - last_commit
                last_commit = now

    def check_gap(now):
        nonlocal maximum_gap
        maximum_gap = max(maximum_gap, now - last_sample)
        _require(maximum_gap <= args.max_sample_gap,
                 f"MEASUREMENT_INTERRUPTED: telemetry gap {maximum_gap:.3f}s exceeds the measurement limit")

    def observe(pid, seen_pids):
        nonlocal next_sample, peak_rss, peak_vram, samples, last_sample, rss_inaccessible_samples
        read_commits()
        now = time.perf_counter()
        if now < next_sample:
            return
        check_gap(now)
        last_sample = now
        next_sample = now + args.interval
        rss = 0
        inaccessible = []
        processes = []
        try:
            root = psutil.Process(pid)
            processes = [root, *root.children(recursive=True)]
        except psutil.NoSuchProcess:
            pass
        except psutil.AccessDenied:
            inaccessible.append(pid)
        for process in processes:
            try:
                rss += process.memory_info().rss
            except psutil.NoSuchProcess:
                continue
            except psutil.AccessDenied:
                inaccessible.append(process.pid)
        gpu = gpu_snapshot("cuda")
        rss_inaccessible_samples += bool(inaccessible)
        rss_mib = rss / 1024 ** 2
        peak_rss = max(peak_rss or 0, rss_mib)
        peak_vram = max(peak_vram or 0, gpu["used_mib"])
        with telemetry.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"elapsed_seconds": now - started, "root_pid": pid,
                                     "tree": [process.pid for process in processes],
                                     "rss_mib": rss_mib, "inaccessible_pids": inaccessible, "gpu": gpu,
                                     "host_resources": _host_resources(output, evidence)}) + "\n")
        samples += 1

    command = [sys.executable, "-B", str(PROJECT_ROOT / "run_batch.py"), "--input", str(args.input.resolve()),
               "--output", str(output)]
    if args.mode == "cache":
        command.append("--resume")
    try:
        supervised = supervised_run(command, cwd=PROJECT_ROOT, env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                                    log_path=log, timeout=args.timeout, observe=observe)
        read_commits()
        elapsed = time.perf_counter() - started
        check_gap(started + elapsed)
        inventory = collect_predictions([output])
        expected = {doc["id"] for doc in inventory["documents"]}
        _require(document_seconds.keys() == expected, "Commit timing does not cover every acknowledged document")
        events = _response_events(output)
        retries = sum(max(record["attempt"] - 1, 0) for record in
                      json.loads((output / "batch_report.json").read_text(encoding="utf-8"))["documents"])
        trace = {
            "schema_version": "ocr-operation-trace-v1", "run_id": evidence.name, "mode": args.mode,
            "batch_roots": [str(output)], "inventory_sha256": sha256_json_compact(inventory),
            "started_at": started_at, "finished_at": datetime.now().astimezone().isoformat(),
            "elapsed_seconds": elapsed, "document_seconds": document_seconds,
            "peak_rss_mib": peak_rss if not rss_inaccessible_samples else None,
            "observed_peak_rss_mib": peak_rss, "rss_inaccessible_samples": rss_inaccessible_samples,
            "peak_vram_mib": peak_vram, "telemetry_samples": samples,
            "sampling_interval_seconds": args.interval, "rss_scope": "observed_process_tree_rss_sum",
            "rss_pid_scope": "live_descendants", "collector_sha256": collector_hash,
            "maximum_sample_gap_seconds": maximum_gap, "power_guard": power_state,
            "vram_scope": "whole_device_used_memory", "document_timing": "command_start_to_observed_commit_deltas",
            "currency": args.currency, "cost": elapsed * args.cost_per_second if args.cost_per_second is not None else None,
            "retries": retries, "timeouts": events["timeouts"], "oom": events["oom"],
            "worker_response_events": events["failures"], "supervised": supervised,
            "command_log_sha256": sha256_file(log), "telemetry_sha256": sha256_file(telemetry),
            "quality_acceptance": "NOT_EVALUATED",
        }
        atomic_write_json(evidence / "inventory.json", inventory)
        atomic_write_json(evidence / "trace.json", trace)
        print(json.dumps({"status": "MEASURED", "trace": str(evidence / "trace.json"),
                          "pages": sum(doc["total_pages"] for doc in inventory["documents"]),
                          "elapsed_seconds": elapsed, "peak_rss_mib": peak_rss, "peak_vram_mib": peak_vram}), flush=True)
        return trace
    except BaseException as error:
        atomic_write_json(evidence / "failure.json", {"status": "FAILED", "error": f"{type(error).__name__}: {error}",
                                                     "output": str(output), "command": command,
                                                     "mode": args.mode, "started_at": started_at,
                                                     "elapsed_seconds": time.perf_counter() - started,
                                                     "document_seconds": document_seconds,
                                                     "peak_rss_mib": peak_rss, "peak_vram_mib": peak_vram,
                                                     "maximum_sample_gap_seconds": maximum_gap,
                                                     "telemetry_samples": samples, "power_guard": power_state,
                                                     "host_resources_after_failure": _host_resources(output, evidence),
                                                     "rss_inaccessible_samples": rss_inaccessible_samples,
                                                     "measurement_status": "INVALID_FOR_SLO",
                                                     "observed_at": datetime.now().astimezone().isoformat()})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("input", "output", "evidence"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    parser.add_argument("--mode", choices=("cold", "warm", "cache"), required=True)
    parser.add_argument("--interval", type=float, default=2)
    parser.add_argument("--timeout", type=float, default=14400)
    parser.add_argument("--max-sample-gap", type=float, default=30)
    parser.add_argument("--currency", default="VND")
    parser.add_argument("--cost-per-second", type=float)
    args = parser.parse_args()
    if not _finite(args.interval) or args.interval < .5 or not _finite(args.timeout) or args.timeout <= 0:
        parser.error("Use an interval >=0.5 seconds and a positive timeout")
    if not _finite(args.max_sample_gap) or args.max_sample_gap <= args.interval:
        parser.error("Maximum sample gap must be greater than the sampling interval")
    if not re.fullmatch("[A-Z]{3}", args.currency) or args.cost_per_second is not None and not _finite(args.cost_per_second):
        parser.error("Use a three-letter currency and a nonnegative supplied cost rate")
    with keep_system_awake() as power_state:
        measure(args, power_state=power_state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
