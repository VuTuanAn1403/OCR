"""Run PDFs through the one product pipeline in a child process (V8-042).

Benchmark runners measure `ocr_pipeline.cli.main` exactly as the product runs
it: CUDA, every page, the unified profile, and a fresh output directory without
`--resume`, so no committed stage is reused. Nothing from the legacy `src.ocr`
namespace is imported here or by the runners built on this module.

A derived configuration keeps the base file's declarations (`config_schema`,
`pipeline`) and replaces only the one profile, so `prepare_backend` validates it
like the product configuration. The child process tree is sampled for peak RSS;
device VRAM comes from the scheduler's own samples in `gpu_scheduler.json`.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import yaml

from ocr_artifacts.atomic_io import atomic_write_text
from ocr_artifacts.hashing import sha256_file
from ocr_runtime.config import get_profile, load_profiles
from ocr_runtime.pipeline_policy import PROFILE

ROOT = Path(__file__).resolve().parents[1]

ENTRY_POINT = "ocr_pipeline.cli.main"
_ENTRY_CODE = "import sys; from ocr_pipeline.cli import main; sys.exit(main(False))"
# Mirrors the product CLI choices (src/ocr_pipeline/cli.py).
ASSET_MODES = ("png", "jpeg", "none")
OUTPUT_MODES = ("compact", "legacy")
PRODUCT_DEVICE = "cuda"


def file_sha256(path: Path) -> Optional[str]:
    """SHA-256 of a file, or None when it does not exist."""
    path = Path(path)
    return sha256_file(path) if path.is_file() else None


def _git(*args: str) -> Optional[bytes]:
    try:
        result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def git_state() -> Dict[str, Any]:
    """Commit and working-tree digest; untracked file contents count, as in the v6 run manifest."""
    commit, status = _git("rev-parse", "HEAD"), _git("status", "--porcelain")
    diff, untracked = _git("diff", "HEAD", "--binary"), _git("ls-files", "--others", "--exclude-standard", "-z")
    if commit is None or status is None or diff is None or untracked is None:
        return {"commit": None, "dirty": None, "uncommitted_diff_sha256": None}
    dirty = bool(status.strip())
    digest = hashlib.sha256(diff + status)
    untracked_hashes = {}
    for name in sorted(part for part in untracked.split(b"\0") if part):
        relative = os.fsdecode(name)
        value = file_sha256(ROOT / relative)
        untracked_hashes[relative] = value
        digest.update(name + b"\0" + (value or "missing").encode() + b"\0")
    return {"commit": commit.decode().strip(), "dirty": dirty,
            "uncommitted_diff_sha256": digest.hexdigest() if dirty else None,
            "untracked_files_sha256": untracked_hashes}


def code_identity() -> Dict[str, str]:
    from ocr_runtime.fingerprint import extraction_fingerprint, source_fingerprint
    return {"source_fingerprint": source_fingerprint(), "extraction_fingerprint": extraction_fingerprint()}


def read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def base_profile(config: Optional[str | Path] = None) -> tuple[Path, Dict[str, Any]]:
    """(config path, unified profile) the product would load for `--config`."""
    path, profiles = load_profiles(config)
    return path, dict(get_profile(profiles, PROFILE))


def write_config(base_config: Path, profile: Dict[str, Any], destination: Path) -> Path:
    """Write `profile` as the unified profile, keeping the base file's declarations."""
    document = yaml.safe_load(Path(base_config).read_text(encoding="utf-8")) or {}
    if not isinstance(document, dict):
        raise ValueError(f"{base_config} is not a profile mapping")
    document = {key: value for key, value in document.items() if key != "profiles"}
    document["profiles"] = {PROFILE: profile}
    atomic_write_text(Path(destination), yaml.safe_dump(document, allow_unicode=True, sort_keys=True))
    return Path(destination)


def product_command(pdf: str | Path, output: str | Path, *, config: Optional[str | Path] = None,
                    assets: str = "png", output_mode: str = "compact", python: Optional[str] = None) -> List[str]:
    if assets not in ASSET_MODES or output_mode not in OUTPUT_MODES:
        raise ValueError(f"Unsupported assets/output mode: {assets}/{output_mode}")
    command = [python or sys.executable, "-B", "-c", _ENTRY_CODE, str(Path(pdf).resolve()),
               "--output", str(Path(output).resolve()), "--assets", assets, "--output-mode", output_mode]
    if config is not None:
        command += ["--config", str(Path(config).resolve())]
    return command


def product_env() -> Dict[str, str]:
    paths = [str(ROOT / "src"), str(ROOT)]
    if os.environ.get("PYTHONPATH"):
        paths.append(os.environ["PYTHONPATH"])
    return {**os.environ, "PYTHONPATH": os.pathsep.join(paths), "PYTHONIOENCODING": "utf-8"}


def _launch(command: List[str], log) -> subprocess.Popen:
    return subprocess.Popen(command, cwd=ROOT, env=product_env(), stdout=log, stderr=subprocess.STDOUT)


class TreeMemorySampler:
    """Peak RSS of a process and all its descendants (the product's GPU workers)."""

    def __init__(self, pid: Optional[int], interval: float = 0.25):
        self.pid = pid
        self.interval = interval
        self.peak_bytes: Optional[int] = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        try:
            import psutil
            root = psutil.Process(self.pid)
        except Exception:  # psutil missing or the child already exited: peak stays unknown
            return
        while not self._stop.is_set():
            total = 0
            try:
                processes = [root, *root.children(recursive=True)]
            except psutil.NoSuchProcess:
                break
            except psutil.Error:  # e.g. AccessDenied while listing children: keep sampling the root
                processes = [root]
            for process in processes:
                try:
                    total += process.memory_info().rss
                except psutil.Error:
                    pass
            self.peak_bytes = max(self.peak_bytes or 0, total)
            self._stop.wait(self.interval)

    @property
    def peak_mb(self) -> Optional[float]:
        return None if self.peak_bytes is None else round(self.peak_bytes / 1024 ** 2, 1)

    def __enter__(self) -> "TreeMemorySampler":
        if self.pid is not None:
            self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join()


def peak_device_vram_mib(scheduler: Optional[Dict[str, Any]]) -> Optional[int]:
    """Largest device-wide `used_mib` the scheduler sampled; None if it recorded none."""
    if not scheduler:
        return None
    values = [sample.get("used_mib") for phase in (scheduler.get("phases") or {}).values()
              for sample in phase.get("samples") or []]
    values += [(event.get("vram") or {}).get("used_mib") for event in scheduler.get("events") or []]
    values = [value for value in values if isinstance(value, (int, float))]
    return max(values) if values else None


def run_product(pdf: str | Path, output: str | Path, *, config: Optional[str | Path] = None,
                assets: str = "png", output_mode: str = "compact", log_path: Optional[Path] = None,
                launch: Optional[Callable[[List[str], Any], Any]] = None,
                sample_interval: float = 0.25) -> Dict[str, Any]:
    """Run one PDF into a fresh `output` root; the document lands in output/<pdf stem>."""
    pdf, output = Path(pdf), Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"Product output must be fresh: {output}")
    command = product_command(pdf, output, config=config, assets=assets, output_mode=output_mode)
    log_path = Path(log_path) if log_path else output.with_name(output.name + ".log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    with log_path.open("wb") as log:
        process = (launch or _launch)(command, log)
        with TreeMemorySampler(getattr(process, "pid", None), sample_interval) as memory:
            returncode = process.wait()
    wall = time.perf_counter() - started
    document_dir = output / pdf.stem
    receipt = read_json(document_dir / "ocr_receipt.json") or {}
    completed = (document_dir / "COMPLETED.json").is_file()
    return {
        "entry_point": ENTRY_POINT, "command": command, "pdf": str(pdf), "pdf_sha256": file_sha256(pdf),
        "document_id": pdf.stem, "output_root": str(output), "output": str(document_dir), "log": str(log_path),
        "returncode": returncode, "wall_seconds": round(wall, 3), "peak_rss_mb": memory.peak_mb,
        "completed_marker": completed, "ocr_identity": receipt.get("ocr_identity"),
        "status": "COMPLETED" if returncode == 0 and completed else "FAILED",
    }
