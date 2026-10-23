"""Single source of processing profiles (ENV-13, H21).

Resolution order: explicit path, then `OCR_CONFIG_PATH`, then
`<repo>/config/profiles.yaml`. A missing file or an unknown profile is an
error; nothing silently falls back to another copy or to built-in defaults.
The V6.3 CLI takes `--config` or `<project root>/config/profiles-v63.yaml`
and never reads `OCR_CONFIG_PATH` (docs/architecture/CAU_HINH_VA_DU_LIEU.md).

A profile file declares `config_schema` and `pipeline` at its top (P12); the
CLI routes on the declared pipeline. Files from before P12 declare neither.
"""
from __future__ import annotations

import os
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from ocr_artifacts.digest import sha256_json_unicode

from ocr_runtime.paths import default_profile_path

DEFAULT_CONFIG_PATH = default_profile_path()


class ConfigError(ValueError):
    pass


CONFIG_SCHEMA = "ocr-profiles-v1"
PIPELINES = ("v6.3", "v6.2", "legacy")


def _declaration(data: Dict[str, Any], path: Path) -> Dict[str, Any]:
    declaration = {key: data[key] for key in ("config_schema", "pipeline") if key in data}
    if declaration.get("config_schema", CONFIG_SCHEMA) != CONFIG_SCHEMA:
        raise ConfigError(f"{path}: config_schema {declaration['config_schema']!r} is not {CONFIG_SCHEMA}")
    if declaration.get("pipeline", PIPELINES[0]) not in PIPELINES:
        raise ConfigError(f"{path}: pipeline must be one of {', '.join(PIPELINES)}, got {declaration['pipeline']!r}")
    return declaration


def read_declaration(config_path: str | Path) -> Dict[str, Any]:
    path = Path(config_path).expanduser()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"Cannot read profile config {path}: {exc}") from exc
    return _declaration(data if isinstance(data, dict) else {}, path)


def declared_pipeline(config_path: str | Path) -> Optional[str]:
    """The declared pipeline, or None for a file that declares none."""
    return read_declaration(config_path).get("pipeline")


DOCUMENT_LAYOUT_METHODS = ("legacy", "region_tree_graph_v1")
FURNITURE_METHODS = ("document_context_v3", "legacy_v6_1")


def furniture_settings(layout: Dict[str, Any]) -> Dict[str, Any]:
    """Furniture policy is independent of the page reading-order algorithm.

    The historical margin rule requires an explicit frozen-baseline opt-in.
    """
    value = layout.get("furniture", {})
    allowed = {"method", "min_pages", "window", "support_ratio", "position_tolerance", "edge_ratio",
               "token_similarity_threshold", "learning_pages"}
    if not isinstance(value, dict) or set(value) - allowed:
        raise ConfigError("document_layout.furniture has unknown settings or is not a mapping")
    method = value.get("method", "document_context_v3")
    if method not in FURNITURE_METHODS:
        raise ConfigError(f"furniture.method must be one of {FURNITURE_METHODS}")
    if method == "legacy_v6_1":
        if layout.get("method", "legacy") != "legacy" or set(value) != {"method"}:
            raise ConfigError("legacy_v6_1 requires legacy layout and accepts no evidence thresholds")
        return {"method": method}
    result = {"method": method, "min_pages": 3, "window": 12, "support_ratio": .6,
              "position_tolerance": .025, "edge_ratio": .20,
              "token_similarity_threshold": .96, "learning_pages": 20, **value}
    for key in ("min_pages", "window", "learning_pages"):
        if isinstance(result[key], bool) or not isinstance(result[key], int):
            raise ConfigError(f"furniture.{key} must be an integer")
    if result["min_pages"] < 3 or min(result["window"], result["learning_pages"]) < result["min_pages"]:
        raise ConfigError("furniture requires window and learning_pages >= min_pages >= 3")
    for key, maximum in (("support_ratio", 1.), ("position_tolerance", .5), ("edge_ratio", .5), ("token_similarity_threshold", 1.)):
        number = result[key]
        if (isinstance(number, bool) or not isinstance(number, (int, float))
                or not math.isfinite(number) or not 0 < number <= maximum):
            raise ConfigError(f"furniture.{key} must be finite in (0, {maximum}]")
    return result


def document_layout_settings(config: Dict[str, Any]) -> Dict[str, Any]:
    """Keep the selected reading order; resolve furniture at document scope."""
    value = config.get("document_layout", {"method": "legacy"})
    if (not isinstance(value, dict) or set(value) - {"method", "min_gap", "furniture"}
            or value.get("method", "legacy") not in DOCUMENT_LAYOUT_METHODS):
        raise ConfigError("document_layout accepts method: legacy | region_tree_graph_v1, min_gap and furniture")
    gap = value.get("min_gap", 3.)
    if isinstance(gap, bool) or not isinstance(gap, (int, float)) or not math.isfinite(gap) or gap <= 0:
        raise ConfigError("document_layout.min_gap must be finite and positive")
    furniture_settings(value)
    return {"method": "legacy", **value}


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
    if isinstance(data, dict):
        _declaration(data, path)
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
        document_layout_settings(profile)
    return path, profiles


def available_profiles(config_path: Optional[str | Path] = None) -> List[str]:
    return list(load_profiles(config_path)[1])


def get_profile(profiles: Dict[str, Dict[str, Any]], name: str) -> Dict[str, Any]:
    if name not in profiles:
        raise ConfigError(f"Unknown profile '{name}'. Available: {', '.join(profiles)}")
    return profiles[name]


def config_hash(config: Dict[str, Any]) -> str:
    """Stable 16-hex digest of a resolved profile."""
    return sha256_json_unicode(config, default=str)[:16]
