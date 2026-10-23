"""Compatibility alias: this module moved to `ocr_contracts.diagram` (migration P02).

The object registered under this name is `ocr_contracts.diagram` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_contracts.diagram as _module

sys.modules[__name__] = _module
