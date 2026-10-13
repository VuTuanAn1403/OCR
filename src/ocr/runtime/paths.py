"""Project paths, each overridable through an environment variable (ENV-03).

Defaults keep the historical CWD-relative layout (`inputs/`, `output/`,
`.cache/`) so existing commands behave the same when run from the repo root.
Functions rather than constants, so a changed environment applies at call time.
"""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]


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
