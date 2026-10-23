"""Compatibility alias: this module moved to `ocr_pipeline.keyword_finalization` (migration P09).

The object registered under this name is `ocr_pipeline.keyword_finalization` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_pipeline.keyword_finalization as _module

sys.modules[__name__] = _module
