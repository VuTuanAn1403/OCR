"""Compatibility alias: this module moved to `ocr_runtime.device` (migration P05a).

The object registered under this name is `ocr_runtime.device` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_runtime.device as _module

sys.modules[__name__] = _module
