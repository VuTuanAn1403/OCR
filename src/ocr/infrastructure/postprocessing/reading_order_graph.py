"""Compatibility alias: this module moved to `ocr_document.reading_order_graph` (migration P08).

The object registered under this name is `ocr_document.reading_order_graph` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_document.reading_order_graph as _module

sys.modules[__name__] = _module
