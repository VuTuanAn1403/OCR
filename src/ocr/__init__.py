"""Legacy namespace `src.ocr`: frozen legacy code and compatibility aliases.

New code lives in the top-level `ocr_*` packages next to this directory. Make
them importable for every consumer of the old namespace (scripts, notebooks,
tests) that only put the repository root on `sys.path`. Workers receive the
same directories explicitly through `src.ocr.runtime.paths.code_roots()`. An
installed wheel has the `ocr_*` packages top-level already (P10).
"""
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent
if (_SRC / "ocr_runtime").is_dir() and str(_SRC) not in sys.path:
    sys.path.append(str(_SRC))
