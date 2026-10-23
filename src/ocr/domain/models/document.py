"""Compatibility alias: this module moved to `ocr_contracts.document` (migration P02).

The object registered under this name is `ocr_contracts.document` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_contracts.document as _module

sys.modules[__name__] = _module
