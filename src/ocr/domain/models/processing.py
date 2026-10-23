"""Compatibility alias: this module moved to `ocr_contracts.processing` (migration P02).

The object registered under this name is `ocr_contracts.processing` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_contracts.processing as _module

sys.modules[__name__] = _module
