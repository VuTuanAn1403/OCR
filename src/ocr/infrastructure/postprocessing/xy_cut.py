"""Compatibility alias: this module moved to `ocr_document.xy_cut` (migration P08).

The object registered under this name is `ocr_document.xy_cut` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_document.xy_cut as _module

sys.modules[__name__] = _module
