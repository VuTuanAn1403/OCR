"""Compatibility alias: this module moved to `ocr_workers.phases` (migration P09).

The object registered under this name is `ocr_workers.phases` itself. Running this path
with `python -m` runs the new module as the main program.
"""
import runpy
import sys

if __name__ == "__main__":
    runpy.run_module("ocr_workers.phases", run_name="__main__", alter_sys=True)
else:
    import ocr_workers.phases as _module

    sys.modules[__name__] = _module
