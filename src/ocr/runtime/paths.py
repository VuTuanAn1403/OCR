"""Project paths, each overridable through an environment variable (ENV-03).

Defaults keep the historical CWD-relative layout (`inputs/`, `output/`,
`.cache/`) so existing commands behave the same when run from the repo root.
Functions rather than constants, so a changed environment applies at call time.
"""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def runtime_resource(name: str) -> Path:
    """Wheel copies are generated during build, never separately maintained."""
    return Path(__file__).resolve().parents[1] / "resources" / name


def default_profile_path() -> Path:
    if (PROJECT_ROOT / "pyproject.toml").is_file():
        return PROJECT_ROOT / "config/profiles.yaml"
    return runtime_resource("profiles.yaml")


def hardware_profile_dir() -> Path:
    if (PROJECT_ROOT / "pyproject.toml").is_file():
        return PROJECT_ROOT / "config/hardware"
    return runtime_resource("hardware")


def docling_worker_path() -> Path:
    if (PROJECT_ROOT / "pyproject.toml").is_file():
        return PROJECT_ROOT / "scripts/docling_structure_worker.py"
    return runtime_resource("docling_structure_worker.py")


def _env_dir(name: str, default: Path) -> Path:
    value = os.getenv(name)
    return Path(value).expanduser() if value else default


def data_dir() -> Path:
    """Input PDFs (`OCR_DATA_DIR`, default `inputs`)."""
    return _env_dir("OCR_DATA_DIR", Path("inputs"))


def output_dir() -> Path:
    """Extraction outputs (`OCR_OUTPUT_DIR`, default `output`)."""
    return _env_dir("OCR_OUTPUT_DIR", Path("output"))


def cache_dir() -> Path:
    """Page cache and Docling job files (`OCR_CACHE_DIR`, default `.cache`)."""
    return _env_dir("OCR_CACHE_DIR", Path(".cache"))


def models_dir() -> Path:
    """Model weights (`OCR_MODELS_DIR`, default `<repo>/models`)."""
    return _env_dir("OCR_MODELS_DIR", PROJECT_ROOT / "models")
