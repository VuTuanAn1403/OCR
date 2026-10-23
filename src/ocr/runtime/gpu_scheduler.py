"""Compatibility alias: this module moved to `ocr_pipeline.scheduler` (migration P09).

The object registered under this name is `ocr_pipeline.scheduler` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_pipeline.scheduler as _module

sys.modules[__name__] = _module
