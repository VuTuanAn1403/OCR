"""GPU environment readiness probes, run in the target interpreter.

The orchestrating interpreter never imports Torch or creates a CUDA context:
each environment is probed by a short child process. A readiness report is
not GPU inference evidence.
"""
from __future__ import annotations

import json
import os
import subprocess

from ocr_runtime.backend_probe import validate_ort_environment
from ocr_runtime.paths import PROJECT_ROOT

CHILD_PROBE = r'''
import json, sys
from importlib import metadata
device = sys.argv[1]
require_ort = sys.argv[2] == "true"
report = {"device": device, "packages": {}, "errors": [],
          "python_executable": sys.executable, "python_prefix": sys.prefix,
          "python_base_prefix": sys.base_prefix}
for name in ("onnxruntime", "onnxruntime-gpu", "rapidocr-onnxruntime", "torch", "docling-slim"):
    try: report["packages"][name] = metadata.version(name)
    except metadata.PackageNotFoundError: pass
if require_ort:
    try:
        import onnxruntime as ort
        report["available_providers"] = ort.get_available_providers()
    except Exception as exc: report["errors"].append(str(exc))
try:
    import torch
    if device == "cuda":
        if not torch.cuda.is_available(): raise RuntimeError("Torch CUDA unavailable")
        x = torch.ones((16, 16), device="cuda")
        y = x @ x
        torch.cuda.synchronize()
        report["torch_actual_device"] = str(y.device)
        report["gpu_total_gib"] = torch.cuda.get_device_properties(0).total_memory / 1024**3
    else:
        x = torch.ones((16, 16), device="cpu")
        y = x @ x
        report["torch_actual_device"] = str(y.device)
    report["torch_smoke_value"] = float(y[0, 0])
except Exception as exc: report["errors"].append(str(exc))
print(json.dumps(report))
'''


def resolve_benchmark_policy(device, allow_cpu_benchmark):
    if device not in ("cpu", "cuda"):
        raise ValueError("Device must be explicit cpu or cuda")
    if device == "cpu" and not allow_cpu_benchmark:
        raise ValueError("CPU V6.2 requires --device cpu --allow-cpu-benchmark")
    if allow_cpu_benchmark and device != "cpu":
        raise ValueError("--allow-cpu-benchmark is valid only with explicit --device cpu")
    return "cpu_acceptance_benchmark" if device == "cpu" else "gpu_production_readiness"


def inspect_environment(python, device, *, require_ort=True):
    # This process exits before another environment is probed. No Torch import
    # or torch.cuda call is made by the orchestrating interpreter.
    result = subprocess.run([str(python), "-c", CHILD_PROBE, device, str(require_ort).lower()], cwd=PROJECT_ROOT,
                            capture_output=True, text=True, encoding="utf-8", timeout=90,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if result.returncode:
        return {"python": str(python), "status": "FAILED", "errors": [result.stderr[-2000:]]}
    try:
        report = json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError) as exc:
        return {"python": str(python), "status": "FAILED", "errors": [f"Invalid probe response: {exc}"]}
    try:
        if require_ort or any(name in report["packages"] for name in ("onnxruntime", "onnxruntime-gpu", "rapidocr-onnxruntime")):
            report["ort_environment"] = validate_ort_environment(device, report["packages"])
    except RuntimeError as exc:
        report["errors"].append(str(exc))
    required = "CUDAExecutionProvider" if device == "cuda" else "CPUExecutionProvider"
    if require_ort and required not in report.get("available_providers", []):
        report["errors"].append(f"{required} unavailable")
    report.update(python=str(python), status="FAILED" if report["errors"] else "CAPABILITY_ONLY",
                  model_inference="NOT_EVALUATED", operator_placement="NOT_EVALUATED")
    return report
