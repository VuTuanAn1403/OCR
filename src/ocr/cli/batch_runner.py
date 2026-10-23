"""Retired import path; execution uses the single supported pipeline.

Historical parsing/report helpers are loaded lazily for regression tools only.
"""
from ocr_pipeline.cli import main as _main


def main():
    return _main(True)


def __getattr__(name):
    if name.startswith("__"):
        raise AttributeError(name)
    from importlib import import_module
    return getattr(import_module("benchmark.baselines.legacy_cli.batch_runner"), name)


if __name__ == "__main__":
    raise SystemExit(main())
