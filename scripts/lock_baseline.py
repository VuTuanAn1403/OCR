"""Lock the identity of the production baseline before any challenger run (V8-001).

The lock reuses the production preflight instead of re-deriving it:
`ocr_pipeline.backend.prepare_backend` pins the profile, verifies every model
file against `models/v62/runtime-models.json`, pins both worker interpreters
and dependency locks, records the code fingerprints and probes the GPU under
the GPU lease. On top of that this tool records Git state, verifies each lock
inside its own interpreter, inventories the input PDFs with
`ocr_pipeline.batch.input_snapshot` and computes the per-document
`ocr_identity` exactly as `GPUProcessor.request_for` does.

It runs no OCR and loads no model in this process. Quality stays NOT_EVALUATED.
Output is a new JSON file under scratch/ (never overwritten).

Exit codes: 0 = LOCKED, 1 = lock written but INCOMPLETE or FAILED, 2 = could not run.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for entry in (ROOT / "src", ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from scripts import build_dev_context as dev_context  # noqa: E402

SCHEMA = "ocr-v8-baseline-lock-v1"
PROFILE = "unified_gpu_full_ocr"
CODE_SCOPE = ("src", "config", "models", "requirements", "scripts/docling_structure_worker.py", "pyproject.toml")
REQUEST_DEFAULTS = {"assets": "png", "output_mode": "compact"}  # ocr_pipeline.cli defaults
LOCK_PROBE = ("import json, sys\n"
              "from ocr_runtime.dependency_lock import verify_installed_lock\n"
              "print(json.dumps(verify_installed_lock(sys.argv[1])))\n")


def run(args, cwd=ROOT, env=None, timeout=120):
    return subprocess.run(args, cwd=cwd, env=env, capture_output=True, timeout=timeout,
                          creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def git_state(root: Path) -> dict:
    git = lambda *a: run(["git", *a], cwd=root)  # noqa: E731
    head = git("rev-parse", "HEAD")
    if head.returncode:
        raise ValueError("Cannot read Git HEAD")
    status = git("status", "--porcelain=v1", "-z", "--untracked-files=normal").stdout.decode("utf-8")
    records = [item for item in status.split("\0") if item]
    code = git("status", "--porcelain=v1", "--untracked-files=normal", "--", *CODE_SCOPE).stdout.decode("utf-8")
    return {"head": head.stdout.decode().strip(),
            "branch": git("branch", "--show-current").stdout.decode().strip() or None,
            "dirty": bool(records), "change_records": len(records),
            "full_diff_sha256": hashlib.sha256(git("diff", "--binary", "HEAD").stdout).hexdigest(),
            "code_scope": list(CODE_SCOPE),
            "code_scope_changes": [line for line in code.splitlines() if line],
            "code_scope_diff_sha256": hashlib.sha256(
                git("diff", "--binary", "HEAD", "--", *CODE_SCOPE).stdout).hexdigest(),
            "note": "Untracked files are listed by status only; the diff hashes cover tracked files."}


def gpu_state() -> dict:
    try:
        query = run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total",
                     "--format=csv,noheader"], timeout=30)
        header = run(["nvidia-smi"], timeout=30).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "NOT_EVALUATED", "error": str(exc)}
    if query.returncode:
        return {"status": "NOT_EVALUATED", "error": query.stderr.decode("utf-8", "replace")[-500:]}
    gpus = [dict(zip(("name", "driver", "memory_total"), [part.strip() for part in line.split(",")]))
            for line in query.stdout.decode("utf-8").splitlines() if line.strip()]
    cuda = re.search(r"CUDA Version:\s*([0-9.]+)", header)
    return {"status": "OBSERVED", "gpus": gpus, "driver_cuda_version": cuda.group(1) if cuda else None}


def verify_lock(python: str, lock: str) -> dict:
    from ocr_runtime.paths import worker_pythonpath
    env = {**os.environ, "PYTHONPATH": worker_pythonpath()}
    try:
        result = run([python, "-c", LOCK_PROBE, lock], env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "FAILED", "error": str(exc)}
    if result.returncode:
        return {"status": "FAILED", "error": result.stderr.decode("utf-8", "replace")[-1500:]}
    return json.loads(result.stdout.decode("utf-8").strip().splitlines()[-1])


def probe_runtimes(backend: dict) -> dict:
    from ocr_runtime import gpu_lease, preflight
    with gpu_lease.lease_for_gpu(gpu_lease.gpu_snapshot("cuda")):
        return {role: preflight.inspect_environment(backend[f"{role}_python"], "cuda", require_ort=role == "text")
                for role in ("text", "docling")}


def relative(path: str, root: Path) -> str:
    try:
        return Path(path).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path


def inputs(backend: dict, input_dir: Path) -> list[dict]:
    from ocr_pipeline.backend import GPUProcessor
    from ocr_pipeline.batch import input_snapshot
    processor = GPUProcessor(backend, **REQUEST_DEFAULTS)
    rows = []
    for record in input_snapshot(input_dir):
        row = {key: record.get(key) for key in ("id", "name", "size", "pdf_sha256", "total_pages",
                                                 "source_error", "duplicate_of")}
        row["ocr_identity"] = (processor.request_for(record, input_dir)["ocr_identity"]
                               if record.get("pdf_sha256") else None)
        rows.append(row)
    return rows


def matching_receipts(rows: list[dict], output_root: Path, root: Path) -> dict:
    identities = {row["ocr_identity"]: row["id"] for row in rows if row.get("ocr_identity")}
    matches = []
    for receipt in sorted(output_root.glob("*/*/ocr_receipt.json")) if output_root.is_dir() else []:
        try:
            identity = json.loads(receipt.read_text(encoding="utf-8")).get("ocr_identity")
        except (OSError, ValueError):
            continue
        if identity in identities:
            matches.append({"document": identities[identity], "receipt": relative(str(receipt), root)})
    return {"searched": f"{relative(str(output_root), root)}/*/*/ocr_receipt.json", "matches": matches,
            "note": "A match only means an existing extraction has the same identity; it is not re-validated here."}


def build_lock(root: Path, input_dir: Path, output_root: Path, *, gpu_preflight: bool = True) -> dict:
    from ocr_runtime.config import resolve_config_path
    from ocr_runtime.version import PIPELINE_VERSION
    lock = {"schema_version": SCHEMA, "captured_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "pipeline_version": PIPELINE_VERSION, "profile": PROFILE, "git": git_state(root), "gpu": gpu_state(),
            "request_defaults": REQUEST_DEFAULTS, "inference": "NOT_RUN", "quality": "NOT_EVALUATED"}
    problems = []
    try:
        from ocr_pipeline.backend import prepare_backend
        config_path = resolve_config_path(None)
        backend = prepare_backend(config_path, PROFILE, root / ".venv-v62", preflight=gpu_preflight)
    except Exception as exc:  # the production preflight decides; record why it refused
        lock.update(status="FAILED", error=f"{type(exc).__name__}: {exc}")
        return lock
    lock["code"] = {"code_fingerprints": backend["code_fingerprints"],
                    "source_fingerprint": backend["source_fingerprint"]}
    lock["config"] = {"path": relative(backend["config_path"], root),
                      "sha256": hashlib.sha256(Path(backend["config_path"]).read_bytes()).hexdigest(),
                      "profile_digest": digest(backend["config"])}
    models = {relative(path, root): checksum for path, checksum in backend["model_hashes"].items()}
    lock["models"] = {"registry": relative(backend["model_registry_path"], root), "files": len(models),
                      "verified_by": "ocr_pipeline.backend.prepare_backend (sha256 against registry)",
                      "sha256": dict(sorted(models.items()))}
    lock["interpreters"] = {role: relative(backend[f"{role}_python"], root) for role in ("text", "docling")}
    lock["locks"] = {}
    for path, checksum in backend["lock_hashes"].items():
        role = "docling" if "docling" in Path(path).name else "text"
        lock["locks"][relative(path, root)] = {"sha256": checksum, "interpreter": role,
                                                "installed": verify_lock(backend[f"{role}_python"], path)}
    if gpu_preflight:
        lock["runtime_probes"] = probe_runtimes(backend)
    else:
        lock["runtime_probes"] = "NOT_EVALUATED: --no-gpu-preflight"
        problems.append("GPU preflight skipped")
    lock["inputs"] = inputs(backend, input_dir)
    lock["existing_outputs"] = matching_receipts(lock["inputs"], output_root, root)
    lock["portable_identity"] = digest({"code": backend["code_fingerprints"], "config_sha256": lock["config"]["sha256"],
                                        "profile_digest": lock["config"]["profile_digest"],
                                        "models": sorted(models.values()),
                                        "locks": sorted(item["sha256"] for item in lock["locks"].values())})
    for path, item in lock["locks"].items():
        if item["installed"].get("status") != "VERIFIED":
            problems.append(f"Dependency lock not verified in its interpreter: {path}")
    if isinstance(lock["runtime_probes"], dict):
        problems += [f"Runtime probe failed: {role}" for role, probe in lock["runtime_probes"].items()
                     if probe.get("status") == "FAILED"]
    problems += [f"Input not usable: {row['name']}" for row in lock["inputs"]
                 if row.get("source_error") or not row.get("pdf_sha256")]
    if not lock["inputs"]:
        problems.append("No input PDF")
    lock["problems"] = problems
    lock["status"] = "INCOMPLETE" if problems else "LOCKED"
    return lock


def next_lock_id(root: Path, day: str) -> str:
    base = root / "scratch" / "benchmarks"
    used = {p.name for p in base.glob(f"BASELINE-V8-{day}-*")} if base.is_dir() else set()
    number = 1
    while f"BASELINE-V8-{day}-{number:03d}" in used:
        number += 1
    return f"BASELINE-V8-{day}-{number:03d}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, default=ROOT / "inputs", help="folder of input PDFs")
    parser.add_argument("--output-root", type=Path, default=ROOT / "output", help="where existing receipts live")
    parser.add_argument("--no-gpu-preflight", action="store_true", help="CPU-only check; the lock stays INCOMPLETE")
    args = parser.parse_args(argv)
    try:
        lock_id = next_lock_id(ROOT, dt.date.today().strftime("%Y%m%d"))
        lock = {"lock_id": lock_id, **build_lock(ROOT, args.input, args.output_root,
                                                  gpu_preflight=not args.no_gpu_preflight)}
        target = dev_context.write_snapshot(ROOT, f"scratch/benchmarks/{lock_id}/baseline_lock.json",
                                            json.dumps(lock, ensure_ascii=False, indent=2) + "\n")
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Cannot lock baseline: {exc}", file=sys.stderr)
        return 2
    print(f"{lock_id}: {lock['status']} -> {target}")
    for problem in lock.get("problems", []) + ([lock["error"]] if lock.get("error") else []):
        print(f"  - {problem}")
    return 0 if lock["status"] == "LOCKED" else 1


if __name__ == "__main__":
    sys.exit(main())
