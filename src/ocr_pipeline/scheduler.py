"""Document-wide A -> process exit -> B, with a CPU-only coordinating process.

This module deliberately imports neither Torch nor pipeline/model modules.
An OS-backed lease spans both phases and the final export, even on 4 GB GPUs.

Stage cache (P11b): phase A and phase B write into content-addressed stage
directories `<stage cache>/<phase>/<key>`. A stage key covers the upstream
receipt, the phase's own code closure, the coordinator code that builds its
request and environment, its effective config, the models and locks it loads
with the variables that locate them, its interpreters and the protocol. With
`resume`, a committed
stage whose files still match its receipt is reused instead of run again;
any change to those inputs gives a new key that never sees older output.
Export always runs, into the document output.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import shutil
import sys
import time
import uuid

from ocr_artifacts.atomic_io import atomic_write_json, replace
from ocr_artifacts.digest import sha256_json_ascii
from ocr_artifacts.hashing import sha256_file as sha256
from ocr_runtime.gpu_lease import GPULease, gpu_snapshot, lease_for_gpu  # re-exported
from ocr_runtime.paths import PROJECT_ROOT, absolute_path_env, v63_cache_root, worker_pythonpath
from ocr_runtime.process_tree import supervised_run

ROOT = PROJECT_ROOT
PROTOCOL = "document-two-phase-v1"
STAGE_KEY_SCHEMA = "stage-key-v1"
PHASES = ("text", "structure", "export")
CACHED_PHASES = ("text", "structure")


def validate_policy(device, allow_cpu_benchmark):
    if device not in ("cuda", "cpu"):
        raise ValueError("Two-phase device must be explicit cuda or cpu")
    if (device == "cpu") != bool(allow_cpu_benchmark):
        raise ValueError("CPU requires --device cpu --allow-cpu-benchmark; the flag is invalid with CUDA")


def stage_models(phase, models, config):
    """Model files a phase loads. Phase A's layout model is Docling's layout
    model too; a file of unknown role counts for every phase. The registry
    file is read only by the supervisor: its pinned files and the settings it
    copies into the config are key parts already. It stays in phase B's set
    so no registry edit goes unseen, and out of phase A's so a Docling model
    update still reuses phase A."""
    def path_of(value):
        return Path(value).resolve() if value else None
    detector = path_of(config.get("text_detector", {}).get("model_path"))
    layout = path_of(config.get("layout_model", {}).get("model_path"))
    font = path_of(config.get("bridge_font"))
    registry = path_of(ROOT / config["model_registry"]) if config.get("model_registry") else None
    selected = {}
    for name, digest in models.items():
        path = Path(name).resolve()
        if layout and (path == layout or layout in path.parents):
            owners = ("text", "structure")
        elif path == detector or "vietocr" in path.parts:
            owners = ("text",)
        elif "docling" in path.parts or path in (font, registry):
            owners = ("structure",)
        else:
            owners = PHASES
        if phase in owners:
            selected[name] = digest
    return selected


def stage_locks(phase, locks):
    """Phase B starts the Docling server; every phase runs in the text runtime."""
    return {name: digest for name, digest in locks.items()
            if phase == "structure" or not name.endswith("docling-gpu.lock")}


# Environment variables that choose which weights a phase process loads (F05).
# The pinned model paths already follow them (F06); this keeps the choice
# visible in the key. HF_HOME is not read: the Docling client sets it to
# `<models>/docling/huggingface` for its server.
STAGE_MODEL_ENV = {"text": ("OCR_MODELS_DIR", "VIETOCR_MODEL_DIR"), "structure": ("OCR_MODELS_DIR",),
                   "export": ()}


def stage_env(phase, environ=None):
    """The model-selecting variables as a phase worker reads them. The
    scheduler hands workers absolute values (P12); a relative one would be
    read from the checkout, their working directory."""
    environ = os.environ if environ is None else environ
    return {name: str((ROOT / Path(environ[name]).expanduser()).resolve()) if environ.get(name) else None
            for name in STAGE_MODEL_ENV[phase]}


def stage_key(phase, request, identity, input_receipt, code, coordinator, environ=None):
    config = request["config"]
    parts = {"code": code, "coordinator": coordinator, "device": request["device"], "python": identity["python"],
             "models": stage_models(phase, request["model_hashes"], config),
             "locks": stage_locks(phase, request["lock_hashes"]), "env": stage_env(phase, environ)}
    if phase == "text":
        text_config = copy.deepcopy(config)
        text_config.setdefault("docling", {})["enabled"] = False  # as phase A runs it
        parts.update(pdf=identity["pdf"], pages=identity["pages"], config=text_config)
    else:
        parts.update(input=sha256(input_receipt), config=config)
    if phase == "structure":
        parts["docling_python"] = str(Path(request["docling_python"]).absolute())
    if phase == "export":
        parts.update({name: request.get(name) for name in ("config_path", "assets", "output_mode", "keywords_file")},
                     finalize_document=bool(request.get("finalize_document", True)))
    return sha256_json_ascii({"schema_version": STAGE_KEY_SCHEMA, "stage": phase, "protocol": PROTOCOL, **parts})


def run_document(request, *, resume=False):
    validate_policy(request["device"], request.get("allow_cpu_benchmark", False))
    if "torch" in sys.modules:
        raise RuntimeError("GPU supervisor must start in a fresh interpreter without importing Torch")
    from ocr_runtime.fingerprint import coordinator_fingerprint, extraction_fingerprint, legacy_stage, stage_fingerprint
    snapshot = gpu_snapshot(request["device"])
    # Extraction code only (P11a): keyword/Excel edits keep phase checkpoints valid.
    identity = {"pdf": sha256(request["pdf"]), "source": extraction_fingerprint(),
                "config": request["config"], "pages": request.get("pages"),
                "device": request["device"], "python": str(Path(request["text_python"]).absolute()),
                "models": request["model_hashes"], "locks": request["lock_hashes"],
                "protocol": PROTOCOL}
    generation = sha256_json_ascii(identity)
    root = Path(request.get("work_dir", v63_cache_root() / "v62-jobs")) / generation
    cache = Path(request.get("stage_cache_dir", v63_cache_root() / "v63-stages"))
    # Path variables made absolute here: workers run from the checkout (P12).
    # The snapshot's model directories win over the current environment (F06).
    worker_environ = {**os.environ, **absolute_path_env(), **request.get("model_env", {})}
    root.mkdir(parents=True, exist_ok=True)
    request = {**request, "generation": generation, "identity": identity, "job_dir": str(root), "stages": {}}
    request_path = root / "request.json"
    # The request contains absolute runtime paths, never embedded shell commands.
    audit = {"schema_version": "document-two-phase-v1", "generation": generation,
             "status": "RUNNING", "parent_pid": os.getpid(), "parent_imported_torch": False,
             "device": request["device"], "initial_vram": snapshot, "events": [], "phases": {}}
    audit_path = root / "scheduler.json"
    acquired = False
    try:
        with lease_for_gpu(snapshot, timeout=request.get("lease_timeout", 60)):
            acquired = True
            upstream = None  # (phase, directory, key) of the stage this phase consumes
            coordinator = coordinator_fingerprint()
            for phase in PHASES:
                legacy = legacy_stage(phase, request["config"], request.get("finalize_document", True))
                code = stage_fingerprint(phase, legacy=legacy)
                input_receipt = upstream[1] / "done.json" if upstream else None
                key = stage_key(phase, request, identity, input_receipt, code, coordinator, worker_environ)
                stage = {"key": key, "code": code, "legacy": legacy, "reused": False}
                final = cache / phase / key if phase in CACHED_PHASES else root
                if resume and phase in CACHED_PHASES and committed_stage(final, phase, key, input_receipt):
                    receipt = json.loads((final / "done.json").read_text(encoding="utf-8"))
                    request["stages"][phase] = {**stage, "dir": str(final), "reused": True,
                                                "receipt_sha256": sha256(final / "done.json"),
                                                "produced_by_generation": receipt["generation"],
                                                "historical_seconds": receipt.get("seconds")}
                    audit["phases"][phase] = {"resumed": True, "key": key, "generation": receipt["generation"]}
                    upstream = (phase, final, key)
                    continue
                if upstream and not committed_stage(upstream[1], upstream[0], upstream[2]):
                    raise RuntimeError("Phase prerequisite checkpoint is missing or changed")
                # Never write into a committed directory: a new attempt gets its own.
                work = (cache / phase / f"{key}.tmp-{generation[:12]}-{uuid.uuid4().hex[:8]}"
                        if phase in CACHED_PHASES else root)
                work.mkdir(parents=True, exist_ok=True)
                request["stages"][phase] = {**stage, "dir": str(work)}
                atomic_write_json(request_path, request)
                env = dict(worker_environ)
                env.update(PYTHONIOENCODING="utf-8", PYTHONPATH=worker_pythonpath(),
                           OCR_DOCLING_PYTHON=request["docling_python"],
                           CUDA_VISIBLE_DEVICES="" if request["device"] == "cpu" or phase == "export" else "0",
                           TOKENIZERS_PARALLELISM="false")
                env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
                audit["events"].append({"phase": phase, "event": "START", "time_ns": time.time_ns(),
                                        "vram": gpu_snapshot(request["device"])})
                atomic_write_json(audit_path, audit)
                samples = []
                last_sample = [0.]
                def observe(pid, pids):
                    if time.monotonic() - last_sample[0] >= 2:
                        samples.append({"pid": pid, "tree": pids, **gpu_snapshot(request["device"])})
                        last_sample[0] = time.monotonic()
                command = [request["text_python"], "-m", "ocr_workers.phases",
                           "--request", str(request_path), "--phase", phase]
                (work / "exited.json").unlink(missing_ok=True)
                result = supervised_run(command, cwd=ROOT, env=env, log_path=root / f"{phase}.log",
                                        timeout=request.get("phase_timeout", 14400), observe=observe)
                if not valid_stage(work, phase, key, input_receipt):
                    raise RuntimeError(f"Invalid or incomplete {phase} checkpoint")
                atomic_write_json(work / "exited.json", {"receipt_sha256": sha256(work / "done.json"), "tree_exited": True})
                if phase in CACHED_PHASES:
                    commit_stage(work, final)
                receipt = json.loads((final / "done.json").read_text(encoding="utf-8"))
                request["stages"][phase].update(dir=str(final), receipt_sha256=sha256(final / "done.json"),
                                                produced_by_generation=receipt["generation"])
                upstream = (phase, final, key)
                audit["phases"][phase] = {**result, "key": key, "samples": samples}
                audit["events"].append({"phase": phase, "event": "TREE_EXITED", "time_ns": time.time_ns(),
                                        "vram": gpu_snapshot(request["device"])})
                atomic_write_json(audit_path, audit)
            audit["status"] = "COMPLETED"
    except BaseException as exc:
        audit.update(status="FAILED", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        if acquired:
            atomic_write_json(audit_path, audit)
    output = Path(request["output"]) / Path(request["pdf"]).stem
    atomic_write_json(output / "gpu_scheduler.json", audit)
    from ocr_pipeline.completion import mark_completed
    if request.get("finalize_document", True):
        mark_completed(output, json.loads((output / "validation.json").read_text(encoding="utf-8"))["status"])
    return {"output": str(output), "audit": str(audit_path), "generation": generation,
            "stages": {phase: {k: v for k, v in request["stages"][phase].items() if k in ("key", "reused")}
                       for phase in PHASES}}


def commit_stage(work, final):
    """Publish a verified stage directory under its key. An earlier directory
    of the same key (stale or concurrent) is moved aside first; Windows cannot
    rename onto an existing directory. The GPU lease serializes producers;
    transient Windows sharing locks are retried by `replace`."""
    if final.exists():
        aside = final.with_name(f"{final.name}.replaced-{uuid.uuid4().hex[:8]}")
        replace(final, aside)
        shutil.rmtree(aside, ignore_errors=True)
    replace(work, final)


def valid_stage(directory, phase, key, input_receipt=None):
    """`done.json` of this phase and key, every listed file unchanged, and the
    exact upstream receipt it was produced from."""
    try:
        directory = Path(directory)
        data = json.loads((directory / "done.json").read_text(encoding="utf-8"))
        if input_receipt is not None and data.get("input_receipt_sha256") != sha256(input_receipt):
            return False
        return (data["key"] == key and data["phase"] == phase and bool(data["files"]) and all(
            (directory / name).is_file() and sha256(directory / name) == digest
            for name, digest in data["files"].items()))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def committed_stage(directory, phase, key, input_receipt=None):
    """A valid stage whose producing process tree was verified to exit; a
    directory being written or left by a crash never qualifies."""
    try:
        ack = json.loads((Path(directory) / "exited.json").read_text(encoding="utf-8"))
        return (ack["tree_exited"] is True and valid_stage(directory, phase, key, input_receipt)
                and ack["receipt_sha256"] == sha256(Path(directory) / "done.json"))
    except (OSError, ValueError, KeyError, TypeError):
        return False
