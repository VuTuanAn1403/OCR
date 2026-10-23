"""Compatibility alias: this module moved to `ocr_structure.hidden_text_layer` (migration P07).

The object registered under this name is `ocr_structure.hidden_text_layer` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_structure.hidden_text_layer as _module

sys.modules[__name__] = _module
