"""Compatibility alias: this module moved to `ocr_pipeline.completion` (migration P09).

The object registered under this name is `ocr_pipeline.completion` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_pipeline.completion as _module

sys.modules[__name__] = _module
