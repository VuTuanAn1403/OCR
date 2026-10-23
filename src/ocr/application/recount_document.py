"""Compatibility alias: this module moved to `ocr_pipeline.recount` (migration P09).

The object registered under this name is `ocr_pipeline.recount` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_pipeline.recount as _module

sys.modules[__name__] = _module
