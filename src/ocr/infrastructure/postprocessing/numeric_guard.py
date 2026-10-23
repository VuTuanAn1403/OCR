"""Compatibility alias: this module moved to `ocr_text.numeric_guard` (migration P05a).

The object registered under this name is `ocr_text.numeric_guard` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_text.numeric_guard as _module

sys.modules[__name__] = _module
