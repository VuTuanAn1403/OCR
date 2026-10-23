"""Compatibility alias: this module moved to `ocr_runtime.backend_probe` (migration P05a).

The object registered under this name is `ocr_runtime.backend_probe` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_runtime.backend_probe as _module

sys.modules[__name__] = _module
