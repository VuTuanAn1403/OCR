"""Compatibility alias: this module moved to `ocr_text.unicode_normalizer` (migration P05a).

The object registered under this name is `ocr_text.unicode_normalizer` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_text.unicode_normalizer as _module

sys.modules[__name__] = _module
