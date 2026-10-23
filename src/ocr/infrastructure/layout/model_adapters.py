"""Compatibility alias: this module moved to `ocr_layout.model_adapters` (migration P06).

The object registered under this name is `ocr_layout.model_adapters` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_layout.model_adapters as _module

sys.modules[__name__] = _module
