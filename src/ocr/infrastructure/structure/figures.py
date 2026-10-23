"""Compatibility alias: this module moved to `ocr_document.figures` (migration P08).

The object registered under this name is `ocr_document.figures` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_document.figures as _module

sys.modules[__name__] = _module
