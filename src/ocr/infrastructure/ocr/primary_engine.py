"""Compatibility alias: this module moved to `ocr_recognition.primary_engine` (migration P06).

The object registered under this name is `ocr_recognition.primary_engine` itself, so imports,
`mock.patch` targets and isinstance checks behave as before.
"""
import sys

import ocr_recognition.primary_engine as _module

sys.modules[__name__] = _module
