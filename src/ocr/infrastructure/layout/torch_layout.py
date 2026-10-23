"""Compatibility alias: this module moved to `ocr_layout.torch_layout` (migration P06).

The object registered under this name is `ocr_layout.torch_layout` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_layout.torch_layout as _module

sys.modules[__name__] = _module
