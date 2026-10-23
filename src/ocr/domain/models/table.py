"""Compatibility alias: this module moved to `ocr_contracts.table` (migration P02).

The object registered under this name is `ocr_contracts.table` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_contracts.table as _module

sys.modules[__name__] = _module
