"""Compatibility alias: this module moved to `ocr_document.ids` (migration P08).

The object registered under this name is `ocr_document.ids` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_document.ids as _module

sys.modules[__name__] = _module
