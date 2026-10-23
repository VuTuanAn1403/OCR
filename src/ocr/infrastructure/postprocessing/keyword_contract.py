"""Compatibility alias: this module moved to `ocr_keywords.contract` (migration P03).

The object registered under this name is `ocr_keywords.contract` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_keywords.contract as _module

sys.modules[__name__] = _module
