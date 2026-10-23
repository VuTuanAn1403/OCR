"""Compatibility alias: this module moved to `ocr_contracts.subpage` (migration P02).

The object registered under this name is `ocr_contracts.subpage` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_contracts.subpage as _module

sys.modules[__name__] = _module
