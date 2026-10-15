"""Single source of processing profiles (ENV-13, H21).

Resolution order: explicit path, then `OCR_CONFIG_PATH`, then
`<repo>/config/profiles.yaml`. A missing file or an unknown profile is an
error; nothing silently falls back to another copy or to built-in defaults.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from src.ocr.runtime.paths import default_profile_path

DEFAULT_CONFIG_PATH = default_profile_path()


class ConfigError(ValueError):
    pass


def resolve_config_path(config_path: Optional[str | Path] = None) -> Path:
    if config_path:
        path, origin = Path(config_path), "argument"
    elif os.getenv("OCR_CONFIG_PATH"):
        path, origin = Path(os.environ["OCR_CONFIG_PATH"]), "OCR_CONFIG_PATH"
    else:
        path, origin = DEFAULT_CONFIG_PATH, "default"
    path = path.expanduser()
    if not path.is_file():
        raise ConfigError(f"Profile config not found: {path} (from {origin})")
    return path.resolve()


def load_profiles(config_path: Optional[str | Path] = None) -> Tuple[Path, Dict[str, Dict[str, Any]]]:
    path = resolve_config_path(config_path)
    try:
        with path.open("r", encoding="utf-8") as stream:
            data = yaml.safe_load(stream)
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"Cannot read profile config {path}: {exc}") from exc
    profiles = data.get("profiles") if isinstance(data, dict) else None
    if not isinstance(profiles, dict) or not profiles:
        raise ConfigError(f"{path} has no 'profiles' mapping")
    for name, profile in profiles.items():
        if not isinstance(name, str) or not name.strip():
            raise ConfigError(f"{path}: profile names must be non-empty strings")
        if not isinstance(profile, dict):
            raise ConfigError(f"{path}: profile '{name}' is not a mapping")
        if "profile" in profile and profile["profile"] != name:
            raise ConfigError(f"{path}: profile '{name}' declares a different name '{profile['profile']}'")
        profile.setdefault("profile", name)
    return path, profiles


def available_profiles(config_path: Optional[str | Path] = None) -> List[str]:
    return list(load_profiles(config_path)[1])


def get_profile(profiles: Dict[str, Dict[str, Any]], name: str) -> Dict[str, Any]:
    if name not in profiles:
        raise ConfigError(f"Unknown profile '{name}'. Available: {', '.join(profiles)}")
    return profiles[name]


def config_hash(config: Dict[str, Any]) -> str:
    """Stable 16-hex digest of a resolved profile."""
    payload = json.dumps(config, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
