"""Compatibility alias: this module moved to `ocr_structure.diagram_builder` (migration P07).

The object registered under this name is `ocr_structure.diagram_builder` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_structure.diagram_builder as _module

sys.modules[__name__] = _module
