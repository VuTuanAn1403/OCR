"""Compatibility alias: this module moved to `ocr_keywords.counter` (migration P03).

The object registered under this name is `ocr_keywords.counter` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_keywords.counter as _module

sys.modules[__name__] = _module
