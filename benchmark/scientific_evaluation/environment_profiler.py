"""
Environment & Hardware Profiler and CPU Latency Compliance Verifier.
Adheres strictly to RESEARCH_PROTOCOL_V5.md Section 5:
- Records CPU, RAM, OS, library versions, model weights & hashes, git commit, and config hash.
- Enforces the user-confirmed CPU latency upper bounds:
    - Native text layer: <= 0.15 s/page
    - Mixed: <= 1.80 s/page
    - Scanned: <= 2.50 s/page
"""

import os
import sys
import platform
import psutil
import hashlib
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional


TARGET_CPU_LIMITS = {
    "NATIVE": 0.15,
    "MIXED": 1.80,
    "SCANNED": 2.50,
}


def compute_file_sha256(filepath: Path) -> Optional[str]:
    """Computes SHA256 hex digest of a file."""
    if not filepath.is_file():
        return None
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def get_git_commit_hash(repo_dir: Path) -> Dict[str, Any]:
    """Retrieves git commit hash and working tree status."""
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(repo_dir), text=True
        ).strip()
        status = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=str(repo_dir), text=True
        ).strip()
        is_clean = len(status) == 0
        return {"commit_hash": commit, "is_clean": is_clean}
    except Exception as e:
        return {"commit_hash": "unknown", "error": str(e), "is_clean": False}


def capture_environment_metadata(workspace_root: Path) -> Dict[str, Any]:
    """
    Captures complete hardware, OS, Python, libraries, model weights, and git metadata.
    """
    mem = psutil.virtual_memory()

    # Package versions
    packages = {}
    for pkg in [
        "torch", "pymupdf", "rapidocr_onnxruntime", "onnxruntime",
        "vietocr", "scipy", "apted", "bs4", "numpy", "psutil"
    ]:
        try:
            mod = __import__(pkg)
            packages[pkg] = getattr(mod, "__version__", "installed")
        except ImportError:
            packages[pkg] = "not_installed"

    # Model weight hashes
    models_dir = workspace_root / "models"
    model_hashes = {}
    if models_dir.exists():
        for model_path in models_dir.rglob("*.pth"):
            model_hashes[model_path.name] = compute_file_sha256(model_path)
        for model_path in models_dir.rglob("*.onnx"):
            model_hashes[model_path.name] = compute_file_sha256(model_path)

    # Config hash
    config_file = workspace_root / "config" / "profiles.yaml"
    config_hash = compute_file_sha256(config_file) if config_file.exists() else None

    # Git metadata
    git_meta = get_git_commit_hash(workspace_root)

    return {
        "hardware": {
            "processor": platform.processor(),
            "cpu_count_physical": psutil.cpu_count(logical=False),
            "cpu_count_logical": psutil.cpu_count(logical=True),
            "total_ram_gb": round(mem.total / (1024 ** 3), 2),
            "available_ram_gb": round(mem.available / (1024 ** 3), 2),
        },
        "operating_system": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
        },
        "runtime": {
            "python_version": platform.python_version(),
            "python_executable": sys.executable,
        },
        "libraries": packages,
        "models": model_hashes,
        "config_sha256": config_hash,
        "git": git_meta,
        "target_cpu_limits": TARGET_CPU_LIMITS,
    }


def verify_cpu_latency_compliance(
    category: str,
    measured_seconds_per_page: float
) -> Dict[str, Any]:
    """
    Verifies whether the measured average latency satisfies the user-confirmed CPU limits.
    """
    cat_key = category.upper()
    if "NATIVE" in cat_key:
        limit = TARGET_CPU_LIMITS["NATIVE"]
        expected_range = "0.05 - 0.15s"
    elif "MIXED" in cat_key:
        limit = TARGET_CPU_LIMITS["MIXED"]
        expected_range = "0.80 - 1.80s"
    else:  # SCANNED or default
        limit = TARGET_CPU_LIMITS["SCANNED"]
        expected_range = "1.50 - 2.50s"

    passed = measured_seconds_per_page <= limit
    return {
        "category": cat_key,
        "measured_seconds_per_page": round(measured_seconds_per_page, 4),
        "upper_limit_seconds": limit,
        "expected_range": expected_range,
        "is_compliant": passed,
    }
