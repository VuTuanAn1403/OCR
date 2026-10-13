"""Run manifest for baselines and acceptance runs (proposal section 6.5).

Records what is needed to reproduce or reject a measurement: commit and a hash
of uncommitted changes, config path and hash, model hashes, package versions,
hardware, device and the page-cache state (H24: pages restored from cache keep
the timings of an older run, so they must be visible).
"""
from __future__ import annotations

import hashlib
import copy
import os
import platform
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any, Dict, List, Optional

import psutil

from src.ocr.domain.models.schema import PAGE_SCHEMA_VERSION
from src.ocr.infrastructure.export.manifest_exporter import PIPELINE_VERSION
from src.ocr.runtime.atomic_io import atomic_write_json
from src.ocr.runtime.fingerprint import source_fingerprint
from src.ocr.runtime.models import model_hashes
from src.ocr.runtime.paths import PROJECT_ROOT

RUN_MANIFEST_SCHEMA = "run-manifest-v1"
_PACKAGES = ("pymupdf", "torch", "torchvision", "vietocr", "rapidocr-onnxruntime", "onnxruntime",
             "onnxruntime-gpu", "numpy", "opencv-python-headless", "pydantic", "PyYAML")


def file_sha256(path: Path) -> Optional[str]:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(*args: str) -> Optional[bytes]:
    try:
        return subprocess.run(["git", *args], cwd=PROJECT_ROOT, capture_output=True,
                              check=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return None


def git_state() -> Dict[str, Any]:
    commit = _git("rev-parse", "HEAD")
    status = _git("status", "--porcelain")
    diff = _git("diff", "HEAD", "--binary")
    untracked = _git("ls-files", "--others", "--exclude-standard", "-z")
    if commit is None or status is None or diff is None or untracked is None:
        return {"commit": None, "dirty": None, "uncommitted_diff_sha256": None}
    dirty = bool(status.strip())
    digest = hashlib.sha256(diff + status)
    untracked_hashes = {}
    for name in sorted(part for part in untracked.split(b"\0") if part):
        relative = os.fsdecode(name)
        path = PROJECT_ROOT / relative
        if path.is_symlink():
            value = hashlib.sha256(os.fsencode(os.readlink(path))).hexdigest()
        else:
            value = file_sha256(path)
        untracked_hashes[relative] = value
        digest.update(name + b"\0" + (value or "missing").encode() + b"\0")
    return {
        "commit": commit.decode().strip(),
        "dirty": dirty,
        # Include untracked contents: V6 sources may not be committed yet,
        # and a listing alone cannot identify the code that produced a run.
        "uncommitted_diff_sha256": digest.hexdigest() if dirty else None,
        "untracked_files_sha256": untracked_hashes,
    }


def package_versions() -> Dict[str, Optional[str]]:
    versions: Dict[str, Optional[str]] = {}
    for name in _PACKAGES:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def hardware_info() -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "platform": platform.platform(),
        "processor": platform.processor(),
        "cpu_count_physical": psutil.cpu_count(logical=False),
        "cpu_count_logical": psutil.cpu_count(logical=True),
        "total_ram_gb": round(psutil.virtual_memory().total / 1024 ** 3, 2),
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
        "cuda_available": False,
    }
    try:
        import torch
        info["torch_cuda_version"] = torch.version.cuda
        if torch.cuda.is_available():
            info["cuda_available"] = True
            info["gpu_name"] = torch.cuda.get_device_name(0)
            info["gpu_total_vram_gb"] = round(torch.cuda.get_device_properties(0).total_memory / 1024 ** 3, 2)
    except ImportError:
        pass
    return info


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunRecorder:
    """Collects one run's metadata; `write` emits `run_manifest.json`."""

    def __init__(self, kind: str, *, config_path: Path, profile: str, profile_config: Dict[str, Any],
                 device: str, cache_dir: Path, resume: bool, assets_mode: str,
                 argv: Optional[List[str]] = None):
        cache_dir = Path(cache_dir)
        self.data: Dict[str, Any] = {
            "schema": RUN_MANIFEST_SCHEMA,
            "run_id": f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}",
            "kind": kind,
            "argv": list(sys.argv if argv is None else argv),
            "started_at_utc": _now(),
            "finished_at_utc": None,
            "status": "RUNNING",
            "pipeline_version": PIPELINE_VERSION,
            "page_schema_version": PAGE_SCHEMA_VERSION,
            "source_fingerprint": source_fingerprint(),
            "git": git_state(),
            "config": {"path": str(config_path), "sha256": file_sha256(Path(config_path)),
                       "profile": profile, "resolved": copy.deepcopy(profile_config)},
            "device": device,
            "assets_mode": assets_mode,
            "models": model_hashes(profile_config),
            "packages": package_versions(),
            "hardware": hardware_info(),
            "cache": {"dir": str(cache_dir.resolve()),
                      "empty_at_start": not any(cache_dir.iterdir()) if cache_dir.is_dir() else True,
                      "resume": resume, "pages_from_cache": 0},
            "documents": [],
        }

    @property
    def run_id(self) -> str:
        return self.data["run_id"]

    def add_document(self, doc: Any) -> None:
        """Record an ExtractedDocument (or a failure dict)."""
        if isinstance(doc, dict):
            cached_pages = doc.get("pages_from_cache", [])
            self.data["cache"]["pages_from_cache"] += len(cached_pages)
            self.data["documents"].append(copy.deepcopy(doc))
            return
        from_cache = [p.page_num for p in doc.pages if p.quality.from_cache]
        self.data["cache"]["pages_from_cache"] += len(from_cache)
        self.data["documents"].append({
            "document_id": doc.document_id,
            "file_sha256_16": doc.file_hash,
            "pages": doc.selected_pages,
            "pages_from_cache": from_cache,
            "timing": doc.timing,
        })

    def write(self, path: Path, *, final: bool = True) -> Path:
        self.data["status"] = "COMPLETED" if final else "RUNNING"
        self.data["finished_at_utc"] = _now() if final else None
        # First-run downloads can add weights after recording the start.
        self.data["models_at_finish"] = model_hashes(self.data["config"]["resolved"])
        atomic_write_json(Path(path), self.data)
        return Path(path)
