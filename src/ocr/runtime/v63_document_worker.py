"""Compatibility alias: this module moved to `ocr_pipeline.document_owner` (migration P09).

The object registered under this name is `ocr_pipeline.document_owner` itself. Running this path
with `python -m` runs the new module as the main program.
"""
import runpy
import sys

if __name__ == "__main__":
    runpy.run_module("ocr_pipeline.document_owner", run_name="__main__", alter_sys=True)
else:
    import ocr_pipeline.document_owner as _module

    sys.modules[__name__] = _module
