"""Compatibility import path for the one supported application CLI.

No routing by backend, profile name, configuration filename or hardware.
"""
from ocr_pipeline.cli import main


def run_one():
    return main(False)


def run_batch():
    return main(True)
