"""Compatibility alias: this module moved to `ocr_contracts.page` (migration P02).

The object registered under this name is `ocr_contracts.page` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_contracts.page as _module

sys.modules[__name__] = _module
