"""Compatibility alias: this module moved to `ocr_contracts.region` (migration P02).

The object registered under this name is `ocr_contracts.region` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_contracts.region as _module

sys.modules[__name__] = _module
