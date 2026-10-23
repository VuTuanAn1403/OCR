"""Compatibility alias: this module moved to `ocr_text.text_cleaner` (migration P05a).

The object registered under this name is `ocr_text.text_cleaner` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_text.text_cleaner as _module

sys.modules[__name__] = _module
