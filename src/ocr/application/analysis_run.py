"""Compatibility alias: this module moved to `ocr_pipeline.analysis_run` (migration P09).

The object registered under this name is `ocr_pipeline.analysis_run` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_pipeline.analysis_run as _module

sys.modules[__name__] = _module
