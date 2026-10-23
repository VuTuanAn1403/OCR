"""Compatibility alias: this module moved to `ocr_recognition.vietnamese_quality` (migration P06).

The object registered under this name is `ocr_recognition.vietnamese_quality` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_recognition.vietnamese_quality as _module

sys.modules[__name__] = _module
