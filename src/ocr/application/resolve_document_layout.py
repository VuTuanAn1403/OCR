"""Compatibility alias: this module moved to `ocr_document.resolve_document_layout` (migration P08).

The object registered under this name is `ocr_document.resolve_document_layout` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_document.resolve_document_layout as _module

sys.modules[__name__] = _module
