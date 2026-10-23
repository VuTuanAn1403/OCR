"""Compatibility alias: this module moved to `ocr_recognition.text_detector` (migration P06).

The object registered under this name is `ocr_recognition.text_detector` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_recognition.text_detector as _module

sys.modules[__name__] = _module
