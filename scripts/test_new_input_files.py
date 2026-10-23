"""Compatibility command using the one supported pipeline.

Historical helper APIs remain available only as explicit research fixtures.
"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import src.ocr
from ocr_pipeline.cli import main as _main

def main(argv=None):
    return _main(True, argv=argv)

def __getattr__(name):
    if name.startswith("__"):
        raise AttributeError(name)
    from importlib import import_module
    return getattr(import_module("benchmark.baselines.legacy_cli.test_new_input_files"), name)

if __name__ == "__main__":
    raise SystemExit(main())
