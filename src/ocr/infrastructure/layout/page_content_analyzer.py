"""Compatibility alias: this module moved to `ocr_layout.page_content_analyzer` (migration P06).

The object registered under this name is `ocr_layout.page_content_analyzer` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_layout.page_content_analyzer as _module

sys.modules[__name__] = _module
