"""Compatibility alias: this module moved to `ocr_contracts.quality` (migration P02).

The object registered under this name is `ocr_contracts.quality` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_contracts.quality as _module

sys.modules[__name__] = _module
