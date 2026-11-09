"""Benchmark package: GT evaluators, runners and challenger contracts.

The product packages (`ocr_*`) live in src/. The legacy `src.ocr` namespace used to put
that directory on sys.path as a side effect of being imported; benchmark code now imports
the packages directly (V8-042), so make them importable here.
"""
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if (_SRC / "ocr_runtime").is_dir() and str(_SRC) not in sys.path:
    sys.path.append(str(_SRC))
