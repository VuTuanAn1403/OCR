"""Hardware profiles (proposal V6 ENV-01): per-machine device, worker count,
thread budget, recognition batch size and persistent paths, kept apart from
the processing profiles in config/profiles.yaml.

Precedence: an explicit CLI flag, then the hardware profile, then the
processing profile/defaults. For paths an already-set `OCR_*_DIR` variable
wins over the file. Values reach the resolved configuration (device,
num_threads, batch_size), so they are hashed with every run; the file itself
is recorded in run_manifest.json.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from src.ocr.runtime.config import ConfigError
from src.ocr.runtime.device import VALID_DEVICES
from src.ocr.runtime.paths import hardware_profile_dir

PATH_VARIABLES = {"data_dir": "OCR_DATA_DIR", "output_dir": "OCR_OUTPUT_DIR",
                  "cache_dir": "OCR_CACHE_DIR", "models_dir": "OCR_MODELS_DIR"}
_KEYS = {"name", "description", "device", "workers", "threads_per_worker", "batch_size", "paths"}


@dataclass(frozen=True)
class HardwareProfile:
    name: str
    path: Path
    sha256: str
    device: Optional[str] = None
    workers: Optional[int] = None
    threads_per_worker: Optional[int] = None
    batch_size: Optional[int] = None
    paths: Dict[str, str] = field(default_factory=dict)

    def record(self) -> Dict[str, Any]:
        return {"name": self.name, "path": str(self.path), "sha256": self.sha256, "device": self.device,
                "workers": self.workers, "threads_per_worker": self.threads_per_worker,
                "batch_size": self.batch_size, "paths": dict(self.paths)}


def resolve_hardware_path(value: str | Path) -> Path:
    """A bare name selects config/hardware/<name>.yaml (bundled in wheels)."""
    path = Path(value).expanduser()
    if path.suffix not in (".yaml", ".yml") and len(path.parts) == 1:
        path = hardware_profile_dir() / f"{path.name}.yaml"
    if not path.is_file():
        raise ConfigError(f"Hardware profile not found: {path}")
    return path.resolve()


def _positive(data: Dict[str, Any], key: str, path: Path) -> Optional[int]:
    value = data.get(key)
    if value is not None and (type(value) is not int or value < 1):
        raise ConfigError(f"{path}: hardware.{key} must be a positive integer or null")
    return value


def load_hardware(value: str | Path) -> HardwareProfile:
    path = resolve_hardware_path(value)
    raw = path.read_bytes()
    try:
        document = yaml.safe_load(raw.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ConfigError(f"Cannot read hardware profile {path}: {exc}") from exc
    data = document.get("hardware") if isinstance(document, dict) else None
    if not isinstance(data, dict):
        raise ConfigError(f"{path} has no 'hardware' mapping")
    unknown = set(data) - _KEYS
    if unknown:
        raise ConfigError(f"{path}: unknown hardware keys {sorted(unknown)}")
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ConfigError(f"{path}: hardware.name is required")
    device = data.get("device")
    if device is not None and device not in VALID_DEVICES:
        raise ConfigError(f"{path}: hardware.device must be one of {', '.join(VALID_DEVICES)}")
    paths = data.get("paths") or {}
    if not isinstance(paths, dict) or set(paths) - set(PATH_VARIABLES) \
            or not all(isinstance(v, str) and v.strip() for v in paths.values()):
        raise ConfigError(f"{path}: hardware.paths accepts non-empty {', '.join(PATH_VARIABLES)}")
    return HardwareProfile(name=name, path=path, sha256=hashlib.sha256(raw).hexdigest(), device=device,
                           workers=_positive(data, "workers", path),
                           threads_per_worker=_positive(data, "threads_per_worker", path),
                           batch_size=_positive(data, "batch_size", path), paths=dict(paths))


def apply_paths(profile: Optional[HardwareProfile]) -> Dict[str, str]:
    """Export the profile's paths unless the variable is already set; returns
    the variables this call set."""
    applied: Dict[str, str] = {}
    if profile is None:
        return applied
    for key, variable in PATH_VARIABLES.items():
        if key in profile.paths and not os.getenv(variable):
            os.environ[variable] = profile.paths[key]
            applied[variable] = profile.paths[key]
    return applied


def preparse_hardware(argv=None) -> Optional[HardwareProfile]:
    """Load --hardware before the main parser so path defaults see it."""
    import argparse
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--hardware", default=None)
    known, _ = parser.parse_known_args(argv)
    if known.hardware is None:
        return None
    profile = load_hardware(known.hardware)
    apply_paths(profile)
    return profile
