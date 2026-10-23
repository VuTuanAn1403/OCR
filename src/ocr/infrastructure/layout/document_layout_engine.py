"""Compatibility alias: this module moved to `ocr_structure.document_layout_engine` (migration P07).

The object registered under this name is `ocr_structure.document_layout_engine` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_structure.document_layout_engine as _module

sys.modules[__name__] = _module
