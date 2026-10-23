"""Compatibility alias: this module moved to `ocr_document.section_tree` (migration P08).

The object registered under this name is `ocr_document.section_tree` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_document.section_tree as _module

sys.modules[__name__] = _module
