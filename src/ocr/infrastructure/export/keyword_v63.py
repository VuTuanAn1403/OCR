"""Compatibility alias: this module moved to `ocr_reporting.workbooks` (migration P04).

The object registered under this name is `ocr_reporting.workbooks` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_reporting.workbooks as _module

sys.modules[__name__] = _module
