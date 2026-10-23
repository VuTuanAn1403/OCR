"""Inspect V6.2 readiness without creating a CUDA context in the parent.

This is a readiness report, not a production/GPU acceptance certificate. Model
inference and placement remain NOT_EVALUATED until selected checkpoints exist.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from contextlib import nullcontext

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ocr.runtime.atomic_io import atomic_write_json
from src.ocr.runtime.gpu_scheduler import gpu_snapshot, lease_for_gpu
# The probes live in ocr_runtime.preflight (runtime code must not import scripts/).
from ocr_runtime.preflight import CHILD_PROBE, inspect_environment, resolve_benchmark_policy  # noqa: F401


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True, choices=("cpu", "cuda"))
    parser.add_argument("--allow-cpu-benchmark", action="store_true")
    parser.add_argument("--env-root", type=Path, help="Probe the isolated V6.2 text/docling environments")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        purpose = resolve_benchmark_policy(args.device, args.allow_cpu_benchmark)
    except ValueError as exc:
        parser.error(str(exc))
    suffix = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    text_python = args.env_root / "text" / suffix if args.env_root else sys.executable
    default_worker = ROOT / ".venv-docling" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    worker = args.env_root / "docling" / suffix if args.env_root else Path(os.getenv("OCR_DOCLING_PYTHON", str(default_worker)))
    lease = lease_for_gpu(gpu_snapshot("cuda")) if args.env_root and args.device == "cuda" else nullcontext()
    with lease:
        reports = {"main": inspect_environment(text_python, args.device)}
        if worker.is_file():
            reports["docling"] = inspect_environment(worker, args.device, require_ort=False)
        else:
            reports["docling"] = {"status": "FAILED", "errors": [f"Missing interpreter: {worker}"]}
    capability_ready = bool(args.env_root) and all(r.get("status") == "CAPABILITY_ONLY" for r in reports.values())
    status = "CAPABILITY_READY" if capability_ready else "NOT_READY"
    report = {"schema_version": "v62-readiness-v1", "run_purpose": purpose,
              "status": status, "parent_cuda_initialized": False,
              "environments": reports,
              "release_gates": {"selected_layout_model": "NOT_EVALUATED",
                                "selected_text_detector": "NOT_EVALUATED",
                                "full_pipeline_gpu_placement": "NOT_EVALUATED",
                                "small_gpu_document_two_phase": "NOT_EVALUATED",
                                "gt_header_footer_reading_order": "NOT_EVALUATED",
                                "cpu_req_01_03": "NOT_EVALUATED"}}
    atomic_write_json(args.output, report)
    print(f"V6.2 readiness: {status}; model/soak/quality gates remain separate; report: {args.output.resolve()}")
    return 0 if capability_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
